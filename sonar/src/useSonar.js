// useSonar — the shared "brain" for the Sonar app. Holds all state, derived
// memos, and handlers so the desktop and mobile views render from one source of
// truth (same layers, playlist, player, and audio element). Lifted verbatim
// from the original monolithic Sonar.jsx; view-specific map geometry (zoomBy,
// pan, nearest-track, dotPos) stays in each view since desktop is landscape and
// mobile is portrait.
import React from 'react';
import { API } from './api.js';
import { Labels } from './labels.js';
import { Cache, FALLBACK_SUGGESTIONS } from './cache.js';
import { LAYER_COLORS, CANDIDATE_COLOR, FALLBACK_COLOR, distBetween, layerTag, makeGalaxy } from './sonar-utils.jsx';

const STORE_KEY = 'sonar-state-v1';

// Number of amplitude buckets in a real waveform (matches the bar count the
// players render). Kept here so peak extraction and rendering agree.
export const WAVE_BUCKETS = 56;

// Downsample a decoded AudioBuffer into `buckets` peak amplitudes in [0.08,1].
// Channel 0 is enough for a visual envelope; the floor keeps quiet sections
// from disappearing entirely.
function computePeaks(audioBuffer, buckets = WAVE_BUCKETS) {
  const ch = audioBuffer.getChannelData(0);
  const size = Math.floor(ch.length / buckets) || 1;
  const out = new Array(buckets).fill(0);
  let max = 0;
  for (let b = 0; b < buckets; b++) {
    let peak = 0;
    const start = b * size;
    const end = Math.min(ch.length, start + size);
    for (let i = start; i < end; i++) {
      const v = Math.abs(ch[i]);
      if (v > peak) peak = v;
    }
    out[b] = peak;
    if (peak > max) max = peak;
  }
  const norm = max > 0 ? 1 / max : 1;
  for (let b = 0; b < buckets; b++) out[b] = Math.max(0.08, out[b] * norm);
  return out;
}

// Responsive breakpoint helper — true on phone-sized viewports. Shared by the
// Sonar shell to pick the mobile vs desktop view.
// Either dimension ≤640 counts as mobile, but the short-side clause is gated on a
// coarse pointer so a *rotated phone* (landscape: wide but short, touch) stays on
// the mobile view, while a merely short desktop window (mouse) does not.
export function useIsMobile(query = '(max-width: 640px), (max-height: 640px) and (pointer: coarse)') {
  const get = () => (typeof window !== 'undefined' && window.matchMedia
    ? window.matchMedia(query).matches : false);
  const [isMobile, setIsMobile] = React.useState(get);
  React.useEffect(() => {
    if (!window.matchMedia) return undefined;
    const mql = window.matchMedia(query);
    const onChange = () => setIsMobile(mql.matches);
    onChange();
    mql.addEventListener('change', onChange);
    return () => mql.removeEventListener('change', onChange);
  }, [query]);
  return isMobile;
}

export function useSonar({ initialView = 'map' } = {}) {
  // ---- persisted bootstrap ----
  const boot = React.useMemo(() => {
    try {
      const raw = localStorage.getItem(STORE_KEY);
      return raw ? JSON.parse(raw) : null;
    } catch { return null; }
  }, []);

  const [view, setView] = React.useState(boot?.view || initialView);
  const [vibeQuery, setVibeQuery] = React.useState('');
  const [suggestions, setSuggestions] = React.useState(FALLBACK_SUGGESTIONS);
  const [aboutOpen, setAboutOpen] = React.useState(false);

  // ---- search layers ----
  const colorIdxRef = React.useRef(boot?.colorIdx || 0);
  // A new layer takes the first palette color no current layer is using, so
  // colors never collide while ≤8 searches are active (the persisted round
  // robin index is only a fallback once every hue is taken).
  const pickColor = (existing = []) => {
    const used = new Set(existing.map((l) => l.color));
    return LAYER_COLORS.find((c) => !used.has(c))
      || LAYER_COLORS[colorIdxRef.current++ % LAYER_COLORS.length];
  };
  const makeLayer = React.useCallback((kind, extra, existing = []) => ({
    id: `L_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`,
    kind,
    label: '',
    query: '',
    seedTrackId: null,
    seedTrack: null,
    color: pickColor(existing),
    visible: true,
    loading: false,
    fetched: false,
    results: [],
    enhancedQuery: null,
    searchId: null,
    ...extra,
  }), []);

  // Restored layers come back fetched (results inline) so a refresh doesn't
  // re-hit the API; brand-new sessions start empty (suggestions are shown but
  // nothing is auto-selected).
  const [layers, setLayers] = React.useState(() =>
    (boot?.layers || []).map((l) => ({ ...l, loading: false, fetched: true })));

  const [playingId, setPlayingId] = React.useState(null);
  // Hold the playing track object too, so the player keeps showing it even after
  // it's removed from every layer/playlist (tracksById would otherwise drop it).
  const [playingTrack, setPlayingTrack] = React.useState(null);
  // …and a snapshot of its origin (layer/playlist color + tag), so the now-playing
  // track keeps its color and source tag (and stays peekable) after its layer is
  // removed.
  const [playingOrigin, setPlayingOrigin] = React.useState(null);
  const [hoverId, setHoverId] = React.useState(null);
  const [selectedId, setSelectedId] = React.useState(null);
  const [isPlaying, setIsPlaying] = React.useState(false);
  const [progress, setProgress] = React.useState(0);
  const [duration, setDuration] = React.useState(0);
  // Real waveform peaks for the playing track (null = use the pseudo-envelope).
  const [peaks, setPeaks] = React.useState(null);

  // ---- whole-corpus map probing ----
  // `backdrop` is a procedural galaxy starfield (generated once, so it paints on
  // the first render) giving decorative spatial context to the corpus; `probes`
  // are full tracks discovered by clicking empty map space (resolved via
  // /map/nearest — the true nearest track, not just one already loaded).
  const [backdrop] = React.useState(makeGalaxy);
  const [probes, setProbes] = React.useState([]);

  const [playlist, setPlaylist] = React.useState(boot?.playlist || []);
  const [candidates, setCandidates] = React.useState(null); // { aId, bId, tracks }

  // ---- drift radio ----
  // Autopilot playback: when ON, end-of-track hops to a nearest sonic neighbor
  // of the just-finished track (instead of walking the nav list), skipping
  // anything already played this session. `drift` (0..1) widens the pick window
  // down the similarity ranking: 0 = always the closest unplayed neighbor,
  // 1 = anywhere in the fetched candidates. Visited hops accumulate in `wake`,
  // which the maps draw as a fading trail. Radio starts OFF every session; only
  // the drift setting persists.
  const [radioOn, setRadioOn] = React.useState(false);
  const [drift, setDrift] = React.useState(
    typeof boot?.drift === 'number' ? Math.max(0, Math.min(1, boot.drift)) : 0.3);
  const [wake, setWake] = React.useState([]);
  // Prefetched, played-filtered, similarity-ranked neighbors of the playing
  // track: { seedId, tracks }. Drives both the live drift preview on the map and
  // the actual next hop (so the pick comes from exactly the pool the user saw).
  // Session-only.
  const [radioCandidates, setRadioCandidates] = React.useState(null);
  // Every track played this session (any source), so the radio never repeats.
  const playedIdsRef = React.useRef(new Set());
  // Guards against overlapping hops (double `ended` fires, skip mashing).
  const radioBusyRef = React.useRef(false);
  // The drift preview (halo + candidate dots) is only shown *while you are
  // adjusting drift* — `bumpDriftPreview` flips this on and lingers ~1.1s after
  // the last change so you can see where the window settled, then hides it.
  const [driftPreviewing, setDriftPreviewing] = React.useState(false);
  const driftPreviewTimerRef = React.useRef(null);
  const bumpDriftPreview = React.useCallback(() => {
    setDriftPreviewing(true);
    if (driftPreviewTimerRef.current) clearTimeout(driftPreviewTimerRef.current);
    driftPreviewTimerRef.current = setTimeout(() => setDriftPreviewing(false), 1100);
  }, []);
  const [labelsByTrackId, setLabelsByTrackId] = React.useState({});
  // When set, only this layer's tracks are shown (click a pill to filter to its
  // members). null = show every layer that isn't explicitly hidden.
  const [soloLayerId, setSoloLayerId] = React.useState(null);
  // Zoom/pan/rotation of the map: screen = translate(x,y) ∘ scale(k) ∘ rotate(r).
  // Rotation (radians) is only driven by the mobile two-finger gesture; the
  // desktop view ignores it.
  const [zoom, setZoom] = React.useState({ k: 1, x: 0, y: 0, r: 0 });
  const audioRef = React.useRef(null);

  React.useEffect(() => { Labels.init(); }, []);
  React.useEffect(() => { Cache.getSuggestions().then(setSuggestions).catch(() => {}); }, []);

  // Probe the whole corpus at a normalized (x,y): resolve the globally-nearest
  // track via /map/nearest, remember it (so it gets a dot + is selectable), and
  // select it. Used by both views' empty-space click handlers.
  const probeAt = React.useCallback(async (nx, ny) => {
    const x = Math.max(0, Math.min(1, nx));
    const y = Math.max(0, Math.min(1, ny));
    try {
      const t = await API.mapNearest(x, y, 'fma');
      if (t && t.id) {
        setProbes((ps) => (ps.some((p) => p.id === t.id) ? ps : [...ps, t]));
        setSelectedId(t.id);
        return t;
      }
    } catch (e) {
      console.error('probe failed', e);
    }
    return null;
  }, []);
  const clearProbes = React.useCallback(() => setProbes([]), []);

  // Extract real waveform peaks for the playing track (fetch + decode + bucket),
  // cached per track id. Falls back to the pseudo-envelope on any failure
  // (unsupported browser, CORS, decode error).
  const peaksCacheRef = React.useRef(new Map());
  const audioCtxRef = React.useRef(null);
  React.useEffect(() => {
    if (!playingId) { setPeaks(null); return undefined; }
    const cached = peaksCacheRef.current.get(playingId);
    if (cached) { setPeaks(cached); return undefined; }
    let alive = true;
    setPeaks(null);
    (async () => {
      try {
        const AC = window.AudioContext || window.webkitAudioContext;
        if (!AC) return;
        if (!audioCtxRef.current) audioCtxRef.current = new AC();
        const res = await fetch(API.getStreamUrl(playingId));
        if (!res.ok || !alive) return;
        const raw = await res.arrayBuffer();
        const audioBuf = await audioCtxRef.current.decodeAudioData(raw);
        if (!alive) return;
        const computed = computePeaks(audioBuf);
        peaksCacheRef.current.set(playingId, computed);
        if (alive) setPeaks(computed);
      } catch { /* keep the pseudo-envelope */ }
    })();
    return () => { alive = false; };
  }, [playingId]);

  // ---- persistence: save the durable slice of state on change ----
  React.useEffect(() => {
    try {
      const slim = layers.map(({ loading, ...l }) => ({ ...l, fetched: true }));
      localStorage.setItem(STORE_KEY, JSON.stringify({
        view, layers: slim, playlist, colorIdx: colorIdxRef.current, drift,
      }));
    } catch { /* quota / serialization — ignore */ }
  }, [view, layers, playlist, drift]);

  // Run the actual API call for one layer.
  const runLayerSearch = React.useCallback(async (layer) => {
    if (layer.kind === 'vibe') {
      const r = await API.semanticSearch(layer.query, 'fma', 24, true);
      const results = r.results || r;
      const enhancedQuery = r.enhanced_query || null;
      const searchId = Labels.recordSearch('/semantic-search', 'text',
        { text: layer.query, enhanced_text: enhancedQuery }, { source: 'fma', limit: 24, enhance: true }, results);
      return { results, enhancedQuery, searchId };
    }
    if (layer.kind === 'similar') {
      const results = await API.findSimilar(layer.seedTrackId);
      const searchId = Labels.recordSearch(`/tracks/${layer.seedTrackId}/similar`, 'seed',
        { seed_track_id: layer.seedTrackId }, { source: 'fma', polarity: 'similar' }, results);
      return { results, enhancedQuery: null, searchId };
    }
    const results = await API.findDissimilar(layer.seedTrackId);
    const searchId = Labels.recordSearch(`/tracks/${layer.seedTrackId}/dissimilar`, 'seed',
      { seed_track_id: layer.seedTrackId }, { source: 'fma', polarity: 'dissimilar' }, results);
    return { results, enhancedQuery: null, searchId };
  }, []);

  // Fetch any layer that hasn't been fetched yet. (We intentionally DO NOT
  // auto-select a result — searching never picks a song for you.)
  React.useEffect(() => {
    const pending = layers.filter((l) => !l.fetched && !l.loading);
    if (!pending.length) return;
    pending.forEach((l) => {
      setLayers((ls) => ls.map((x) => (x.id === l.id ? { ...x, loading: true } : x)));
      runLayerSearch(l)
        .then(({ results, enhancedQuery, searchId }) => {
          setLayers((ls) => ls.map((x) => (x.id === l.id
            ? { ...x, loading: false, fetched: true, results, enhancedQuery, searchId } : x)));
        })
        .catch((e) => {
          console.error('layer search failed', e);
          setLayers((ls) => ls.map((x) => (x.id === l.id
            ? { ...x, loading: false, fetched: true, results: [] } : x)));
        });
    });
  }, [layers, runLayerSearch]);

  // ---- layer ops ----
  // `solo` (default true) auto-selects the new pill so the map filters to it;
  // the fresh-session seeding passes false so it can plant two pills at once.
  // The id is fixed up front so we can solo the right pill, while the functional
  // updater stays authoritative for dedup + color (it sees fresh state).
  const addVibeLayer = (text, { solo = true } = {}) => {
    const t = (text || '').trim();
    if (!t) return;
    const existing = layers.find((l) => l.kind === 'vibe' && l.query.toLowerCase() === t.toLowerCase());
    const id = existing ? existing.id : `L_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`;
    setLayers((ls) => (ls.some((l) => l.kind === 'vibe' && l.query.toLowerCase() === t.toLowerCase())
      ? ls : [...ls, makeLayer('vibe', { id, label: t, query: t }, ls)]));
    if (solo) setSoloLayerId(id);
  };
  // Creating a similar/dissimilar search auto-selects (solos) its pill too.
  const addSeedLayer = (kind, track) => {
    if (!track) return;
    const existing = layers.find((l) => l.kind === kind && l.seedTrackId === track.id);
    const id = existing ? existing.id : `L_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`;
    setLayers((ls) => (ls.some((l) => l.kind === kind && l.seedTrackId === track.id)
      ? ls : [...ls, makeLayer(kind, { id, label: track.title, seedTrackId: track.id, seedTrack: track }, ls)]));
    setSoloLayerId(id);
  };

  // Fresh session (nothing restored from localStorage): seed two random vibe
  // pills so the map isn't empty on first load.
  const seededRef = React.useRef(false);
  React.useEffect(() => {
    if (seededRef.current) return;
    seededRef.current = true;
    if ((boot?.layers || []).length || layers.length) return;
    const pool = [...(suggestions.length ? suggestions : FALLBACK_SUGGESTIONS)];
    for (let n = 0; n < 2 && pool.length; n++) {
      addVibeLayer(pool.splice(Math.floor(Math.random() * pool.length), 1)[0], { solo: false });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Re-add a layer that produced a (still-present) playlist track. No-ops if a
  // matching layer is already shown.
  const restoreLayer = (origin) => {
    if (!origin) return;
    setLayers((ls) => {
      const dup = ls.some((l) => l.kind === origin.kind
        && (origin.kind === 'vibe'
          ? l.query.toLowerCase() === (origin.query || '').toLowerCase()
          : l.seedTrackId === origin.seedTrackId));
      if (dup) return ls;
      return [...ls, makeLayer(origin.kind, {
        label: origin.label, query: origin.query || '',
        seedTrackId: origin.seedTrackId || null, seedTrack: origin.seedTrack || null,
      }, ls)];
    });
  };
  const removeLayer = (id) => {
    setLayers((ls) => ls.filter((l) => l.id !== id));
    setSoloLayerId((s) => (s === id ? null : s));
  };
  const clearLayers = () => { setLayers([]); setCandidates(null); setSelectedId(null); setSoloLayerId(null); };
  const toggleLayerVisible = (id) =>
    setLayers((ls) => ls.map((l) => (l.id === id ? { ...l, visible: !l.visible } : l)));
  // Click a pill to filter to just its members; click it again to show all.
  const toggleSolo = (id) => setSoloLayerId((s) => (s === id ? null : id));
  const showAllLayers = () => { setSoloLayerId(null); setLayers((ls) => ls.map((l) => ({ ...l, visible: true }))); };
  // Hide every search layer at once — the map falls back to just the playlist
  // dots. Clears any solo (which would otherwise keep one layer shown).
  const hideAllLayers = () => { setSoloLayerId(null); setLayers((ls) => ls.map((l) => ({ ...l, visible: false }))); };

  // ---- derived ----
  // A layer is shown if it's soloed, or (when nothing is soloed) not hidden.
  const isLayerShown = React.useCallback(
    (l) => (soloLayerId ? l.id === soloLayerId : l.visible), [soloLayerId]);
  const visibleLayers = React.useMemo(() => layers.filter(isLayerShown), [layers, isLayerShown]);
  const anyLoading = layers.some((l) => l.loading);
  const allVisible = !soloLayerId && layers.length > 0 && layers.every((l) => l.visible);

  // Newest-first views for display only (pills, chips, legends). The underlying
  // `layers` array stays append-ordered — color assignment, dedupe, originFor,
  // and Backspace-removes-last all depend on that order — so never reverse it
  // in place.
  const displayLayers = React.useMemo(() => [...layers].reverse(), [layers]);
  const displayVisibleLayers = React.useMemo(() => [...visibleLayers].reverse(), [visibleLayers]);

  // De-duped union of visible layers' results. Overlap takes the first (oldest)
  // visible layer's color; sources lists every visible layer the track is in.
  const visibleTracks = React.useMemo(() => {
    const seen = new Map();
    const order = [];
    for (const l of layers) {
      if (!isLayerShown(l)) continue;
      for (const t of l.results) {
        if (!t || !t.id) continue;
        const ex = seen.get(t.id);
        if (ex) { ex.sources.push(l); continue; }
        const entry = { track: t, color: l.color, sources: [l] };
        seen.set(t.id, entry);
        order.push(entry);
      }
    }
    return order;
  }, [layers, isLayerShown]);

  const entryByTrackId = React.useMemo(() => {
    const m = new Map();
    visibleTracks.forEach((e) => m.set(e.track.id, e));
    return m;
  }, [visibleTracks]);

  const playlistById = React.useMemo(() => {
    const m = new Map();
    playlist.forEach((s) => { if (s.track) m.set(s.track.id, s); });
    return m;
  }, [playlist]);

  // Index of every track we have full metadata for. The currently-playing track
  // is kept in here even after it's removed from every layer/playlist, so it
  // stays resolvable (selectable / peekable) while it's still playing.
  const tracksById = React.useMemo(() => {
    const m = new Map();
    layers.forEach((l) => { l.results.forEach((t) => m.set(t.id, t)); if (l.seedTrack) m.set(l.seedTrack.id, l.seedTrack); });
    if (candidates) candidates.tracks.forEach((t) => m.set(t.id, t));
    playlist.forEach((s) => { if (s.track) m.set(s.track.id, s.track); });
    probes.forEach((t) => m.set(t.id, t));
    wake.forEach((t) => m.set(t.id, t));
    if (radioCandidates) radioCandidates.tracks.forEach((t) => m.set(t.id, t));
    if (playingTrack && !m.has(playingTrack.id)) m.set(playingTrack.id, playingTrack);
    return m;
  }, [layers, candidates, playlist, probes, wake, radioCandidates, playingTrack]);

  const playing = playingId ? (tracksById.get(playingId) || (playingTrack?.id === playingId ? playingTrack : null)) : null;
  const hover = hoverId ? tracksById.get(hoverId) : null;
  // Fall back to the retained playing track so the now-playing track stays
  // selectable/peekable even after it's removed from every layer/playlist.
  const selected = selectedId
    ? (tracksById.get(selectedId) || (playingTrack?.id === selectedId ? playingTrack : null))
    : null;

  const flatResults = React.useMemo(() => visibleTracks.map((e) => e.track), [visibleTracks]);

  // ---- vibe tagger suggestions ----
  const activeVibeTexts = React.useMemo(
    () => layers.filter((l) => l.kind === 'vibe').map((l) => l.query.toLowerCase()),
    [layers]);
  const vibeSuggestions = React.useMemo(() => {
    const q = vibeQuery.toLowerCase().trim();
    return suggestions
      .filter((v) => !activeVibeTexts.includes(v.toLowerCase()))
      .filter((v) => !q || v.toLowerCase().includes(q))
      .slice(0, 14);
  }, [vibeQuery, activeVibeTexts, suggestions]);

  // ---- playlist ----
  const recomputeDist = (arr) =>
    arr.map((s, i) => ({ ...s, dist: i === 0 ? null : distBetween(arr[i - 1].track, s.track) }));

  // Snapshot of the layer a track came from, so the playlist can restore it.
  const originFor = (track) => {
    const src = entryByTrackId.get(track.id)?.sources?.[0];
    if (!src) return null;
    return {
      kind: src.kind, label: src.label, color: src.color,
      query: src.query || '', seedTrackId: src.seedTrackId || null, seedTrack: src.seedTrack || null,
    };
  };

  const addToPlaylist = (track) => {
    if (!track) return;
    const origin = originFor(track);
    const color = entryByTrackId.get(track.id)?.color || FALLBACK_COLOR;
    setPlaylist((t) => {
      if (t.some((s) => s.track?.id === track.id)) return t;
      const slot = { id: `s_${track.id}_${Date.now()}`, track, dist: null, origin, color };
      return recomputeDist([...t, slot]);
    });
  };
  // Insert a candidate between its edge's two endpoints, then clear the
  // remaining candidates — once you've picked one, the rest go away (re-click
  // the edge to interpolate again).
  const insertCandidate = (track) => {
    if (!candidates) { addToPlaylist(track); return; }
    const origin = { kind: 'interp', label: 'interpolation', color: CANDIDATE_COLOR };
    setPlaylist((t) => {
      if (t.some((s) => s.track?.id === track.id)) return t;
      const ai = t.findIndex((s) => s.track?.id === candidates.aId);
      const bi = t.findIndex((s) => s.track?.id === candidates.bId);
      const slot = { id: `s_${track.id}_${Date.now()}`, track, dist: null, origin, color: CANDIDATE_COLOR };
      if (ai < 0 || bi < 0) return recomputeDist([...t, slot]);
      const at = Math.max(ai, bi);
      return recomputeDist([...t.slice(0, at), slot, ...t.slice(at)]);
    });
    setCandidates(null);
  };
  const removeFromPlaylist = (id) => setPlaylist((t) => recomputeDist(t.filter((s) => s.id !== id)));
  const movePlaylist = (id, dir) => setPlaylist((t) => {
    const i = t.findIndex((s) => s.id === id);
    const j = i + dir;
    if (i < 0 || j < 0 || j >= t.length) return t;
    const arr = [...t];
    [arr[i], arr[j]] = [arr[j], arr[i]];
    return recomputeDist(arr);
  });
  const clearPlaylist = () => { setPlaylist([]); setCandidates(null); };

  // Drag-to-reorder. Native HTML5 DnD; setData is required for the drag to
  // actually start in Firefox (and to keep Chrome from treating it as a click).
  // We track an insertion *boundary* (0..length) so a track can be dropped in
  // the gaps between cards, not just onto another card. (Desktop view only.)
  const dragId = React.useRef(null);
  const [dropIdx, setDropIdx] = React.useState(null);
  const onDragStartSlot = (e, id) => {
    dragId.current = id;
    e.dataTransfer.effectAllowed = 'move';
    e.dataTransfer.setData('text/plain', id);
  };
  // Over a card: the boundary is above or below it depending on the cursor half.
  const onDragOverCard = (e, index) => {
    if (!dragId.current) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
    const rect = e.currentTarget.getBoundingClientRect();
    const boundary = index + ((e.clientY - rect.top) > rect.height / 2 ? 1 : 0);
    if (dropIdx !== boundary) setDropIdx(boundary);
  };
  const onDragEndSlot = () => { dragId.current = null; setDropIdx(null); };
  const onDropSlot = (e) => {
    e.preventDefault();
    const from = dragId.current;
    const boundary = dropIdx;
    dragId.current = null;
    setDropIdx(null);
    if (!from || boundary == null) return;
    setPlaylist((arr0) => {
      const fi = arr0.findIndex((s) => s.id === from);
      if (fi < 0) return arr0;
      const arr = [...arr0];
      const [moved] = arr.splice(fi, 1);
      // Removing an element before the boundary shifts later indices left by one.
      let idx = fi < boundary ? boundary - 1 : boundary;
      idx = Math.max(0, Math.min(arr.length, idx));
      arr.splice(idx, 0, moved);
      return recomputeDist(arr);
    });
  };

  // Generate candidate tracks "between" two playlist tracks (the clicked line).
  const interpolateEdge = async (a, b) => {
    if (!a || !b) return;
    try {
      const list = await API.interpolate(a.id, b.id, 'slerp', 8, 'fma');
      const ids = new Set(playlist.filter((s) => s.track).map((s) => s.track.id));
      const tracks = (Array.isArray(list) ? list : (list.results || []))
        .filter((t) => t.id !== a.id && t.id !== b.id && !ids.has(t.id));
      Labels.recordSearch('/interpolate', 'pair',
        { pair_track_ids: [a.id, b.id] }, { source: 'fma', method: 'slerp' }, tracks);
      setCandidates({ aId: a.id, bId: b.id, tracks });
    } catch (e) {
      console.error('interpolate failed', e);
    }
  };
  const clearCandidates = () => setCandidates(null);

  // ---- player ----
  const playTrack = (track) => {
    if (!track) return;
    playedIdsRef.current.add(track.id);
    setPlayingId(track.id);
    setPlayingTrack(track);
    setPlayingOrigin(originFor(track) || playlistById.get(track.id)?.origin || null);
    setSelectedId(track.id);
    const audio = audioRef.current;
    if (audio) {
      audio.src = API.getStreamUrl(track.id);
      // isPlaying is driven by the element's onPlay/onPause/onEnded handlers
      // (single source of truth); just swallow the rejection a new src causes.
      audio.play().catch(() => {});
    }
    Labels.recordLabel(track, 'play');
  };
  const togglePlay = () => {
    const audio = audioRef.current;
    if (!audio || !playing) return;
    // isPlaying is driven by the element's onPlay/onPause handlers.
    if (isPlaying) audio.pause();
    else audio.play().catch(() => {});
  };
  // Cue a track as "now playing" (shows in the player + radial rings on the map)
  // and select it, but do NOT start audio — pressing Space will begin playback.
  const cueTrack = (track) => {
    if (!track) return;
    setPlayingId(track.id);
    setPlayingTrack(track);
    setPlayingOrigin(originFor(track) || playlistById.get(track.id)?.origin || null);
    setSelectedId(track.id);
    setIsPlaying(false);
    const audio = audioRef.current;
    if (audio) audio.src = API.getStreamUrl(track.id);
  };
  const seekTo = (frac) => {
    const audio = audioRef.current;
    if (!audio || !audio.duration) return;
    audio.currentTime = frac * audio.duration;
    setProgress(frac);
  };

  // ---- drift radio engine ----
  // The radio prefetches the playing track's neighbors ONCE per hop
  // (`radioCandidates`), then both the live map preview and the actual next pick
  // read from that same played-filtered, similarity-ranked list — so moving the
  // drift slider never re-fetches, and the hop lands in exactly the pool the user
  // was previewing. `drift` (0..1) sets how many ranks the pick window spans.
  const RADIO_FETCH = 30;
  const WAKE_MAX = 30;

  // How many of the ranked candidates the current drift admits into the pick
  // window: drift 0 → just the nearest (a guaranteed next), drift 1 → all of them.
  const radioWindow = React.useMemo(() => {
    const n = radioCandidates?.tracks.length || 0;
    if (n <= 1) return n;
    return 1 + Math.round(drift * (n - 1));
  }, [radioCandidates, drift]);

  // Fetch + played-filter the neighbors of `seedId`, log the 'radio' search once,
  // and store as radioCandidates. Widens the fetch once if the played-filter
  // empties it. Returns the unplayed list (also stored). No-op reuse if we
  // already hold this seed's candidates.
  const fetchRadioCandidates = React.useCallback(async (seedId, existing) => {
    if (existing && existing.seedId === seedId) return existing.tracks;
    let unplayed = [];
    for (const limit of [RADIO_FETCH, RADIO_FETCH * 2]) {
      const results = await API.findSimilar(seedId, 'fma', limit);
      Labels.recordSearch(`/tracks/${seedId}/similar`, 'radio',
        { seed_track_id: seedId }, { source: 'fma', polarity: 'similar', limit }, results);
      unplayed = (results || []).filter((t) => t && t.id
        && t.id !== seedId && !playedIdsRef.current.has(t.id));
      if (unplayed.length) break;
    }
    setRadioCandidates({ seedId, tracks: unplayed });
    return unplayed;
  }, []);

  // One hop: reuse the prefetched candidates for `from` (fetch only if missing),
  // pick from the current drift window at random, append to the wake, and play.
  const radioNext = async (fromTrack) => {
    const from = fromTrack || playing || playingTrack;
    if (!from || radioBusyRef.current) return;
    radioBusyRef.current = true;
    try {
      const cur = radioCandidates;
      const unplayed = (cur && cur.seedId === from.id)
        ? cur.tracks
        : await fetchRadioCandidates(from.id, cur);
      if (!unplayed.length) { setRadioOn(false); return; } // corpus pocket exhausted
      const windowSize = unplayed.length <= 1
        ? unplayed.length : 1 + Math.round(drift * (unplayed.length - 1));
      const pick = unplayed[Math.floor(Math.random() * windowSize)];
      setWake((w) => {
        const base = w.length ? w : [from]; // first hop starts the trail at the seed
        return [...base.filter((t) => t.id !== pick.id), pick].slice(-WAKE_MAX);
      });
      playTrack(pick); // triggers the prefetch effect for the new seed
    } catch (e) {
      console.error('radio hop failed', e);
      setRadioOn(false);
    } finally {
      radioBusyRef.current = false;
    }
  };

  // Jump straight to a previewed candidate (clicking a lit dot on the map): treat
  // it like a manual skip of the current track, then play the chosen one.
  const hopToCandidate = (track) => {
    if (!track) return;
    const cur = playing || playingTrack;
    if (cur && cur.id !== track.id) Labels.recordLabel(cur, 'radio_skip');
    setWake((w) => {
      const base = w.length ? w : (cur ? [cur] : []);
      return [...base.filter((t) => t.id !== track.id), track].slice(-WAKE_MAX);
    });
    playTrack(track);
  };

  const toggleRadio = () => {
    const next = !radioOn;
    setRadioOn(next);
    if (next) {
      const cur = playing || playingTrack;
      if (cur) {
        playedIdsRef.current.add(cur.id);
        setWake((w) => (w.length ? w : [cur]));
        // Turning the radio on while paused/cued resumes playback.
        const audio = audioRef.current;
        if (!isPlaying && audio && audio.src) audio.play().catch(() => {});
      } else {
        // "Press play and lean back": nothing cued, so seed from a random track.
        API.getTracks(1, 'fma')
          .then((tracks) => { const t = Array.isArray(tracks) ? tracks[0] : null; if (t) playTrack(t); })
          .catch((e) => { console.error('radio random seed failed', e); setRadioOn(false); });
      }
    } else {
      setRadioCandidates(null); // leaving the mode clears the preview
    }
  };

  // Prefetch the playing track's candidates whenever radio is on and the track
  // changes — this powers the live preview and pre-warms the next hop. Skips the
  // fetch if we already hold this seed's candidates (e.g. a click-to-hop that set
  // them). Cancels stale results if the track changes mid-flight.
  React.useEffect(() => {
    if (!radioOn || !playingId) { return undefined; }
    if (radioCandidates && radioCandidates.seedId === playingId) return undefined;
    let alive = true;
    fetchRadioCandidates(playingId, radioCandidates)
      .catch((e) => { if (alive) console.error('radio prefetch failed', e); });
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [radioOn, playingId, fetchRadioCandidates]);
  // Forward/back walks the playlist when one exists, EXCEPT in list view, where
  // it walks the visible results list the user is actually looking at.
  const playlistTracks = React.useMemo(() => playlist.filter((s) => s.track).map((s) => s.track), [playlist]);
  const usePlaylistNav = view !== 'list' && playlistTracks.length > 0;
  const navList = usePlaylistNav ? playlistTracks : flatResults;
  const navSource = radioOn ? 'drift radio' : (usePlaylistNav ? 'your playlist' : 'search results');
  const step = (dir) => {
    // Radio owns the transport while it's on: forward = skip (drift to a new
    // neighbor, logging the skip), back = walk the wake trail (replay without
    // re-appending).
    if (radioOn) {
      const cur = playing || playingTrack;
      if (dir > 0) {
        if (cur) Labels.recordLabel(cur, 'radio_skip');
        radioNext(cur);
      } else {
        const idx = wake.findIndex((t) => t.id === playingId);
        const prev = idx > 0 ? wake[idx - 1]
          : (idx === -1 && wake.length ? wake[wake.length - 1] : null);
        if (prev) playTrack(prev);
      }
      return;
    }
    if (!navList.length) return;
    const idx = navList.findIndex((t) => t.id === playingId);
    const next = navList[(idx + dir + navList.length) % navList.length];
    if (next) playTrack(next);
  };
  // Natural end-of-track: advance to the next track but STOP at the end of the
  // list — no wrap-around, and no re-playing a single-track list forever.
  // (Manual ←/→ via step() still wraps.)
  const playNextOnEnd = () => {
    if (navList.length < 2) return;
    const idx = navList.findIndex((t) => t.id === playingId);
    if (idx < 0 || idx >= navList.length - 1) return; // unknown or last track
    playTrack(navList[idx + 1]);
  };

  // Keyboard transport: Space/K play-pause, ←/→ prev/next track, ↑/↓ seek ±5s.
  // Latest-ref pattern so the listener mounts once but always calls fresh fns.
  const transportRef = React.useRef(null);
  transportRef.current = { togglePlay, step, audio: audioRef };
  React.useEffect(() => {
    const onKey = (e) => {
      const el = e.target;
      if (el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.isContentEditable)) return;
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      const { togglePlay: tp, step: st, audio } = transportRef.current;
      const seek = (d) => {
        const a = audio.current;
        if (!a || !a.duration) return false;
        a.currentTime = Math.max(0, Math.min(a.duration, a.currentTime + d));
        return true;
      };
      switch (e.key) {
        case ' ': case 'k': case 'K': e.preventDefault(); tp(); break;
        case 'ArrowRight': e.preventDefault(); st(1); break;
        case 'ArrowLeft': e.preventDefault(); st(-1); break;
        case 'ArrowUp': if (seek(5)) e.preventDefault(); break;
        case 'ArrowDown': if (seek(-5)) e.preventDefault(); break;
        default: break;
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  // Fresh session (nothing restored): once the two seeded searches finish, pick
  // the two searched tracks that sit furthest apart on the map, add them to the
  // playlist, and cue the first (shows in the player with its radial rings —
  // without auto-playing). Runs at most once.
  const autoCueRef = React.useRef(false);
  React.useEffect(() => {
    if (autoCueRef.current) return;
    if ((boot?.layers || []).length || (boot?.playlist || []).length) { autoCueRef.current = true; return; }
    if (playlist.length) { autoCueRef.current = true; return; } // user already acted
    if (anyLoading) return; // wait for the seeded searches to resolve
    const tracks = flatResults;
    if (tracks.length < 2) return;
    let a = null, b = null, bestD = -1;
    for (let i = 0; i < tracks.length; i++) {
      for (let j = i + 1; j < tracks.length; j++) {
        const d = distBetween(tracks[i], tracks[j]);
        if (d > bestD) { bestD = d; a = tracks[i]; b = tracks[j]; }
      }
    }
    if (!a || !b) return;
    autoCueRef.current = true;
    addToPlaylist(a);
    addToPlaylist(b);
    cueTrack(a);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [anyLoading, flatResults, playlist.length]);

  const labelTrack = (track, signal) => {
    Labels.recordLabel(track, signal);
    setLabelsByTrackId((m) => ({ ...m, [track.id]: signal }));
  };

  const playingTotal = duration || 0;
  const isCandidate = (id) => !!candidates && candidates.tracks.some((t) => t.id === id);

  // The search a track is being validated against (for the "Match" feedback) —
  // its first visible source layer, else its playlist origin, else interpolation.
  // Returns { label, color } or null.
  const sourceTagFor = React.useCallback((track) => {
    if (!track) return null;
    if (candidates && candidates.tracks.some((t) => t.id === track.id)) {
      return { label: 'interpolation', color: CANDIDATE_COLOR };
    }
    const src = entryByTrackId.get(track.id)?.sources?.[0] || playlistById.get(track.id)?.origin;
    if (src) return { label: layerTag(src), color: src.color };
    // Removed-layer now-playing track keeps its captured origin tag.
    if (track.id === playingId && playingOrigin) return { label: layerTag(playingOrigin), color: playingOrigin.color };
    return null;
  }, [candidates, entryByTrackId, playlistById, playingId, playingOrigin]);

  // The track shown in the detail card above the map: hover wins for preview,
  // otherwise the pinned selection.
  const detail = hover || selected;
  const detailPinned = !hover && !!selected;

  // ---- shared zoom (reset is geometry-agnostic; zoomBy is per-view) ----
  const resetZoom = () => setZoom({ k: 1, x: 0, y: 0, r: 0 });

  // ---- audio element event handlers (the <audio> lives in the shell) ----
  const onAudioTimeUpdate = (e) => {
    const a = e.currentTarget;
    setProgress(a.duration ? a.currentTime / a.duration : 0);
  };
  const onAudioLoadedMetadata = (e) => setDuration(e.currentTarget.duration || 0);
  const onAudioEnded = () => {
    setIsPlaying(false);
    if (radioOn) radioNext(playing || playingTrack);
    else playNextOnEnd();
  };
  const onAudioPause = () => setIsPlaying(false);
  const onAudioPlay = () => setIsPlaying(true);

  return {
    // state
    view, setView, vibeQuery, setVibeQuery, suggestions, aboutOpen, setAboutOpen,
    layers, setLayers, playingId, setPlayingId, hoverId, setHoverId,
    selectedId, setSelectedId, isPlaying, progress, duration, peaks,
    playlist, setPlaylist, candidates, setCandidates, labelsByTrackId,
    soloLayerId, zoom, setZoom,
    // whole-corpus probing
    backdrop, probes, probeAt, clearProbes,
    // refs / audio
    audioRef,
    onAudioTimeUpdate, onAudioLoadedMetadata, onAudioEnded, onAudioPause, onAudioPlay,
    // layer ops
    addVibeLayer, addSeedLayer, restoreLayer, removeLayer, clearLayers,
    toggleLayerVisible, toggleSolo, showAllLayers, hideAllLayers,
    // derived
    isLayerShown, visibleLayers, displayLayers, displayVisibleLayers,
    anyLoading, allVisible, visibleTracks,
    entryByTrackId, playlistById, tracksById, playing, playingOrigin, hover, selected,
    flatResults, vibeSuggestions, playlistTracks, navList, navSource,
    detail, detailPinned, isCandidate, playingTotal, sourceTagFor,
    // playlist ops
    addToPlaylist, insertCandidate, removeFromPlaylist, movePlaylist, clearPlaylist,
    dragId, dropIdx, onDragStartSlot, onDragOverCard, onDragEndSlot, onDropSlot,
    interpolateEdge, clearCandidates,
    // player
    playTrack, togglePlay, cueTrack, seekTo, step, playNextOnEnd, labelTrack,
    // drift radio
    radioOn, toggleRadio, drift, setDrift, wake,
    radioCandidates, radioWindow, hopToCandidate,
    driftPreviewing, bumpDriftPreview,
    // zoom
    resetZoom,
  };
}

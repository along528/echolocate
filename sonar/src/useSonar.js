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
import { LAYER_COLORS, CANDIDATE_COLOR, FALLBACK_COLOR, distBetween, layerTag } from './sonar-utils.jsx';

const STORE_KEY = 'sonar-state-v1';

// Responsive breakpoint helper — true on phone-width viewports. Shared by the
// Sonar shell to pick the mobile vs desktop view.
export function useIsMobile(query = '(max-width: 640px)') {
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
  const [hoverId, setHoverId] = React.useState(null);
  const [selectedId, setSelectedId] = React.useState(null);
  const [isPlaying, setIsPlaying] = React.useState(false);
  const [progress, setProgress] = React.useState(0);
  const [duration, setDuration] = React.useState(0);

  const [playlist, setPlaylist] = React.useState(boot?.playlist || []);
  const [candidates, setCandidates] = React.useState(null); // { aId, bId, tracks }
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

  // ---- persistence: save the durable slice of state on change ----
  React.useEffect(() => {
    try {
      const slim = layers.map(({ loading, ...l }) => ({ ...l, fetched: true }));
      localStorage.setItem(STORE_KEY, JSON.stringify({
        view, layers: slim, playlist, colorIdx: colorIdxRef.current,
      }));
    } catch { /* quota / serialization — ignore */ }
  }, [view, layers, playlist]);

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
  const addVibeLayer = (text) => {
    const t = (text || '').trim();
    if (!t) return;
    setLayers((ls) => (ls.some((l) => l.kind === 'vibe' && l.query.toLowerCase() === t.toLowerCase())
      ? ls : [...ls, makeLayer('vibe', { label: t, query: t }, ls)]));
  };
  const addSeedLayer = (kind, track) => {
    if (!track) return;
    setLayers((ls) => (ls.some((l) => l.kind === kind && l.seedTrackId === track.id)
      ? ls : [...ls, makeLayer(kind, { label: track.title, seedTrackId: track.id, seedTrack: track }, ls)]));
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
      addVibeLayer(pool.splice(Math.floor(Math.random() * pool.length), 1)[0]);
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

  // Index of every track we have full metadata for.
  const tracksById = React.useMemo(() => {
    const m = new Map();
    layers.forEach((l) => { l.results.forEach((t) => m.set(t.id, t)); if (l.seedTrack) m.set(l.seedTrack.id, l.seedTrack); });
    if (candidates) candidates.tracks.forEach((t) => m.set(t.id, t));
    playlist.forEach((s) => { if (s.track) m.set(s.track.id, s.track); });
    return m;
  }, [layers, candidates, playlist]);

  const playing = playingId ? tracksById.get(playingId) : null;
  const hover = hoverId ? tracksById.get(hoverId) : null;
  const selected = selectedId ? tracksById.get(selectedId) : null;

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
    setPlayingId(track.id);
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
  // Forward/back walks the playlist when one exists, otherwise the visible results.
  const playlistTracks = React.useMemo(() => playlist.filter((s) => s.track).map((s) => s.track), [playlist]);
  const navList = playlistTracks.length ? playlistTracks : flatResults;
  const navSource = playlistTracks.length ? 'your playlist' : 'search results';
  const step = (dir) => {
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
    return src ? { label: layerTag(src), color: src.color } : null;
  }, [candidates, entryByTrackId, playlistById]);

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
  const onAudioEnded = () => { setIsPlaying(false); playNextOnEnd(); };
  const onAudioPause = () => setIsPlaying(false);
  const onAudioPlay = () => setIsPlaying(true);

  return {
    // state
    view, setView, vibeQuery, setVibeQuery, suggestions, aboutOpen, setAboutOpen,
    layers, setLayers, playingId, setPlayingId, hoverId, setHoverId,
    selectedId, setSelectedId, isPlaying, progress, duration,
    playlist, setPlaylist, candidates, setCandidates, labelsByTrackId,
    soloLayerId, zoom, setZoom,
    // refs / audio
    audioRef,
    onAudioTimeUpdate, onAudioLoadedMetadata, onAudioEnded, onAudioPause, onAudioPlay,
    // layer ops
    addVibeLayer, addSeedLayer, restoreLayer, removeLayer, clearLayers,
    toggleLayerVisible, toggleSolo, showAllLayers, hideAllLayers,
    // derived
    isLayerShown, visibleLayers, displayLayers, displayVisibleLayers,
    anyLoading, allVisible, visibleTracks,
    entryByTrackId, playlistById, tracksById, playing, hover, selected,
    flatResults, vibeSuggestions, playlistTracks, navList, navSource,
    detail, detailPinned, isCandidate, playingTotal, sourceTagFor,
    // playlist ops
    addToPlaylist, insertCandidate, removeFromPlaylist, movePlaylist, clearPlaylist,
    dragId, dropIdx, onDragStartSlot, onDragOverCard, onDragEndSlot, onDropSlot,
    interpolateEdge, clearCandidates,
    // player
    playTrack, togglePlay, cueTrack, seekTo, step, playNextOnEnd, labelTrack,
    // zoom
    resetZoom,
  };
}

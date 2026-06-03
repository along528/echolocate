// Sonar — "sonar map + list", wired to the real EchoLocate vector service.
//
// Search model: each vibe / similar / dissimilar query is its own *layer* with
// its own color. Layers coexist on the map and in the list; every dot is colored
// by the search it came from. Each layer can be hidden, soloed, or removed.
// The 2D positions come from each track's x,y (a PCA projection of the MERT
// v_mid embedding — the same embedding used for interpolation).
import React from 'react';
import { API } from './api.js';
import { Labels } from './labels.js';
import { Cache, FALLBACK_SUGGESTIONS } from './cache.js';
import { Wordmark, Waveform, DistanceChip } from './svg-bits.jsx';
import {
  IconListPlus, IconSimilar, IconDissimilar, IconCheck, IconTilde, IconX, IconClose,
  IconExternal, IconEye, IconEyeOff, IconUp, IconDown, IconPlus,
  IconZoomIn, IconZoomOut, IconRecenter, IconInfo,
} from './icons.jsx';

// Per-search layer colors. A search's color is its identity everywhere (pill,
// dots, list rows). White is reserved for interpolation candidates.
const LAYER_COLORS = [
  '#22d3ee', '#f472b6', '#fbbf24', '#a78bfa', '#34d399',
  '#60a5fa', '#fb7185', '#c084fc', '#facc15', '#4ade80',
  '#2dd4bf', '#f59e0b', '#e879f9', '#38bdf8', '#a3e635',
  '#fca5a5', '#fdba74', '#5eead4', '#93c5fd', '#d8b4fe',
];
const CANDIDATE_COLOR = '#ffffff';
const FALLBACK_COLOR = '#94a3b8';

const VW = 760;
const VH = 540;
// Inner plot margin (was 60 — shrunk so the graph fills more of the canvas).
const PAD = 26;

const ASSET = import.meta.env.BASE_URL;
const STORE_KEY = 'sonar-state-v1';

function fmtTime(s) {
  if (s == null || isNaN(s)) return '0:00';
  const m = Math.floor(s / 60);
  const r = Math.floor(s % 60);
  return `${m}:${r.toString().padStart(2, '0')}`;
}

// Deterministic fallback coordinate from an id, so tracks lacking a projection
// still land somewhere stable rather than piling up at the origin.
function hashCoord(id) {
  let h = 2166136261;
  for (let i = 0; i < id.length; i++) {
    h ^= id.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  const a = ((h >>> 0) % 1000) / 1000;
  const b = ((Math.imul(h, 2654435761) >>> 0) % 1000) / 1000;
  return [a, b];
}

function coordsOf(t) {
  if (t && typeof t.x === 'number' && typeof t.y === 'number') return [t.x, t.y];
  return hashCoord(t?.id || '');
}

// SVG position. x: left -> right. y: high values at top.
function dotPos(t) {
  const [cx, cy] = coordsOf(t);
  return { x: PAD + cx * (VW - 2 * PAD), y: PAD + (1 - cy) * (VH - 2 * PAD) };
}

function distBetween(a, b) {
  if (!a || !b) return 0;
  const [ax, ay] = coordsOf(a);
  const [bx, by] = coordsOf(b);
  return Math.min(1, Math.sqrt((ax - bx) ** 2 + (ay - by) ** 2));
}

const distChipValue = (t) => (typeof t.similarity === 'number' ? 1 - t.similarity : 0);
const layerTag = (l) => (l.kind === 'similar' ? '≈ ' : l.kind === 'dissimilar' ? '≠ ' : '') + l.label;
const layerKindWord = (l) => (l.kind === 'similar' ? 'Similar to' : l.kind === 'dissimilar' ? 'Dissimilar to' : 'Vibe');
// Shorten a URL to "host/…/last-segment" for inline display; falls back to the raw string.
const prettyUrl = (url) => {
  try {
    const u = new URL(url);
    const seg = u.pathname.split('/').filter(Boolean).pop();
    return u.hostname.replace(/^www\./, '') + (seg ? `/${seg}` : '');
  } catch { return url; }
};

// 3-way training-signal feedback (relevant / borderline / wrong). Styled to
// match the legacy frontend's "Match" pill exactly. Fires Labels.recordLabel.
function FeedbackPills({ track, value, onLabel }) {
  const opts = [
    ['relevant', <IconCheck size={15} />, 'mp-yes', 'Relevant'],
    ['borderline', <IconTilde size={15} />, 'mp-mid', 'Borderline'],
    ['wrong', <IconX size={15} />, 'mp-no', 'Wrong'],
  ];
  return (
    <div className="match-pill label-group" role="group" aria-label="Rate match" onClick={(e) => e.stopPropagation()}>
      <span className="mp-label">Match</span>
      {opts.map(([sig, glyph, tone, title]) => (
        <button
          key={sig}
          className={'action-btn mp-btn ' + tone + (value === sig ? ' selected' : '')}
          title={title}
          onClick={(e) => { e.stopPropagation(); onLabel(track, sig); }}
        >{glyph}</button>
      ))}
    </div>
  );
}

// External source link — icon only, sits next to the track title. No "FMA" text.
function SourceLink({ track, className = '' }) {
  if (!track || !track.track_url) return null;
  return (
    <a className={'ld-srclink ' + className} href={track.track_url} target="_blank" rel="noopener noreferrer"
      onClick={(e) => e.stopPropagation()} title="Open source (Free Music Archive)">
      <IconExternal size={13} />
    </a>
  );
}

export default function Sonar({ initialView = 'map' }) {
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
  const makeLayer = React.useCallback((kind, extra) => ({
    id: `L_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`,
    kind,
    label: '',
    query: '',
    seedTrackId: null,
    seedTrack: null,
    color: LAYER_COLORS[colorIdxRef.current++ % LAYER_COLORS.length],
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
  const [zoom, setZoom] = React.useState({ k: 1, x: 0, y: 0 });
  // Pan drag bookkeeping (click-drag to pan when zoomed in).
  const panRef = React.useRef(null); // { sx, sy, ox, oy } during a drag
  const didPanRef = React.useRef(false); // set true once a drag actually moves
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
      ? ls : [...ls, makeLayer('vibe', { label: t, query: t })]));
  };
  const addSeedLayer = (kind, track) => {
    if (!track) return;
    setLayers((ls) => (ls.some((l) => l.kind === kind && l.seedTrackId === track.id)
      ? ls : [...ls, makeLayer(kind, { label: track.title, seedTrackId: track.id, seedTrack: track })]));
  };
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
      })];
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

  // ---- derived ----
  // A layer is shown if it's soloed, or (when nothing is soloed) not hidden.
  const isLayerShown = React.useCallback(
    (l) => (soloLayerId ? l.id === soloLayerId : l.visible), [soloLayerId]);
  const visibleLayers = React.useMemo(() => layers.filter(isLayerShown), [layers, isLayerShown]);
  const anyLoading = layers.some((l) => l.loading);
  const allVisible = !soloLayerId && layers.length > 0 && layers.every((l) => l.visible);

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
  // Insert a candidate between its edge's two endpoints (does not clear candidates).
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
  const dragId = React.useRef(null);
  const [dragOverId, setDragOverId] = React.useState(null);
  const onDragStartSlot = (e, id) => {
    dragId.current = id;
    e.dataTransfer.effectAllowed = 'move';
    e.dataTransfer.setData('text/plain', id);
  };
  const onDragOverSlot = (e, id) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
    if (dragId.current && dragId.current !== id && dragOverId !== id) setDragOverId(id);
  };
  const onDragEndSlot = () => { dragId.current = null; setDragOverId(null); };
  const onDropSlot = (e, targetId) => {
    e.preventDefault();
    const from = dragId.current;
    dragId.current = null;
    setDragOverId(null);
    if (!from || from === targetId) return;
    setPlaylist((t) => {
      const fi = t.findIndex((s) => s.id === from);
      const ti = t.findIndex((s) => s.id === targetId);
      if (fi < 0 || ti < 0) return t;
      const arr = [...t];
      const [moved] = arr.splice(fi, 1);
      arr.splice(ti, 0, moved);
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
      audio.play().then(() => setIsPlaying(true)).catch(() => setIsPlaying(false));
    }
    Labels.recordLabel(track, 'play');
  };
  const togglePlay = () => {
    const audio = audioRef.current;
    if (!audio || !playing) return;
    if (isPlaying) { audio.pause(); setIsPlaying(false); }
    else { audio.play().then(() => setIsPlaying(true)).catch(() => {}); }
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

  const labelTrack = (track, signal) => {
    Labels.recordLabel(track, signal);
    setLabelsByTrackId((m) => ({ ...m, [track.id]: signal }));
  };

  const playingTotal = duration || 0;
  const isCandidate = (id) => !!candidates && candidates.tracks.some((t) => t.id === id);

  // The track shown in the detail card above the map: hover wins for preview,
  // otherwise the pinned selection.
  const detail = hover || selected;
  const detailPinned = !hover && !!selected;

  // ---- map zoom / pan ----
  const zoomBy = (factor) => setZoom((z) => {
    const k = Math.max(1, Math.min(8, z.k * factor));
    // keep the plot centered while zooming
    const cx = VW / 2, cy = VH / 2;
    return { k, x: cx - (cx - z.x) * (k / z.k), y: cy - (cy - z.y) * (k / z.k) };
  });
  const resetZoom = () => setZoom({ k: 1, x: 0, y: 0 });
  const onWheelMap = (e) => {
    if (!e.ctrlKey && Math.abs(e.deltaY) < 1) return;
    e.preventDefault();
    zoomBy(e.deltaY < 0 ? 1.12 : 1 / 1.12);
  };

  // Map a click on the SVG background to plot coords (accounting for zoom),
  // then select the nearest track to it.
  const nearestTrack = (px, py) => {
    let best = null, bestD = Infinity;
    const consider = (t) => {
      const p = dotPos(t);
      const d = (p.x - px) ** 2 + (p.y - py) ** 2;
      if (d < bestD) { bestD = d; best = t; }
    };
    visibleTracks.forEach((e) => consider(e.track));
    if (candidates) candidates.tracks.forEach(consider);
    playlistTracks.forEach(consider);
    return best;
  };
  const onMapBackgroundClick = (e) => {
    // A click that came at the end of a pan-drag shouldn't also select a track.
    if (didPanRef.current) { didPanRef.current = false; return; }
    // Clicks on a dot/line stopPropagation, so reaching here means empty space:
    // select the nearest track to the click.
    const svg = e.currentTarget;
    const rect = svg.getBoundingClientRect();
    const sx = ((e.clientX - rect.left) / rect.width) * VW;
    const sy = ((e.clientY - rect.top) / rect.height) * VH;
    // invert zoom transform: screen = k*plot + offset
    const px = (sx - zoom.x) / zoom.k;
    const py = (sy - zoom.y) / zoom.k;
    const t = nearestTrack(px, py);
    if (t) setSelectedId(t.id);
  };

  // ---- click-drag to pan (only meaningful when zoomed in) ----
  const onMapPointerDown = (e) => {
    if (zoom.k <= 1 || e.button !== 0) return;
    panRef.current = { sx: e.clientX, sy: e.clientY, ox: zoom.x, oy: zoom.y, rect: e.currentTarget.getBoundingClientRect() };
    didPanRef.current = false;
  };
  const onMapPointerMove = (e) => {
    const pan = panRef.current;
    if (!pan) return;
    const dx = (e.clientX - pan.sx) * (VW / pan.rect.width);
    const dy = (e.clientY - pan.sy) * (VH / pan.rect.height);
    if (!didPanRef.current && Math.abs(e.clientX - pan.sx) + Math.abs(e.clientY - pan.sy) > 3) {
      didPanRef.current = true;
    }
    if (didPanRef.current) setZoom((z) => ({ ...z, x: pan.ox + dx, y: pan.oy + dy }));
  };
  const onMapPointerUp = () => { panRef.current = null; };

  const onLayerKeyDown = (e) => {
    if (e.key === 'Enter' && vibeQuery.trim()) {
      // Add the *typed* text — suggestions are never auto-selected.
      addVibeLayer(vibeQuery.trim());
      setVibeQuery('');
    } else if (e.key === 'Backspace' && !vibeQuery && layers.length) {
      removeLayer(layers[layers.length - 1].id);
    }
  };

  // ---- track detail card (shared by the bar above the map) ----
  function DetailCard({ t, pinned }) {
    if (!t) return null;
    const cand = isCandidate(t.id);
    const sources = entryByTrackId.get(t.id)?.sources || [];
    const inPlaylistOrigin = playlistById.get(t.id)?.origin;
    const label = labelsByTrackId[t.id];
    return (
      <div className={'ld-detail ' + (pinned ? 'is-pinned' : '')}>
        <div className="ld-detail-main">
          <div className="ld-detail-sources">
            {cand && <span className="lc-source-tag" style={{ borderColor: CANDIDATE_COLOR, color: CANDIDATE_COLOR }}>interpolation</span>}
            {sources.map((l) => (
              <span key={l.id} className="lc-source-tag" style={{ borderColor: l.color, color: l.color }}>
                <span className="ld-layer-swatch" style={{ background: l.color }} />{layerTag(l)}
              </span>
            ))}
            {!sources.length && !cand && inPlaylistOrigin && (
              <span className="lc-source-tag" style={{ borderColor: inPlaylistOrigin.color, color: inPlaylistOrigin.color }}>
                {layerKindWord(inPlaylistOrigin)} {inPlaylistOrigin.label}
              </span>
            )}
            {playing && playing.id !== t.id && (
              <span className="ld-detail-dist">{distBetween(playing, t).toFixed(2)} away</span>
            )}
          </div>
          <div className="ld-detail-title">
            {t.title}
            <SourceLink track={t} />
          </div>
          <div className="ld-detail-sub">{t.artist} — {t.album}</div>
          {t.track_url && (
            <a className="ld-detail-url" href={t.track_url} target="_blank" rel="noopener noreferrer"
              onClick={(e) => e.stopPropagation()} title={t.track_url}>
              <IconExternal size={12} />{prettyUrl(t.track_url)}
            </a>
          )}
        </div>
        {/* Actions are always visible (no hover gating). */}
        <div className="ld-detail-actions">
          <button className="lo-btn-ghost" onClick={() => playTrack(t)}>▶ Play</button>
          <button className="lo-btn-ghost" onClick={() => (cand ? insertCandidate(t) : addToPlaylist(t))} title="Add to playlist">
            <IconListPlus size={15} />
          </button>
          <button className="lo-btn-ghost" onClick={() => addSeedLayer('similar', t)} title="Find similar"><IconSimilar size={15} /></button>
          <button className="lo-btn-ghost" onClick={() => addSeedLayer('dissimilar', t)} title="Find dissimilar"><IconDissimilar size={15} /></button>
          <FeedbackPills track={t} value={label} onLabel={labelTrack} />
        </div>
      </div>
    );
  }

  return (
    <div className="lo-shell ld-shell" data-density="cozy">
      <audio
        ref={audioRef}
        onTimeUpdate={(e) => {
          const a = e.currentTarget;
          setProgress(a.duration ? a.currentTime / a.duration : 0);
        }}
        onLoadedMetadata={(e) => setDuration(e.currentTarget.duration || 0)}
        onEnded={() => { setIsPlaying(false); step(1); }}
        onPause={() => setIsPlaying(false)}
        onPlay={() => setIsPlaying(true)}
      />

      {/* ===== TOP BAR ===== */}
      <header className="ld-top">
        <Wordmark size="md" />

        <div className="ld-tagger">
          {layers.map((l) => (
            <span
              key={l.id}
              className={'el-chip is-active ld-layer-pill '
                + (l.visible ? '' : 'is-hidden ')
                + (soloLayerId === l.id ? 'is-solo ' : '')
                + (soloLayerId && soloLayerId !== l.id ? 'is-ghost' : '')}
              style={{ borderColor: l.color }}
              onClick={() => toggleSolo(l.id)}
              title={soloLayerId === l.id ? 'Showing only this search — click to show all' : 'Show only this search'}
            >
              <span className="ld-layer-swatch" style={{ background: l.color }} />
              <span className="ld-layer-label">{layerTag(l)}</span>
              {l.enhancedQuery && <span className="ld-layer-spark" aria-hidden="true">✨</span>}
              <button className="ld-layer-btn" onClick={(e) => { e.stopPropagation(); toggleLayerVisible(l.id); }}
                title={l.visible ? 'Hide this search' : 'Show this search'}>
                {l.visible ? <IconEye size={14} /> : <IconEyeOff size={14} />}
              </button>
              <button className="el-chip-remove" onClick={(e) => { e.stopPropagation(); removeLayer(l.id); }} title="Remove search">×</button>
              <span className="ld-layer-info">
                <strong>{layerKindWord(l)} “{l.label}”</strong>
                <span className="lo-eyebrow">{l.loading ? 'searching…' : `${l.results.length} tracks`}</span>
                {l.enhancedQuery && <em>✨ {l.enhancedQuery}</em>}
                {/* For similar/dissimilar, surface the exact seed song and let
                    you jump to it. */}
                {l.seedTrack && (
                  <button className="ld-layer-seed" onClick={(e) => { e.stopPropagation(); setSelectedId(l.seedTrack.id); }}>
                    {l.seedTrack.title} — {l.seedTrack.artist}
                  </button>
                )}
              </span>
            </span>
          ))}
          <input
            className="ld-tagger-input"
            placeholder={layers.length ? '+ another search…' : 'Tag vibes or describe a mood…'}
            value={vibeQuery}
            onChange={(e) => setVibeQuery(e.target.value)}
            onKeyDown={onLayerKeyDown}
          />
          <button
            className="ld-tagger-dice"
            title="Surprise me"
            onClick={() => addVibeLayer(suggestions[Math.floor(Math.random() * suggestions.length)])}
          >🎲</button>
          {layers.length > 0 && (
            <div className="ld-layer-toolbar">
              <button className="lo-btn-ghost ld-mini-btn" onClick={showAllLayers} disabled={allVisible}>Show all</button>
              <button className="lo-btn-ghost ld-mini-btn" onClick={clearLayers}>Clear all</button>
            </div>
          )}
        </div>

        <div className="ld-view-toggle" role="tablist" aria-label="View">
          <button role="tab" aria-selected={view === 'map'}
            className={'ld-view-btn ' + (view === 'map' ? 'is-active' : '')}
            onClick={() => setView('map')}>
            <svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor"><circle cx="12" cy="12" r="2.5" /><circle cx="12" cy="12" r="6" fill="none" stroke="currentColor" strokeWidth="1.2" /><circle cx="12" cy="12" r="10" fill="none" stroke="currentColor" strokeWidth="1.2" opacity="0.5" /></svg>
            Map
          </button>
          <button role="tab" aria-selected={view === 'list'}
            className={'ld-view-btn ' + (view === 'list' ? 'is-active' : '')}
            onClick={() => setView('list')}>
            <svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor"><rect x="3" y="5" width="18" height="2" rx="1" /><rect x="3" y="11" width="18" height="2" rx="1" /><rect x="3" y="17" width="18" height="2" rx="1" /></svg>
            List
          </button>
        </div>

        <button className="lo-btn-icon" title="About" onClick={() => setAboutOpen(true)}>
          <svg viewBox="0 0 24 24" fill="currentColor" width="18" height="18"><path d="M3 18h18v-2H3v2zm0-5h18v-2H3v2zm0-7v2h18V6H3z" /></svg>
        </button>
      </header>

      {/* Suggestion strip — ALWAYS visible. Adds a layer on click; never
          auto-selects. */}
      <div className="ld-suggest-strip">
        <span className="lo-eyebrow">{vibeQuery ? `Matching “${vibeQuery}”` : 'Try a vibe'}</span>
        <div className="ld-suggest-list">
          {vibeSuggestions.map((v) => (
            <button key={v} className="el-chip" onClick={() => { addVibeLayer(v); setVibeQuery(''); }}>+ {v}</button>
          ))}
          {vibeQuery && !vibeSuggestions.some((v) => v.toLowerCase() === vibeQuery.toLowerCase()) && (
            <button className="el-chip" onClick={() => { addVibeLayer(vibeQuery.trim()); setVibeQuery(''); }}>
              + Add “{vibeQuery}” as a search
            </button>
          )}
        </div>
      </div>

      {/* ===== MAIN ===== */}
      <main className="ld-main">
        {/* LEFT — PLAYLIST RAIL */}
        <aside className="ld-rail">
          <div className="la-rail-head">
            <h2 className="lo-eyebrow-strong">Your playlist</h2>
            <button className="lo-btn-ghost ld-mini-btn" onClick={clearPlaylist}>Clear</button>
          </div>

          <div className="ld-trail-hint lo-eyebrow">
            {playlistTracks.length > 1
              ? 'Click a link between two tracks to find tracks in between. Drag to reorder.'
              : 'Add tracks, then click between them to interpolate.'}
          </div>

          <div className="la-trail-list lo-scroll">
            {playlist.map((slot, i) => {
              const t = slot.track;
              if (!t) return null;
              const prev = playlist[i - 1]?.track;
              const layerPresent = slot.origin && layers.some((l) => l.kind === slot.origin.kind
                && (slot.origin.kind === 'vibe'
                  ? l.query?.toLowerCase() === (slot.origin.query || '').toLowerCase()
                  : l.seedTrackId === slot.origin.seedTrackId));
              return (
                <React.Fragment key={slot.id}>
                  {i > 0 && prev && (
                    <button
                      className={'la-trail-link ld-trail-link-btn ' +
                        (candidates && ((candidates.aId === prev.id && candidates.bId === t.id) ||
                          (candidates.aId === t.id && candidates.bId === prev.id)) ? 'is-active' : '')}
                      title="Find tracks between these two"
                      onClick={() => interpolateEdge(prev, t)}
                    ><IconPlus size={13} /></button>
                  )}
                  <div
                    className={'la-trail-card '
                      + (playingId === t.id ? 'is-playing ' : '')
                      + (dragOverId === slot.id ? 'is-drag-over ' : '')}
                    draggable
                    onDragStart={(e) => onDragStartSlot(e, slot.id)}
                    onDragOver={(e) => onDragOverSlot(e, slot.id)}
                    onDragLeave={() => setDragOverId((d) => (d === slot.id ? null : d))}
                    onDragEnd={onDragEndSlot}
                    onDrop={(e) => onDropSlot(e, slot.id)}
                  >
                    <div className="la-trail-marker"><span className="la-trail-dot" style={{ background: slot.color || 'var(--el-indigo-500)' }} /></div>
                    <div className="la-trail-body" onClick={() => playTrack(t)}>
                      <div className="la-trail-eye">
                        <span className="lo-eyebrow-strong">{`Step ${i + 1}`}</span>
                      </div>
                      <div className="lo-track-title" style={{ fontSize: '0.85rem', marginTop: 2 }}>
                        {t.title}<SourceLink track={t} />
                      </div>
                      <div className="lo-track-sub" style={{ fontSize: '0.72rem' }}>{t.artist}</div>
                    </div>
                    <div className="ld-trail-card-ctl">
                      <button className="lo-act-btn" title="Move up" disabled={i === 0}
                        onClick={(e) => { e.stopPropagation(); movePlaylist(slot.id, -1); }}><IconUp size={13} /></button>
                      <button className="lo-act-btn" title="Move down" disabled={i === playlist.length - 1}
                        onClick={(e) => { e.stopPropagation(); movePlaylist(slot.id, 1); }}><IconDown size={13} /></button>
                      {slot.origin && slot.origin.kind !== 'interp' && !layerPresent && (
                        <button className="lo-act-btn" title="Show this track's search layer again"
                          onClick={(e) => { e.stopPropagation(); restoreLayer(slot.origin); }}
                          style={{ color: slot.color }}><IconEye size={13} /></button>
                      )}
                      <button className="lo-act-btn" title="Remove from playlist"
                        onClick={(e) => { e.stopPropagation(); removeFromPlaylist(slot.id); }}><IconClose size={12} /></button>
                    </div>
                  </div>
                </React.Fragment>
              );
            })}
            {playlist.length === 0 && <div className="lo-eyebrow" style={{ padding: '12px 4px' }}>Add tracks to build a playlist.</div>}
          </div>
        </aside>

        {/* CENTER — MAP or LIST */}
        <section className="ld-center">
          <div className="ld-center-head">
            <div>
              <span className="lo-eyebrow">{view === 'map' ? 'MERT embeddings' : 'Results'}</span>
              <h2 className="el-h2" style={{ fontSize: '1.1rem' }}>
                {anyLoading ? 'Searching…' : (
                  <>{visibleTracks.length} tracks{' '}
                    <em>across {visibleLayers.length} {visibleLayers.length === 1 ? 'search' : 'searches'}</em></>
                )}
              </h2>
            </div>
            {candidates && (
              <button className="lo-btn-ghost ld-mini-btn" onClick={clearCandidates}>Clear interpolation</button>
            )}
          </div>

          {/* Track detail card — lives ABOVE the map so it never obscures dots. */}
          {view === 'map' && (
            <div className="ld-detail-bar">
              {detail
                ? <DetailCard t={detail} pinned={detailPinned} />
                : <div className="ld-detail-empty" />}
            </div>
          )}

          {view === 'map' ? (
            <div className="ld-map-wrap">
              <svg
                className="lc-canvas" viewBox={`0 0 ${VW} ${VH}`} preserveAspectRatio="xMidYMid meet"
                style={{ cursor: zoom.k > 1 ? 'grab' : 'default' }}
                onClick={onMapBackgroundClick}
                onWheel={onWheelMap}
                onMouseDown={onMapPointerDown}
                onMouseMove={onMapPointerMove}
                onMouseUp={onMapPointerUp}
                onMouseLeave={onMapPointerUp}
              >
                {/* background catch-rect so clicks on empty space register */}
                <rect x={0} y={0} width={VW} height={VH} fill="transparent" />
                <g transform={`translate(${zoom.x} ${zoom.y}) scale(${zoom.k})`}>
                  <g opacity="0.18" style={{ pointerEvents: 'none' }}>
                    {[0.25, 0.5, 0.75].map((g) => (
                      <React.Fragment key={g}>
                        <line x1={PAD + g * (VW - 2 * PAD)} y1={PAD} x2={PAD + g * (VW - 2 * PAD)} y2={VH - PAD} stroke="white" strokeWidth="0.5" />
                        <line x1={PAD} y1={PAD + g * (VH - 2 * PAD)} x2={VW - PAD} y2={PAD + g * (VH - 2 * PAD)} stroke="white" strokeWidth="0.5" />
                      </React.Fragment>
                    ))}
                    <rect x={PAD} y={PAD} width={VW - 2 * PAD} height={VH - 2 * PAD} fill="none" stroke="white" strokeWidth="0.6" />
                  </g>

                  {/* sonar rings on playing dot */}
                  {playing && [50, 100, 160, 230].map((r, i) => {
                    const pos = dotPos(playing);
                    return <circle key={i} cx={pos.x} cy={pos.y} r={r} fill="none" stroke="var(--el-yellow-500)" strokeOpacity={[0.55, 0.35, 0.22, 0.12][i]} strokeWidth={1} style={{ pointerEvents: 'none' }} />;
                  })}

                  {/* playlist edges — clickable to interpolate between endpoints */}
                  {playlistTracks.length > 1 && playlistTracks.slice(1).map((b, i) => {
                    const a = playlistTracks[i];
                    const pa = dotPos(a); const pb = dotPos(b);
                    const active = candidates && ((candidates.aId === a.id && candidates.bId === b.id) ||
                      (candidates.aId === b.id && candidates.bId === a.id));
                    const mx = (pa.x + pb.x) / 2, my = (pa.y + pb.y) / 2;
                    return (
                      <g key={`seg_${a.id}_${b.id}`} className="ld-edge" style={{ cursor: 'pointer' }}
                        onClick={(e) => { e.stopPropagation(); interpolateEdge(a, b); }}>
                        <title>Find tracks between “{a.title}” and “{b.title}”</title>
                        <line x1={pa.x} y1={pa.y} x2={pb.x} y2={pb.y} stroke="transparent" strokeWidth="16" />
                        <line x1={pa.x} y1={pa.y} x2={pb.x} y2={pb.y}
                          stroke="var(--el-indigo-500)" strokeOpacity={active ? 0.95 : 0.5}
                          strokeWidth={active ? 3 : 2} strokeDasharray="4 4" />
                        {/* midpoint "+" affordance signalling the line is clickable */}
                        <circle className="ld-edge-mid" cx={mx} cy={my} r={9} fill="var(--el-bg-secondary)" stroke="var(--el-indigo-500)" strokeWidth="1.5" strokeOpacity={active ? 1 : 0.7} />
                        <path className="ld-edge-mid" d={`M${mx - 4} ${my} h8 M${mx} ${my - 4} v8`} stroke="var(--el-indigo-500)" strokeWidth="1.5" strokeLinecap="round" />
                      </g>
                    );
                  })}
                  {playlistTracks.map((t) => {
                    const p = dotPos(t);
                    return <circle key={'tr_' + t.id} cx={p.x} cy={p.y} r={11} fill="none" stroke="var(--el-indigo-500)" strokeWidth="2" strokeOpacity="0.6" style={{ pointerEvents: 'none' }} />;
                  })}

                  {/* result dots, colored by their search layer */}
                  {visibleTracks.map(({ track: t, color }) => {
                    const p = dotPos(t);
                    const isPlay = t.id === playingId;
                    const isSel = t.id === selectedId;
                    const isHov = t.id === hoverId;
                    const inPlaylist = playlistById.has(t.id);
                    const r = isPlay ? 9 : isSel ? 7 : 5;
                    return (
                      <g key={t.id}
                        onMouseEnter={() => setHoverId(t.id)}
                        onMouseLeave={() => setHoverId((prev) => (prev === t.id ? null : prev))}
                        onClick={(e) => { e.stopPropagation(); setSelectedId(t.id); }}
                        onDoubleClick={(e) => { e.stopPropagation(); playTrack(t); }}
                        style={{ cursor: 'pointer' }}>
                        {(isHov || isSel) && (
                          <circle cx={p.x} cy={p.y} r={r + 6} fill="none" stroke={isSel ? color : 'rgba(255,255,255,0.3)'} strokeWidth="1.5" />
                        )}
                        <circle cx={p.x} cy={p.y} r={r} fill={color} opacity={inPlaylist ? 1 : 0.85}
                          style={{ filter: isPlay ? `drop-shadow(0 0 8px ${color})` : 'none' }} />
                        {inPlaylist && <circle cx={p.x} cy={p.y} r={r + 3} fill="none" stroke="white" strokeWidth="1" />}
                      </g>
                    );
                  })}

                  {/* playlist tracks whose source layer is no longer visible still
                      get a dot (colored by their saved origin). */}
                  {playlistTracks.map((t) => {
                    if (entryByTrackId.has(t.id)) return null;
                    const p = dotPos(t);
                    const isSel = t.id === selectedId;
                    const isPlay = t.id === playingId;
                    const slot = playlistById.get(t.id);
                    const color = slot?.color || FALLBACK_COLOR;
                    return (
                      <g key={'pl_' + t.id}
                        onMouseEnter={() => setHoverId(t.id)}
                        onMouseLeave={() => setHoverId((prev) => (prev === t.id ? null : prev))}
                        onClick={(e) => { e.stopPropagation(); setSelectedId(t.id); }}
                        onDoubleClick={(e) => { e.stopPropagation(); playTrack(t); }}
                        style={{ cursor: 'pointer' }}>
                        {isSel && <circle cx={p.x} cy={p.y} r={12} fill="none" stroke={color} strokeWidth="1.5" />}
                        <circle cx={p.x} cy={p.y} r={isPlay ? 9 : 6} fill={color} opacity={0.9} />
                        <circle cx={p.x} cy={p.y} r={9} fill="none" stroke="white" strokeWidth="1" strokeOpacity="0.7" />
                      </g>
                    );
                  })}

                  {/* interpolation candidates — distinct white, dashed-ring style */}
                  {candidates && candidates.tracks.map((t) => {
                    if (entryByTrackId.has(t.id)) return null;
                    const p = dotPos(t);
                    const isSel = t.id === selectedId;
                    return (
                      <g key={'cand_' + t.id}
                        onMouseEnter={() => setHoverId(t.id)}
                        onMouseLeave={() => setHoverId((prev) => (prev === t.id ? null : prev))}
                        onClick={(e) => { e.stopPropagation(); setSelectedId(t.id); }}
                        onDoubleClick={(e) => { e.stopPropagation(); playTrack(t); }}
                        style={{ cursor: 'pointer' }}>
                        <circle cx={p.x} cy={p.y} r={9} fill="none" stroke={CANDIDATE_COLOR} strokeWidth="1.2" strokeOpacity="0.7" strokeDasharray="3 2" />
                        <circle cx={p.x} cy={p.y} r={4.5} fill={CANDIDATE_COLOR} opacity={isSel ? 1 : 0.85} />
                      </g>
                    );
                  })}

                </g>
              </svg>

              {/* MERT projection caption + explainer */}
              <div className="ld-map-caption lo-eyebrow">
                MERT embeddings
                <span className="ld-info" tabIndex={0}
                  aria-label="A 2D map of MERT audio embeddings (PCA projection). Dots close together sound similar; the axes themselves aren't meaningful.">
                  <IconInfo size={12} />
                  <span className="ld-info-pop">
                    A 2D map of the tracks' MERT audio embeddings (PCA projection). Dots that sit close together
                    sound similar — the axes themselves aren't meaningful.
                  </span>
                </span>
              </div>

              {/* zoom controls */}
              <div className="ld-zoom">
                <button className="lo-btn-icon" title="Zoom in" onClick={() => zoomBy(1.25)}><IconZoomIn size={16} /></button>
                <button className="lo-btn-icon" title="Zoom out" onClick={() => zoomBy(1 / 1.25)}><IconZoomOut size={16} /></button>
                <button className="lo-btn-icon" title="Reset view" onClick={resetZoom} disabled={zoom.k === 1 && zoom.x === 0 && zoom.y === 0}><IconRecenter size={16} /></button>
              </div>

              <div className="lc-legend">
                {visibleLayers.map((l) => (
                  <div key={l.id} className="lc-legend-row">
                    <span className="lc-legend-dot" style={{ background: l.color }} /> {layerTag(l)}
                  </div>
                ))}
                {candidates && (
                  <div className="lc-legend-row">
                    <span className="lc-legend-dot" style={{ background: CANDIDATE_COLOR }} /> interpolation
                  </div>
                )}
                {playlistTracks.length > 1 && (
                  <>
                    <div className="lc-legend-divider" />
                    <div className="lc-legend-row">
                      <svg width="22" height="6"><line x1="0" y1="3" x2="22" y2="3" stroke="var(--el-indigo-500)" strokeWidth="2" strokeDasharray="4 3" /></svg>
                      playlist (click ＋ to interpolate)
                    </div>
                  </>
                )}
              </div>
            </div>
          ) : (
            <div className="ld-list lo-scroll">
              {visibleTracks.map(({ track: t, color, sources }, i) => {
                const inPlaylist = playlistById.has(t.id);
                const isPlay = playingId === t.id;
                return (
                  <div key={t.id}
                    className={'lo-track ld-track ' + (isPlay ? 'is-playing ' : '')}
                    onClick={() => { setSelectedId(t.id); playTrack(t); }}>
                    <span className="lo-track-num">{(i + 1).toString().padStart(2, '0')}</span>
                    <span className="ld-dot-inline" style={{ background: color }} title={sources.map(layerTag).join(', ')} />
                    <button className="lo-track-play" title="Play" onClick={(e) => { e.stopPropagation(); playTrack(t); }}>▶</button>
                    <div className="lo-track-info">
                      <div className="lo-track-title">{t.title}<SourceLink track={t} /></div>
                      <div className="lo-track-sub">{t.artist} — {t.album}</div>
                      {/* search origin shown inline in every row */}
                      <div className="ld-track-origin">
                        {sources.map((l) => (
                          <span key={l.id} className="ld-origin-tag" style={{ color: l.color }}>
                            <span className="ld-layer-swatch" style={{ background: l.color }} />{layerTag(l)}
                          </span>
                        ))}
                      </div>
                    </div>
                    <FeedbackPills track={t} value={labelsByTrackId[t.id]} onLabel={labelTrack} />
                    <DistanceChip value={distChipValue(t)} />
                    <div className="lo-track-actions">
                      <button className="lo-act-btn" title="Find similar" onClick={(e) => { e.stopPropagation(); addSeedLayer('similar', t); }}><IconSimilar size={15} /></button>
                      <button className="lo-act-btn" title="Find dissimilar" onClick={(e) => { e.stopPropagation(); addSeedLayer('dissimilar', t); }}><IconDissimilar size={15} /></button>
                      <button className={'lo-act-btn ' + (inPlaylist ? 'is-active' : '')} title={inPlaylist ? 'In your playlist' : 'Add to playlist'}
                        onClick={(e) => { e.stopPropagation(); addToPlaylist(t); }}>{inPlaylist ? <IconCheck size={15} /> : <IconListPlus size={15} />}</button>
                    </div>
                  </div>
                );
              })}
              {!anyLoading && visibleTracks.length === 0 && <div className="lo-eyebrow" style={{ padding: 16 }}>No results. Add a vibe above to start.</div>}
            </div>
          )}
        </section>

        {/* RIGHT — NOW PLAYING */}
        <aside className="ld-now-rail">
          <div className="lo-now">
            <div className="lo-now-art"><img src={`${ASSET}assets/artwork.svg`} alt="" className="lo-now-art-mascot" /></div>
            <div>
              <div className="lo-eyebrow-strong">Now playing</div>
              <div className="lo-now-title">{playing ? <>{playing.title}<SourceLink track={playing} /></> : '—'}</div>
              <div className="lo-now-sub">{playing ? `${playing.artist} — ${playing.album}` : 'Pick a track'}</div>
              {playing && (() => {
                const src = entryByTrackId.get(playing.id)?.sources?.[0] || playlistById.get(playing.id)?.origin;
                return (
                  <div className="lo-eyebrow" style={{ marginTop: 4 }}>
                    Playing from {navSource}
                    {src && <> · <span style={{ color: src.color }}>{layerKindWord(src)} {src.label}</span></>}
                  </div>
                );
              })()}
            </div>
            <div>
              <Waveform width={244} height={36} progress={progress} bars={48} seed={(playingId || 'x').charCodeAt(0) + 3} onSeek={playing ? seekTo : null} />
              <div className="lo-now-times">
                <span>{fmtTime(playingTotal * progress)}</span>
                <span>{fmtTime(playingTotal)}</span>
              </div>
            </div>
            <div className="lo-now-controls">
              <button className="lo-now-btn" title="Previous" onClick={() => step(-1)}>
                <svg viewBox="0 0 24 24" fill="currentColor" width="16" height="16"><path d="M6 6h2v12H6zm3.5 6l8.5 6V6z" /></svg>
              </button>
              <button className="lo-now-btn is-play" title={isPlaying ? 'Pause' : 'Play'} onClick={togglePlay}>
                {isPlaying
                  ? <svg viewBox="0 0 24 24" fill="white" width="18" height="18"><path d="M6 5h4v14H6zm8 0h4v14h-4z" /></svg>
                  : <svg viewBox="0 0 24 24" fill="white" width="18" height="18"><path d="M8 5v14l11-7z" /></svg>}
              </button>
              <button className="lo-now-btn" title="Next" onClick={() => step(1)}>
                <svg viewBox="0 0 24 24" fill="currentColor" width="16" height="16"><path d="M6 18l8.5-6L6 6v12zM16 6v12h2V6h-2z" /></svg>
              </button>
            </div>
          </div>

          {playing && (
            <div className="la-now-actions">
              <div className="lo-now-fb">
                <FeedbackPills track={playing} value={labelsByTrackId[playing.id]} onLabel={labelTrack} />
              </div>
              <button className="lo-btn-ghost" onClick={() => addSeedLayer('similar', playing)}>
                <IconSimilar size={15} /> <span style={{ marginLeft: 6 }}>Similar to this</span>
              </button>
              <button className="lo-btn-ghost" onClick={() => addSeedLayer('dissimilar', playing)}>
                <IconDissimilar size={15} /> <span style={{ marginLeft: 6 }}>Dissimilar to this</span>
              </button>
              <button className="lo-btn-ghost" onClick={() => addToPlaylist(playing)}>
                <IconListPlus size={15} /> <span style={{ marginLeft: 6 }}>Add to playlist</span>
              </button>
            </div>
          )}
        </aside>
      </main>

      {/* ===== ABOUT MODAL — mirrors the legacy frontend's hamburger/about ===== */}
      {aboutOpen && (
        <div className="ld-about-overlay" role="dialog" aria-modal="true" aria-label="About EchoLocate"
          onClick={(e) => { if (e.target === e.currentTarget) setAboutOpen(false); }}>
          <div className="ld-about-card">
            <button className="ld-about-close" aria-label="Close" onClick={() => setAboutOpen(false)}>✕</button>
            <h2 className="el-h2" style={{ fontSize: '1.4rem', marginBottom: 8 }}>About EchoLocate</h2>
            <p className="el-body-muted">
              EchoLocate is an AI-powered music discovery system that uses audio embeddings for
              sonic similarity search. The sonar map plots tracks by a 2D PCA projection of their
              MERT <code>v_mid</code> embedding — the same vector used for interpolation. Search
              layers, build a playlist, and click the lines between tracks to interpolate.
            </p>
            <p className="el-body-muted" style={{ marginTop: 10 }}>
              <a className="ld-about-link" href="https://github.com/along528/echolocate" target="_blank" rel="noopener noreferrer">View on GitHub ↗</a>
            </p>
            <p className="el-italic-muted" style={{ marginTop: 12 }}>Built with MERT + CLAP embeddings, DuckDB VSS, and HNSW indexing.</p>
          </div>
        </div>
      )}
    </div>
  );
}

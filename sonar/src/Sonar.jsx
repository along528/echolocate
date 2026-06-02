// Sonar — "sonar map + list", wired to the real EchoLocate vector service.
//
// Search model: each vibe / similar / dissimilar query is its own *layer* with
// its own color. Layers coexist on the map and in the list; every dot is colored
// by the search it came from. Each layer can be hidden (eye toggle) without being
// removed. The 2D positions come from each track's x,y (a PCA projection of the
// MERT v_mid embedding — the same embedding used for interpolation).
import React from 'react';
import { API } from './api.js';
import { Labels } from './labels.js';
import { Wordmark, Waveform, DistanceChip } from './svg-bits.jsx';

// Curated vibe vocabulary for the tagger suggestions + dice. These are just
// query terms; any freeform text works too.
const SUGGESTED_VIBES = [
  'dreamy lo-fi', 'smooth jazz', 'late night sax', 'glitchy IDM', 'ambient drone',
  'funky bass', 'ethereal vocals', 'raw punk', 'melancholic piano', 'cosmic synth',
  'minimal techno', 'orchestral swells', 'boom bap', 'shoegaze wall', 'krautrock motorik',
  'bossa nova', 'afrobeat horns', 'breakbeats', 'dub reggae', 'surf rock reverb',
  'cinematic cello', 'acid house', 'whispery folk', 'chiptune',
];

// Per-search layer colors. A search's color is its identity everywhere (pill,
// dots, list rows). White is reserved for interpolation candidates, so it's
// excluded here.
const LAYER_COLORS = [
  '#22d3ee', '#f472b6', '#fbbf24', '#a78bfa', '#34d399',
  '#60a5fa', '#fb7185', '#c084fc', '#facc15', '#4ade80',
];
const CANDIDATE_COLOR = '#ffffff';
const FALLBACK_COLOR = '#94a3b8';

const VW = 760;
const VH = 540;

// Prefix for public/ assets, respecting the build base (e.g. "/sonar/").
const ASSET = import.meta.env.BASE_URL;

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
  return { x: 60 + cx * (VW - 120), y: 60 + (1 - cy) * (VH - 120) };
}

function distBetween(a, b) {
  if (!a || !b) return 0;
  const [ax, ay] = coordsOf(a);
  const [bx, by] = coordsOf(b);
  return Math.min(1, Math.sqrt((ax - bx) ** 2 + (ay - by) ** 2));
}

// similarity (1 = identical) -> DistanceChip value (0 = identical)
const distChipValue = (t) => (typeof t.similarity === 'number' ? 1 - t.similarity : 0);

const layerTag = (l) => (l.kind === 'similar' ? '≈ ' : l.kind === 'dissimilar' ? '≠ ' : '') + l.label;

// 3-way training-signal feedback (relevant / borderline / wrong), restored from
// the legacy frontend. Fires Labels.recordLabel and reflects the local choice.
function FeedbackPills({ track, value, onLabel }) {
  const opts = [
    ['relevant', '✓', 'Relevant'],
    ['borderline', '≈', 'Borderline'],
    ['wrong', '✕', 'Wrong'],
  ];
  return (
    <div className="ld-fb" onClick={(e) => e.stopPropagation()}>
      {opts.map(([sig, glyph, title]) => (
        <button
          key={sig}
          className={'ld-fb-btn ld-fb-' + sig + (value === sig ? ' is-selected' : '')}
          title={title}
          onClick={(e) => { e.stopPropagation(); onLabel(track, sig); }}
        >{glyph}</button>
      ))}
    </div>
  );
}

function FmaLink({ track }) {
  if (!track || !track.track_url) return null;
  return (
    <a className="ld-fma" href={track.track_url} target="_blank" rel="noopener noreferrer"
      onClick={(e) => e.stopPropagation()} title="Open on Free Music Archive">↗ FMA</a>
  );
}

export default function Sonar({ initialView = 'map' }) {
  const [view, setView] = React.useState(initialView);
  const [vibeQuery, setVibeQuery] = React.useState('');

  // ---- search layers ----
  const colorIdxRef = React.useRef(0);
  const makeLayer = React.useCallback((kind, extra) => ({
    id: `L_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`,
    kind,
    label: '',
    query: '',
    seedTrackId: null,
    color: LAYER_COLORS[colorIdxRef.current++ % LAYER_COLORS.length],
    visible: true,
    loading: false,
    fetched: false,
    results: [],
    enhancedQuery: null,
    searchId: null,
    ...extra,
  }), []);

  const [layers, setLayers] = React.useState(() => [
    { id: `L_${Date.now()}_seed`, kind: 'vibe', label: 'dreamy lo-fi', query: 'dreamy lo-fi',
      seedTrackId: null, color: LAYER_COLORS[colorIdxRef.current++ % LAYER_COLORS.length],
      visible: true, loading: false, fetched: false, results: [], enhancedQuery: null, searchId: null },
  ]);

  const [playingId, setPlayingId] = React.useState(null);
  const [hoverId, setHoverId] = React.useState(null);
  const [selectedId, setSelectedId] = React.useState(null);
  const [isPlaying, setIsPlaying] = React.useState(false);
  const [progress, setProgress] = React.useState(0);
  const [duration, setDuration] = React.useState(0);

  const [trail, setTrail] = React.useState([]);
  const [candidates, setCandidates] = React.useState(null); // { aId, bId, tracks }
  const [labelsByTrackId, setLabelsByTrackId] = React.useState({});
  const audioRef = React.useRef(null);

  React.useEffect(() => { Labels.init(); }, []);

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

  // Fetch any layer that hasn't been fetched yet.
  React.useEffect(() => {
    const pending = layers.filter((l) => !l.fetched && !l.loading);
    if (!pending.length) return;
    pending.forEach((l) => {
      setLayers((ls) => ls.map((x) => (x.id === l.id ? { ...x, loading: true } : x)));
      runLayerSearch(l)
        .then(({ results, enhancedQuery, searchId }) => {
          setLayers((ls) => ls.map((x) => (x.id === l.id
            ? { ...x, loading: false, fetched: true, results, enhancedQuery, searchId } : x)));
          setSelectedId((prev) => prev ?? results[0]?.id ?? null);
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
      ? ls : [...ls, makeLayer(kind, { label: track.title, seedTrackId: track.id })]));
  };
  const removeLayer = (id) => setLayers((ls) => ls.filter((l) => l.id !== id));
  const toggleLayerVisible = (id) =>
    setLayers((ls) => ls.map((l) => (l.id === id ? { ...l, visible: !l.visible } : l)));

  // ---- derived ----
  const visibleLayers = React.useMemo(() => layers.filter((l) => l.visible), [layers]);
  const anyLoading = layers.some((l) => l.loading);

  // De-duped union of visible layers' results. Overlap takes the first (oldest)
  // visible layer's color; sources lists every visible layer the track is in.
  const visibleTracks = React.useMemo(() => {
    const seen = new Map();
    const order = [];
    for (const l of layers) {
      if (!l.visible) continue;
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
  }, [layers]);

  const entryByTrackId = React.useMemo(() => {
    const m = new Map();
    visibleTracks.forEach((e) => m.set(e.track.id, e));
    return m;
  }, [visibleTracks]);

  const trackColor = (id) => entryByTrackId.get(id)?.color
    || (candidates?.tracks.some((t) => t.id === id) ? CANDIDATE_COLOR : FALLBACK_COLOR);

  // Index of every track we have full metadata for (all layers + candidates + trail).
  const tracksById = React.useMemo(() => {
    const m = new Map();
    layers.forEach((l) => l.results.forEach((t) => m.set(t.id, t)));
    if (candidates) candidates.tracks.forEach((t) => m.set(t.id, t));
    trail.forEach((s) => { if (s.track) m.set(s.track.id, s.track); });
    return m;
  }, [layers, candidates, trail]);

  const playing = playingId ? tracksById.get(playingId) : null;
  const hover = hoverId ? tracksById.get(hoverId) : null;
  const selected = selectedId ? tracksById.get(selectedId) : null;

  const flatResults = React.useMemo(() => visibleTracks.map((e) => e.track), [visibleTracks]);

  // ---- vibe tagger ----
  const activeVibeTexts = React.useMemo(
    () => layers.filter((l) => l.kind === 'vibe').map((l) => l.query.toLowerCase()),
    [layers]);
  const vibeSuggestions = React.useMemo(() => {
    const q = vibeQuery.toLowerCase().trim();
    return SUGGESTED_VIBES
      .filter((v) => !activeVibeTexts.includes(v.toLowerCase()))
      .filter((v) => !q || v.toLowerCase().includes(q))
      .slice(0, q ? 12 : 10);
  }, [vibeQuery, activeVibeTexts]);

  // ---- trail ----
  const recomputeDist = (arr) =>
    arr.map((s, i) => ({ ...s, dist: i === 0 ? null : distBetween(arr[i - 1].track, s.track) }));

  const addToTrail = (track) => {
    if (!track) return;
    setTrail((t) => {
      if (t.some((s) => s.track?.id === track.id)) return t;
      const prev = t[t.length - 1]?.track || playing;
      const slot = {
        id: `s_${track.id}_${Date.now()}`,
        kind: t.length === 0 ? 'start' : 'interp',
        track,
        dist: t.length === 0 ? null : distBetween(prev, track),
      };
      const endIdx = t.findIndex((s) => s.kind === 'end');
      if (endIdx >= 0) return [...t.slice(0, endIdx), { ...slot, kind: 'interp' }, ...t.slice(endIdx)];
      return [...t, slot];
    });
  };
  // Insert a candidate between its edge's two endpoints (does not clear candidates).
  const insertCandidate = (track) => {
    if (!candidates) { addToTrail(track); return; }
    setTrail((t) => {
      if (t.some((s) => s.track?.id === track.id)) return t;
      const ai = t.findIndex((s) => s.track?.id === candidates.aId);
      const bi = t.findIndex((s) => s.track?.id === candidates.bId);
      if (ai < 0 || bi < 0) return [...t, { id: `s_${track.id}_${Date.now()}`, kind: 'interp', track, dist: null }];
      const at = Math.max(ai, bi); // insert before the later endpoint
      const slot = { id: `s_${track.id}_${Date.now()}`, kind: 'interp', track, dist: null };
      return recomputeDist([...t.slice(0, at), slot, ...t.slice(at)]);
    });
  };
  const removeFromTrail = (id) => setTrail((t) => recomputeDist(t.filter((s) => s.id !== id)));
  const clearTrail = () => { setTrail([]); setCandidates(null); };

  // Generate candidate tracks "between" two trail tracks (the clicked line).
  const interpolateEdge = async (a, b) => {
    if (!a || !b) return;
    try {
      const list = await API.interpolate(a.id, b.id, 'slerp', 8);
      const trailIds = new Set(trail.filter((s) => s.track).map((s) => s.track.id));
      const tracks = (Array.isArray(list) ? list : (list.results || []))
        .filter((t) => t.id !== a.id && t.id !== b.id && !trailIds.has(t.id));
      Labels.recordSearch('/interpolate', 'pair',
        { pair_track_ids: [a.id, b.id] }, { source: 'fma', method: 'slerp' }, tracks);
      setCandidates({ aId: a.id, bId: b.id, tracks });
    } catch (e) {
      console.error('interpolate failed', e);
    }
  };

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
  // Forward/back walks the trail when one exists, otherwise the visible results.
  const trailTracks = React.useMemo(() => trail.filter((s) => s.track).map((s) => s.track), [trail]);
  const navList = trailTracks.length ? trailTracks : flatResults;
  const navSource = trailTracks.length ? 'your trail' : 'search results';
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
              className={'el-chip is-active ld-layer-pill ' + (l.visible ? '' : 'is-hidden')}
              style={{ borderColor: l.color }}
            >
              <span className="ld-layer-swatch" style={{ background: l.color }} />
              <span className="ld-layer-label">{layerTag(l)}</span>
              <button
                className="ld-layer-eye"
                onClick={() => toggleLayerVisible(l.id)}
                title={l.visible ? 'Hide this search' : 'Show this search'}
              >{l.visible ? '◉' : '◌'}</button>
              <button className="el-chip-remove" onClick={() => removeLayer(l.id)} title="Remove search">×</button>
              <span className="ld-layer-info">
                <strong>{layerTag(l)}</strong>
                <span className="lo-eyebrow">{l.loading ? 'searching…' : `${l.results.length} tracks`}</span>
                {l.enhancedQuery && <em>✨ {l.enhancedQuery}</em>}
              </span>
            </span>
          ))}
          <input
            className="ld-tagger-input"
            placeholder={layers.length ? '+ another search…' : 'Tag vibes or describe a mood…'}
            value={vibeQuery}
            onChange={(e) => setVibeQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && vibeQuery.trim()) {
                addVibeLayer(vibeSuggestions[0] || vibeQuery.trim());
                setVibeQuery('');
              } else if (e.key === 'Backspace' && !vibeQuery && layers.length) {
                removeLayer(layers[layers.length - 1].id);
              }
            }}
          />
          <button
            className="ld-tagger-dice"
            title="Surprise me"
            onClick={() => addVibeLayer(SUGGESTED_VIBES[Math.floor(Math.random() * SUGGESTED_VIBES.length)])}
          >🎲</button>
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

        <button className="lo-btn-icon" title="About">
          <svg viewBox="0 0 24 24" fill="currentColor" width="18" height="18"><path d="M3 18h18v-2H3v2zm0-5h18v-2H3v2zm0-7v2h18V6H3z" /></svg>
        </button>
      </header>

      {(vibeQuery || layers.length === 0) && (
        <div className="ld-suggest-strip">
          <span className="lo-eyebrow">{vibeQuery ? `Matching “${vibeQuery}”` : 'Try a vibe'}</span>
          <div className="ld-suggest-list">
            {vibeSuggestions.map((v) => (
              <button key={v} className="el-chip" onClick={() => { addVibeLayer(v); setVibeQuery(''); }}>+ {v}</button>
            ))}
            {vibeQuery && vibeSuggestions.length === 0 && (
              <button className="el-chip" onClick={() => { addVibeLayer(vibeQuery.trim()); setVibeQuery(''); }}>
                + Add “{vibeQuery}” as a search
              </button>
            )}
          </div>
        </div>
      )}

      {/* ===== MAIN ===== */}
      <main className="ld-main">
        {/* LEFT — TRAIL RAIL */}
        <aside className="ld-rail">
          <div className="la-rail-head">
            <h2 className="lo-eyebrow-strong">Your trail</h2>
            <button className="lo-btn-ghost" style={{ padding: '4px 10px', fontSize: 11 }} onClick={clearTrail}>Clear</button>
          </div>

          <div className="ld-trail-hint lo-eyebrow">
            {trailTracks.length > 1
              ? 'Click a link between two tracks to find tracks in between.'
              : 'Add tracks, then click between them to interpolate.'}
          </div>

          <div className="la-trail-list lo-scroll">
            {trail.map((slot, i) => {
              const t = slot.track;
              if (!t) return null;
              const kindLabel = slot.kind === 'start' ? 'Start' : slot.kind === 'end' ? 'End' : `Step ${i}`;
              const prev = trail[i - 1]?.track;
              return (
                <React.Fragment key={slot.id}>
                  {i > 0 && prev && (
                    <button
                      className={'la-trail-link ld-trail-link-btn ' +
                        (candidates && ((candidates.aId === prev.id && candidates.bId === t.id) ||
                          (candidates.aId === t.id && candidates.bId === prev.id)) ? 'is-active' : '')}
                      title="Find tracks between these two"
                      onClick={() => interpolateEdge(prev, t)}
                    >＋</button>
                  )}
                  <div className={'la-trail-card ' + (slot.kind === 'interp' ? 'is-interp ' : '') + (playingId === t.id ? 'is-playing ' : '')}>
                    <div className="la-trail-marker"><span className={'la-trail-dot ' + slot.kind} /></div>
                    <div className="la-trail-body" onClick={() => playTrack(t)}>
                      <div className="la-trail-eye">
                        <span className={slot.kind === 'interp' ? 'lo-eyebrow-amber' : 'lo-eyebrow-strong'}>{kindLabel}</span>
                        {slot.kind === 'interp' && slot.dist != null && <DistanceChip value={slot.dist} kind="amber" />}
                      </div>
                      <div className="lo-track-title" style={{ fontSize: '0.85rem', marginTop: 2 }}>{t.title}</div>
                      <div className="lo-track-sub" style={{ fontSize: '0.72rem' }}>{t.artist}</div>
                    </div>
                    <button className="lo-act-btn" title="Remove" onClick={(e) => { e.stopPropagation(); removeFromTrail(slot.id); }}>×</button>
                  </div>
                </React.Fragment>
              );
            })}
            {trail.length === 0 && <div className="lo-eyebrow" style={{ padding: '12px 4px' }}>Add tracks to build a trail.</div>}
          </div>
        </aside>

        {/* CENTER — MAP or LIST */}
        <section className="ld-center">
          <div className="ld-center-head">
            <div>
              <span className="lo-eyebrow">{view === 'map' ? 'Embedding space' : 'Results'}</span>
              <h2 className="el-h2" style={{ fontSize: '1.1rem' }}>
                {anyLoading ? 'Searching…' : (
                  <>{visibleTracks.length} tracks{' '}
                    <em>across {visibleLayers.length} {visibleLayers.length === 1 ? 'search' : 'searches'}</em></>
                )}
              </h2>
            </div>
          </div>

          {view === 'map' ? (
            <div className="ld-map-wrap">
              <svg className="lc-canvas" viewBox={`0 0 ${VW} ${VH}`} preserveAspectRatio="xMidYMid meet">
                <g opacity="0.18">
                  {[0.25, 0.5, 0.75].map((g) => (
                    <React.Fragment key={g}>
                      <line x1={60 + g * (VW - 120)} y1={60} x2={60 + g * (VW - 120)} y2={VH - 60} stroke="white" strokeWidth="0.5" />
                      <line x1={60} y1={60 + g * (VH - 120)} x2={VW - 60} y2={60 + g * (VH - 120)} stroke="white" strokeWidth="0.5" />
                    </React.Fragment>
                  ))}
                  <rect x={60} y={60} width={VW - 120} height={VH - 120} fill="none" stroke="white" strokeWidth="0.6" />
                </g>

                {/* sonar rings on playing dot */}
                {playing && [50, 100, 160, 230].map((r, i) => {
                  const pos = dotPos(playing);
                  return <circle key={i} cx={pos.x} cy={pos.y} r={r} fill="none" stroke="var(--el-yellow-500)" strokeOpacity={[0.55, 0.35, 0.22, 0.12][i]} strokeWidth={1} />;
                })}

                {/* trail: each segment is clickable to interpolate between its endpoints */}
                {trailTracks.length > 1 && trailTracks.slice(1).map((b, i) => {
                  const a = trailTracks[i];
                  const pa = dotPos(a); const pb = dotPos(b);
                  const active = candidates && ((candidates.aId === a.id && candidates.bId === b.id) ||
                    (candidates.aId === b.id && candidates.bId === a.id));
                  return (
                    <g key={`seg_${a.id}_${b.id}`} style={{ cursor: 'pointer' }} onClick={() => interpolateEdge(a, b)}>
                      <line x1={pa.x} y1={pa.y} x2={pb.x} y2={pb.y} stroke="transparent" strokeWidth="16" />
                      <line x1={pa.x} y1={pa.y} x2={pb.x} y2={pb.y}
                        stroke="var(--el-indigo-500)" strokeOpacity={active ? 0.95 : 0.45}
                        strokeWidth={active ? 2.5 : 2} strokeDasharray="4 4" />
                    </g>
                  );
                })}
                {trailTracks.map((t) => {
                  const p = dotPos(t);
                  return <circle key={'tr_' + t.id} cx={p.x} cy={p.y} r={11} fill="none" stroke="var(--el-indigo-500)" strokeWidth="2" strokeOpacity="0.6" />;
                })}

                {/* result dots (bright, interactive), colored by their search layer */}
                {visibleTracks.map(({ track: t, color }) => {
                  const p = dotPos(t);
                  const isPlay = t.id === playingId;
                  const isSel = t.id === selectedId;
                  const isHov = t.id === hoverId;
                  const inTrail = trailTracks.some((x) => x.id === t.id);
                  const r = isPlay ? 9 : isSel ? 7 : 5;
                  return (
                    <g key={t.id}
                      onMouseEnter={() => setHoverId(t.id)}
                      onMouseLeave={() => setHoverId((prev) => (prev === t.id ? null : prev))}
                      onClick={() => setSelectedId(t.id)}
                      onDoubleClick={() => playTrack(t)}
                      style={{ cursor: 'pointer' }}>
                      {(isHov || isSel) && (
                        <circle cx={p.x} cy={p.y} r={r + 6} fill="none" stroke={isSel ? color : 'rgba(255,255,255,0.3)'} strokeWidth="1.5" />
                      )}
                      <circle cx={p.x} cy={p.y} r={r} fill={color} opacity={inTrail ? 1 : 0.85}
                        style={{ filter: isPlay ? `drop-shadow(0 0 8px ${color})` : 'none' }} />
                      {inTrail && <circle cx={p.x} cy={p.y} r={r + 3} fill="none" stroke="white" strokeWidth="1" />}
                    </g>
                  );
                })}

                {/* interpolation candidates — distinct white, dashed-ring style */}
                {candidates && candidates.tracks.map((t) => {
                  if (entryByTrackId.has(t.id)) return null; // already shown as a result dot
                  const p = dotPos(t);
                  const isSel = t.id === selectedId;
                  return (
                    <g key={'cand_' + t.id}
                      onMouseEnter={() => setHoverId(t.id)}
                      onMouseLeave={() => setHoverId((prev) => (prev === t.id ? null : prev))}
                      onClick={() => setSelectedId(t.id)}
                      onDoubleClick={() => playTrack(t)}
                      style={{ cursor: 'pointer' }}>
                      <circle cx={p.x} cy={p.y} r={9} fill="none" stroke={CANDIDATE_COLOR} strokeWidth="1.2" strokeOpacity="0.7" strokeDasharray="3 2" />
                      <circle cx={p.x} cy={p.y} r={4.5} fill={CANDIDATE_COLOR} opacity={isSel ? 1 : 0.85} />
                    </g>
                  );
                })}

                {/* hover / selected card — a foreignObject so it shares the dot transform */}
                {(hover || selected) && (() => {
                  const t = hover || selected;
                  const pinned = !hover && !!selected;
                  const p = dotPos(t);
                  const cardW = 260; const cardH = 210;
                  let fx = Math.max(6, Math.min(VW - cardW - 6, p.x - cardW / 2));
                  const above = p.y - cardH - 14 > 4;
                  const fy = above ? p.y - cardH - 14 : p.y + 14;
                  const cand = isCandidate(t.id);
                  const sources = entryByTrackId.get(t.id)?.sources || [];
                  const label = labelsByTrackId[t.id];
                  return (
                    <foreignObject x={fx} y={fy} width={cardW} height={cardH} style={{ pointerEvents: 'none', overflow: 'visible' }}>
                      <div className="lc-dot-card-wrap" style={{ height: cardH, alignItems: above ? 'flex-end' : 'flex-start' }}>
                        <div className="lc-dot-card" style={{ pointerEvents: pinned ? 'auto' : 'none' }}>
                          <div className="lc-dot-sources">
                            {cand && <span className="lc-source-tag" style={{ borderColor: CANDIDATE_COLOR, color: CANDIDATE_COLOR }}>interpolation</span>}
                            {sources.map((l) => (
                              <span key={l.id} className="lc-source-tag" style={{ borderColor: l.color, color: l.color }}>
                                <span className="ld-layer-swatch" style={{ background: l.color }} />{layerTag(l)}
                              </span>
                            ))}
                            {playing && <span style={{ marginLeft: 'auto', color: 'var(--el-yellow-500)', fontSize: 11 }}>{distBetween(playing, t).toFixed(2)} away</span>}
                          </div>
                          <div className="lc-dot-title">{t.title}</div>
                          <div className="lc-dot-sub">{t.artist} — {t.album}</div>
                          {pinned && (
                            <>
                              <div className="lc-dot-actions">
                                <button className="lo-btn-ghost" onClick={() => playTrack(t)}>▶ Play</button>
                                <button className="lo-btn-ghost" onClick={() => (cand ? insertCandidate(t) : addToTrail(t))}>+ Trail</button>
                                <button className="lo-btn-ghost" onClick={() => addSeedLayer('similar', t)}>≈ Similar</button>
                              </div>
                              <div className="lc-dot-foot">
                                <FeedbackPills track={t} value={label} onLabel={labelTrack} />
                                <FmaLink track={t} />
                              </div>
                            </>
                          )}
                        </div>
                      </div>
                    </foreignObject>
                  );
                })()}
              </svg>

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
                {trailTracks.length > 1 && (
                  <>
                    <div className="lc-legend-divider" />
                    <div className="lc-legend-row">
                      <svg width="22" height="6"><line x1="0" y1="3" x2="22" y2="3" stroke="var(--el-indigo-500)" strokeWidth="2" strokeDasharray="4 3" /></svg>
                      your trail
                    </div>
                  </>
                )}
              </div>
            </div>
          ) : (
            <div className="ld-list lo-scroll">
              {visibleTracks.map(({ track: t, color, sources }, i) => {
                const inTrail = trailTracks.some((x) => x.id === t.id);
                const isPlay = playingId === t.id;
                return (
                  <div key={t.id}
                    className={'lo-track ld-track ' + (isPlay ? 'is-playing ' : '')}
                    onClick={() => { setSelectedId(t.id); playTrack(t); }}>
                    <span className="lo-track-num">{(i + 1).toString().padStart(2, '0')}</span>
                    <span className="ld-dot-inline" style={{ background: color }} title={sources.map(layerTag).join(', ')} />
                    <button className="lo-track-play" title="Play" onClick={(e) => { e.stopPropagation(); playTrack(t); }}>▶</button>
                    <div className="lo-track-info">
                      <div className="lo-track-title">{t.title}</div>
                      <div className="lo-track-sub">{t.artist} — {t.album}</div>
                    </div>
                    <FmaLink track={t} />
                    <FeedbackPills track={t} value={labelsByTrackId[t.id]} onLabel={labelTrack} />
                    <DistanceChip value={distChipValue(t)} />
                    <div className="lo-track-actions">
                      <button className="lo-act-btn" title="Find similar" onClick={(e) => { e.stopPropagation(); addSeedLayer('similar', t); }}>≈</button>
                      <button className="lo-act-btn" title="Find dissimilar" onClick={(e) => { e.stopPropagation(); addSeedLayer('dissimilar', t); }}>≠</button>
                      <button className={'lo-act-btn ' + (inTrail ? 'is-active' : '')} title={inTrail ? 'In your trail' : 'Add to trail'}
                        onClick={(e) => { e.stopPropagation(); addToTrail(t); }}>{inTrail ? '✓' : '+'}</button>
                    </div>
                  </div>
                );
              })}
              {!anyLoading && visibleTracks.length === 0 && <div className="lo-eyebrow" style={{ padding: 16 }}>No results.</div>}
            </div>
          )}
        </section>

        {/* RIGHT — NOW PLAYING */}
        <aside className="ld-now-rail">
          <div className="lo-now">
            <div className="lo-now-art"><img src={`${ASSET}assets/artwork.svg`} alt="" className="lo-now-art-mascot" /></div>
            <div>
              <div className="lo-eyebrow-strong">Now playing</div>
              <div className="lo-now-title">{playing ? playing.title : '—'}</div>
              <div className="lo-now-sub">{playing ? `${playing.artist} — ${playing.album}` : 'Pick a track'}</div>
              {playing && <div className="lo-eyebrow" style={{ marginTop: 4 }}>Playing from {navSource}</div>}
            </div>
            <div>
              <Waveform width={244} height={36} progress={progress} bars={48} seed={(playingId || 'x').charCodeAt(0) + 3} />
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
                <FmaLink track={playing} />
              </div>
              <button className="lo-btn-ghost" onClick={() => addSeedLayer('similar', playing)}>
                <span style={{ marginRight: 6 }}>≈</span> Similar to this
              </button>
              <button className="lo-btn-ghost" onClick={() => addToTrail(playing)}>
                <span style={{ marginRight: 6 }}>+</span> Add to trail
              </button>
            </div>
          )}
        </aside>
      </main>
    </div>
  );
}

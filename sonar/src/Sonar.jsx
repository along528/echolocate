// Sonar — "sonar map + list", wired to the real EchoLocate vector service.
//
// Differences from the prototype (all tracked in TODO.md):
//  - results come from the vector API (semantic / similar / dissimilar), not mock data
//  - dot positions come from each track's x,y (semantic-axis projection)
//  - a sampled /map/backdrop provides the dimmed context field
//  - per-track vibe chips and the M:SS duration column are deferred (no backend source);
//    the now-playing total time comes from the real <audio> element instead
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

// SVG position. x: organic(0,left) -> synthetic(1,right). y: bright(1) at top.
function dotPos(t) {
  const [cx, cy] = coordsOf(t);
  return { x: 60 + cx * (VW - 120), y: 60 + (1 - cy) * (VH - 120) };
}

function dotColor(t) {
  const [m0, m1] = coordsOf(t);
  if (m0 < 0.5 && m1 < 0.5) return '#6366f1';
  if (m0 >= 0.5 && m1 < 0.5) return '#8b5cf6';
  if (m0 < 0.5 && m1 >= 0.5) return '#a78bfa';
  return '#fbbf24';
}

function distBetween(a, b) {
  if (!a || !b) return 0;
  const [ax, ay] = coordsOf(a);
  const [bx, by] = coordsOf(b);
  return Math.min(1, Math.sqrt((ax - bx) ** 2 + (ay - by) ** 2));
}

// similarity (1 = identical) -> DistanceChip value (0 = identical)
const distChipValue = (t) => (typeof t.similarity === 'number' ? 1 - t.similarity : 0);

export default function Sonar({ initialView = 'map' }) {
  const [view, setView] = React.useState(initialView);
  const [activeVibes, setActiveVibes] = React.useState(['dreamy lo-fi']);
  const [vibeQuery, setVibeQuery] = React.useState('');
  const [mode, setMode] = React.useState({ type: 'vibes' });

  const [results, setResults] = React.useState([]);
  const [enhancedQuery, setEnhancedQuery] = React.useState(null);
  const [loading, setLoading] = React.useState(false);
  const [backdrop, setBackdrop] = React.useState([]);

  const [playingId, setPlayingId] = React.useState(null);
  const [hoverId, setHoverId] = React.useState(null);
  const [selectedId, setSelectedId] = React.useState(null);
  const [isPlaying, setIsPlaying] = React.useState(false);
  const [progress, setProgress] = React.useState(0);
  const [duration, setDuration] = React.useState(0);

  const [trail, setTrail] = React.useState([]);
  const audioRef = React.useRef(null);

  React.useEffect(() => { Labels.init(); }, []);

  // Backdrop sample (dimmed field), fetched once.
  React.useEffect(() => {
    API.mapBackdrop('fma', 400).then(setBackdrop).catch((e) => console.warn('backdrop failed', e));
  }, []);

  // Result fetching: re-runs when the search mode or active vibes change.
  React.useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      try {
        let tracks = [];
        let enh = null;
        if (mode.type === 'similar') {
          tracks = await API.findSimilar(mode.track.id);
          Labels.recordSearch(`/tracks/${mode.track.id}/similar`, 'seed',
            { seed_track_id: mode.track.id }, { source: 'fma', polarity: 'similar' }, tracks);
        } else if (mode.type === 'dissimilar') {
          tracks = await API.findDissimilar(mode.track.id);
          Labels.recordSearch(`/tracks/${mode.track.id}/dissimilar`, 'seed',
            { seed_track_id: mode.track.id }, { source: 'fma', polarity: 'dissimilar' }, tracks);
        } else {
          const q = activeVibes.join(', ').trim();
          if (!q) {
            tracks = await API.getTracks(24, 'fma');
          } else {
            const r = await API.semanticSearch(q, 'fma', 24, true);
            tracks = r.results || r;
            enh = r.enhanced_query || null;
            Labels.recordSearch('/semantic-search', 'text',
              { text: q, enhanced_text: enh }, { source: 'fma', limit: 24, enhance: true }, tracks);
          }
        }
        if (cancelled) return;
        setResults(tracks);
        setEnhancedQuery(enh);
        setSelectedId((prev) => (tracks.some((t) => t.id === prev) ? prev : tracks[0]?.id ?? null));
      } catch (e) {
        if (!cancelled) console.error('search failed', e);
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [mode, activeVibes]);

  // Index of every track we have full metadata for (results + trail + nothing else).
  const tracksById = React.useMemo(() => {
    const m = new Map();
    results.forEach((t) => m.set(t.id, t));
    trail.forEach((s) => { if (s.track) m.set(s.track.id, s.track); });
    return m;
  }, [results, trail]);

  const playing = playingId ? tracksById.get(playingId) : null;
  const hover = hoverId ? tracksById.get(hoverId) : null;
  const selected = selectedId ? tracksById.get(selectedId) : null;
  const resultIds = React.useMemo(() => new Set(results.map((t) => t.id)), [results]);

  // ---- vibe tagger ----
  const toggleVibe = (v) => {
    setActiveVibes((av) => (av.includes(v) ? av.filter((x) => x !== v) : [...av, v]));
    setMode((m) => (m.type === 'vibes' ? m : { type: 'vibes' }));
  };
  const vibeSuggestions = React.useMemo(() => {
    const q = vibeQuery.toLowerCase().trim();
    return SUGGESTED_VIBES
      .filter((v) => !activeVibes.includes(v))
      .filter((v) => !q || v.toLowerCase().includes(q))
      .slice(0, q ? 12 : 10);
  }, [vibeQuery, activeVibes]);

  // ---- trail ----
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
      // insert before an existing 'end' slot, else append
      const endIdx = t.findIndex((s) => s.kind === 'end');
      if (endIdx >= 0) return [...t.slice(0, endIdx), { ...slot, kind: 'interp' }, ...t.slice(endIdx)];
      return [...t, slot];
    });
  };
  const removeFromTrail = (id) => setTrail((t) => t.filter((s) => s.id !== id));
  const clearTrail = () => setTrail([]);

  const regenerate = async () => {
    const withTrack = trail.filter((s) => s.track);
    if (withTrack.length < 2) return;
    const start = withTrack[0].track;
    const end = withTrack[withTrack.length - 1].track;
    try {
      const tracks = await API.interpolatePlaylist(start.id, end.id, 8, 'greedy_walk', 'fma');
      const slots = tracks.map((tk, i) => ({
        id: `s_${tk.id}_${i}`,
        kind: i === 0 ? 'start' : i === tracks.length - 1 ? 'end' : 'interp',
        track: tk,
        dist: i === 0 ? null : distBetween(tracks[i - 1], tk),
      }));
      setTrail(slots);
      Labels.recordSearch('/interpolate/playlist', 'pair',
        { pair_track_ids: [start.id, end.id] }, { source: 'fma', method: 'greedy_walk' }, tracks.slice(1, -1));
    } catch (e) {
      console.error('regenerate failed', e);
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
  const step = (dir) => {
    if (!results.length) return;
    const idx = results.findIndex((t) => t.id === playingId);
    const next = results[(idx + dir + results.length) % results.length];
    if (next) playTrack(next);
  };

  const playingTotal = duration || 0;

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
          {activeVibes.map((v) => (
            <span key={v} className="el-chip is-active ld-tag">
              {v}
              <button className="el-chip-remove" onClick={() => toggleVibe(v)} title="Remove">×</button>
            </span>
          ))}
          <input
            className="ld-tagger-input"
            placeholder={activeVibes.length ? '+ another vibe…' : 'Tag vibes or describe a mood…'}
            value={vibeQuery}
            onChange={(e) => setVibeQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && vibeQuery.trim()) {
                const pick = vibeSuggestions[0] || vibeQuery.trim();
                if (!activeVibes.includes(pick)) toggleVibe(pick);
                setVibeQuery('');
              } else if (e.key === 'Backspace' && !vibeQuery && activeVibes.length) {
                toggleVibe(activeVibes[activeVibes.length - 1]);
              }
            }}
          />
          <button
            className="ld-tagger-dice"
            title="Surprise me"
            onClick={() => {
              const pick = SUGGESTED_VIBES[Math.floor(Math.random() * SUGGESTED_VIBES.length)];
              if (!activeVibes.includes(pick)) toggleVibe(pick);
            }}
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

      {(vibeQuery || activeVibes.length === 0) && (
        <div className="ld-suggest-strip">
          <span className="lo-eyebrow">{vibeQuery ? `Matching “${vibeQuery}”` : 'Try a vibe'}</span>
          <div className="ld-suggest-list">
            {vibeSuggestions.map((v) => (
              <button key={v} className="el-chip" onClick={() => { toggleVibe(v); setVibeQuery(''); }}>+ {v}</button>
            ))}
            {vibeQuery && vibeSuggestions.length === 0 && (
              <button className="el-chip" onClick={() => { toggleVibe(vibeQuery.trim()); setVibeQuery(''); }}>
                + Add “{vibeQuery}” as custom vibe
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

          <div className="ld-trail-summary">
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 4 }}>
              <span className="lo-eyebrow-amber">Avg interpolation</span>
              <DistanceChip
                value={(() => {
                  const ds = trail.filter((s) => s.dist != null);
                  return ds.length ? ds.reduce((a, s) => a + s.dist, 0) / ds.length : 0;
                })()}
                kind="amber"
              />
            </div>
            <span className="lo-eyebrow">{trail.length} tracks</span>
          </div>

          <div className="la-trail-list lo-scroll">
            {trail.map((slot, i) => {
              const t = slot.track;
              if (!t) return null;
              const kindLabel = slot.kind === 'start' ? 'Start' : slot.kind === 'end' ? 'End' : `Step ${i}`;
              return (
                <React.Fragment key={slot.id}>
                  {i > 0 && <div className="la-trail-link" />}
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

          <button className="la-trail-generate" onClick={regenerate} disabled={trail.filter((s) => s.track).length < 2}>
            <span>↻</span> Regenerate playlist
          </button>
        </aside>

        {/* CENTER — MAP or LIST */}
        <section className="ld-center">
          <div className="ld-center-head">
            <div>
              <span className="lo-eyebrow">{view === 'map' ? 'Embedding space' : 'Results'}</span>
              <h2 className="el-h2" style={{ fontSize: '1.1rem' }}>
                {loading ? 'Searching…' : (
                  <>
                    {results.length} tracks{' '}
                    {mode.type === 'similar' ? <>similar to <em>{mode.track.title}</em></>
                      : mode.type === 'dissimilar' ? <>unlike <em>{mode.track.title}</em></>
                      : activeVibes.length ? <>matching <em>{activeVibes.join(' · ')}</em></>
                      : <em>across the catalog</em>}
                  </>
                )}
              </h2>
              {enhancedQuery && <div className="lo-eyebrow" style={{ marginTop: 2 }}>✨ {enhancedQuery}</div>}
            </div>
          </div>

          {view === 'map' ? (
            <div className="ld-map-wrap">
              <div className="lc-axis lc-axis-y">
                <span className="lo-eyebrow">↑ bright · energetic</span>
                <span className="lo-eyebrow">↓ dark · introspective</span>
              </div>
              <div className="lc-axis lc-axis-x">
                <span className="lo-eyebrow">← acoustic · organic</span>
                <span className="lo-eyebrow">electronic · synthetic →</span>
              </div>

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

                {/* dimmed backdrop field */}
                <g style={{ pointerEvents: 'none' }}>
                  {backdrop.map((p) => {
                    if (resultIds.has(p.id)) return null;
                    const pos = dotPos(p);
                    return <circle key={'bg_' + p.id} cx={pos.x} cy={pos.y} r={3} fill={dotColor(p)} opacity={0.16} />;
                  })}
                </g>

                {/* sonar rings on playing dot */}
                {playing && [50, 100, 160, 230].map((r, i) => {
                  const pos = dotPos(playing);
                  return <circle key={i} cx={pos.x} cy={pos.y} r={r} fill="none" stroke="var(--el-yellow-500)" strokeOpacity={[0.55, 0.35, 0.22, 0.12][i]} strokeWidth={1} />;
                })}

                {/* trail polyline + node rings */}
                {trail.length > 1 && (
                  <polyline
                    points={trail.filter((s) => s.track).map((s) => { const p = dotPos(s.track); return `${p.x},${p.y}`; }).join(' ')}
                    fill="none" stroke="var(--el-indigo-500)" strokeOpacity="0.45" strokeWidth="2" strokeDasharray="4 4" />
                )}
                {trail.filter((s) => s.track).map((s) => {
                  const p = dotPos(s.track);
                  return <circle key={'tr_' + s.id} cx={p.x} cy={p.y} r={11} fill="none" stroke="var(--el-indigo-500)" strokeWidth="2" strokeOpacity="0.6" />;
                })}

                {/* result dots (bright, interactive) */}
                {results.map((t) => {
                  const p = dotPos(t);
                  const isPlay = t.id === playingId;
                  const isSel = t.id === selectedId;
                  const isHov = t.id === hoverId;
                  const inTrail = trail.some((s) => s.track?.id === t.id);
                  const r = isPlay ? 9 : isSel ? 7 : 5;
                  return (
                    <g key={t.id}
                      onMouseEnter={() => setHoverId(t.id)}
                      onMouseLeave={() => setHoverId((prev) => (prev === t.id ? null : prev))}
                      onClick={() => setSelectedId(t.id)}
                      onDoubleClick={() => playTrack(t)}
                      style={{ cursor: 'pointer' }}>
                      {(isHov || isSel) && (
                        <circle cx={p.x} cy={p.y} r={r + 6} fill="none" stroke={isSel ? 'var(--el-indigo-500)' : 'rgba(255,255,255,0.3)'} strokeWidth="1.5" />
                      )}
                      <circle cx={p.x} cy={p.y} r={r} fill={dotColor(t)} opacity={inTrail ? 1 : 0.85}
                        style={{ filter: isPlay ? 'drop-shadow(0 0 8px rgba(99,102,241,0.7))' : 'none' }} />
                      {inTrail && <circle cx={p.x} cy={p.y} r={r + 3} fill="none" stroke="white" strokeWidth="1" />}
                    </g>
                  );
                })}

                {playing && (() => {
                  const p = dotPos(playing);
                  return (
                    <g transform={`translate(${p.x - 22} ${p.y - 50})`}>
                      <image href={`${ASSET}assets/logo.svg`} width="44" height="50" />
                    </g>
                  );
                })()}
              </svg>

              {(hover || selected) && (() => {
                const t = hover || selected;
                const [cx, cy] = coordsOf(t);
                return (
                  <div className="lc-dot-card" style={{ left: `${(cx * 100).toFixed(1)}%`, top: `${((1 - cy) * 100).toFixed(1)}%` }}>
                    <div className="lo-eyebrow-strong">
                      {hover ? 'Preview' : 'Selected'}
                      {playing && <span style={{ marginLeft: 8, color: 'var(--el-yellow-500)' }}>· {distBetween(playing, t).toFixed(2)} away</span>}
                    </div>
                    <div className="lc-dot-title">{t.title}</div>
                    <div className="lc-dot-sub">{t.artist} — {t.album}</div>
                    {!hover && selected && (
                      <div className="lc-dot-actions">
                        <button className="lo-btn-ghost" onClick={() => playTrack(t)}>▶ Play</button>
                        <button className="lo-btn-ghost" onClick={() => addToTrail(t)}>+ Trail</button>
                        <button className="lo-btn-ghost" onClick={() => setMode({ type: 'similar', track: t })}>≈ Similar</button>
                      </div>
                    )}
                  </div>
                );
              })()}

              <div className="lc-legend">
                <div className="lc-legend-row"><span className="lc-legend-dot" style={{ background: '#6366f1' }} /> introspective</div>
                <div className="lc-legend-row"><span className="lc-legend-dot" style={{ background: '#8b5cf6' }} /> electric</div>
                <div className="lc-legend-row"><span className="lc-legend-dot" style={{ background: '#a78bfa' }} /> textural</div>
                <div className="lc-legend-row"><span className="lc-legend-dot" style={{ background: '#fbbf24' }} /> kinetic</div>
                <div className="lc-legend-divider" />
                <div className="lc-legend-row">
                  <svg width="22" height="6"><line x1="0" y1="3" x2="22" y2="3" stroke="var(--el-indigo-500)" strokeWidth="2" strokeDasharray="4 3" /></svg>
                  your trail
                </div>
              </div>
            </div>
          ) : (
            <div className="ld-list lo-scroll">
              {results.map((t, i) => {
                const inTrail = trail.some((s) => s.track?.id === t.id);
                const isPlay = playingId === t.id;
                return (
                  <div key={t.id}
                    className={'lo-track ld-track ' + (isPlay ? 'is-playing ' : '')}
                    onClick={() => { setSelectedId(t.id); playTrack(t); }}>
                    <span className="lo-track-num">{(i + 1).toString().padStart(2, '0')}</span>
                    <span className="ld-dot-inline" style={{ background: dotColor(t) }} />
                    <button className="lo-track-play" title="Play" onClick={(e) => { e.stopPropagation(); playTrack(t); }}>▶</button>
                    <div className="lo-track-info">
                      <div className="lo-track-title">{t.title}</div>
                      <div className="lo-track-sub">{t.artist} — {t.album}</div>
                    </div>
                    <DistanceChip value={distChipValue(t)} />
                    <div className="lo-track-actions">
                      <button className="lo-act-btn" title="Find similar" onClick={(e) => { e.stopPropagation(); setMode({ type: 'similar', track: t }); }}>≈</button>
                      <button className="lo-act-btn" title="Find dissimilar" onClick={(e) => { e.stopPropagation(); setMode({ type: 'dissimilar', track: t }); }}>≠</button>
                      <button className={'lo-act-btn ' + (inTrail ? 'is-active' : '')} title={inTrail ? 'In your trail' : 'Add to trail'}
                        onClick={(e) => { e.stopPropagation(); addToTrail(t); }}>{inTrail ? '✓' : '+'}</button>
                    </div>
                  </div>
                );
              })}
              {!loading && results.length === 0 && <div className="lo-eyebrow" style={{ padding: 16 }}>No results.</div>}
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

          <div className="la-now-actions">
            <button className="lo-btn-ghost" onClick={() => playing && setMode({ type: 'similar', track: playing })}>
              <span style={{ marginRight: 6 }}>≈</span> Similar to this
            </button>
            <button className="lo-btn-ghost" onClick={() => addToTrail(playing)}>
              <span style={{ marginRight: 6 }}>+</span> Add to trail
            </button>
          </div>
        </aside>
      </main>
    </div>
  );
}

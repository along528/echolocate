// Sonar — mobile (map-first) view. Immersive full-bleed portrait sonar map with
// floating glass chrome and bottom sheets for search, track detail, now-playing,
// and the playlist builder. Ported from the design handoff prototype
// (layout-d-mobile.jsx) and rewired to the shared useSonar hook (passed as `s`)
// so it drives the exact same state, services, and audio element as the desktop
// view. Ships the desktop dot model (layer colors); the prototype's mock-only
// sonic / clusters / axes variations are intentionally omitted.
import React from 'react';
import { Wordmark, Waveform } from './svg-bits.jsx';
import {
  IconSearch, IconListPlus, IconCheck, IconPlus, IconSimilar, IconDissimilar,
  IconEye, IconEyeOff, IconClose, IconExternal, IconUp, IconDown,
  IconZoomIn, IconZoomOut,
} from './icons.jsx';
import {
  CANDIDATE_COLOR, fmtTime, coordsOf, distBetween,
  layerTag, layerKindWord, prettyUrl, FeedbackPills,
} from './sonar-utils.jsx';

const MVW = 390, MVH = 780, MPAD = 46;
const ASSET = import.meta.env.BASE_URL;

function dotPosM(t) {
  const [cx, cy] = coordsOf(t);
  return { x: MPAD + cx * (MVW - 2 * MPAD), y: MPAD + (1 - cy) * (MVH - 2 * MPAD) };
}

// A bottom sheet whose grab handle can be dragged down to dismiss. A drag past
// ~90px (or a quick flick) closes it; anything less snaps back. The handle's
// grip area sets touch-action:none so the drag never scrolls the page; the
// sheet body keeps its own scroll. Tapping the scrim still closes it too.
function Sheet({ onClose, style, className = '', children }) {
  const [dragY, setDragY] = React.useState(0);
  const [dragging, setDragging] = React.useState(false);
  const startRef = React.useRef(null);
  const onStart = (e) => { startRef.current = { y: e.touches[0].clientY, t: Date.now() }; setDragging(true); setDragY(0); };
  const onMove = (e) => { const s = startRef.current; if (!s) return; const dy = e.touches[0].clientY - s.y; setDragY(dy > 0 ? dy : 0); };
  const onEnd = () => {
    const s = startRef.current; if (!s) return;
    const dt = Date.now() - s.t, dy = dragY;
    startRef.current = null; setDragging(false);
    if (dy > 90 || (dt > 0 && dy / dt > 0.5 && dy > 30)) onClose();
    else setDragY(0);
  };
  return (
    <div className={'ldm-sheet ' + className}
      style={{ ...style, transform: dragY ? `translateY(${dragY}px)` : undefined, transition: dragging ? 'none' : 'transform 0.2s ease' }}>
      <div className="ldm-grip" onTouchStart={onStart} onTouchMove={onMove} onTouchEnd={onEnd} onTouchCancel={onEnd}>
        <div className="ldm-handle" />
      </div>
      {children}
    </div>
  );
}

export default function SonarMobile({ s }) {
  const {
    view, setView, vibeQuery, setVibeQuery,
    layers, playingId, isPlaying, progress, selectedId, setSelectedId,
    candidates, labelsByTrackId, soloLayerId, zoom, setZoom,
    addVibeLayer, addSeedLayer, removeLayer, toggleLayerVisible, toggleSolo,
    visibleLayers, visibleTracks, entryByTrackId, playlistById, playlist,
    playing, selected, playlistTracks, playingTotal, vibeSuggestions, isCandidate,
    addToPlaylist, insertCandidate, removeFromPlaylist, movePlaylist, clearPlaylist,
    interpolateEdge, playTrack, togglePlay, step, labelTrack,
  } = s;

  // Mobile-only UI state: which bottom sheet is open (one at a time).
  const [sheet, setSheet] = React.useState(null);
  // Height of the on-screen keyboard while the search sheet is focused, so the
  // sheet can be pinned above it instead of being scrolled off-screen.
  const [kbInset, setKbInset] = React.useState(0);

  // Latest zoom in a ref so the touch handlers never read a stale closure.
  const zoomRef = React.useRef(zoom);
  zoomRef.current = zoom;
  // Active touch gesture (pan / pinch) bookkeeping, and a flag that a drag
  // actually moved — so a drag that starts on a dot doesn't also tap it.
  const gestureRef = React.useRef(null);
  const movedRef = React.useRef(false);

  // Composition wrappers over shared handlers.
  const openDetail = (id) => { setSelectedId(id); setSheet('detail'); };
  const onInterpolate = (a, b) => { interpolateEdge(a, b); setSheet(null); setView('map'); };
  // Run a map tap action unless the touch was actually a drag (pan/pinch).
  const onTap = (fn) => (e) => { e.stopPropagation(); if (movedRef.current) return; fn(); };

  // Mobile zoom — centered on the portrait canvas, clamped k ∈ [0.3, 5] (can
  // zoom out past the plot since the grid now extends to infinity).
  const ZK_MIN = 0.3, ZK_MAX = 5;
  const zoomBy = (f) => setZoom((z) => {
    const k = Math.max(ZK_MIN, Math.min(ZK_MAX, z.k * f));
    const cx = MVW / 2, cy = MVH / 2;
    return { k, x: cx - (cx - z.x) * (k / z.k), y: cy - (cy - z.y) * (k / z.k) };
  });

  // ---- touch: one-finger pan, two-finger pinch zoom (k ∈ [1, 5]) ----
  // The SVG uses preserveAspectRatio="slice", so screen↔viewBox needs the cover
  // scale S = max(W/MVW, H/MVH) and the centering offsets. (.ldm-map sets
  // touch-action:none, so the browser won't scroll/zoom and we needn't
  // preventDefault — which keeps React's passive touch listeners happy.)
  const rectMetrics = (rect) => {
    const S = Math.max(rect.width / MVW, rect.height / MVH);
    return { S, offX: (rect.width - S * MVW) / 2, offY: (rect.height - S * MVH) / 2 };
  };
  const onTouchStart = (e) => {
    const t = e.touches;
    const rect = e.currentTarget.getBoundingClientRect();
    movedRef.current = false;
    if (t.length === 1) {
      gestureRef.current = { mode: 'pan', x: t[0].clientX, y: t[0].clientY, z0: { ...zoomRef.current }, rect };
    } else if (t.length === 2) {
      const dist = Math.hypot(t[0].clientX - t[1].clientX, t[0].clientY - t[1].clientY);
      gestureRef.current = { mode: 'pinch', dist, z0: { ...zoomRef.current }, rect };
      movedRef.current = true;
    }
  };
  const onTouchMove = (e) => {
    const g = gestureRef.current;
    if (!g) return;
    const t = e.touches;
    const { S, offX, offY } = rectMetrics(g.rect);
    if (g.mode === 'pan' && t.length === 1) {
      const dxs = t[0].clientX - g.x, dys = t[0].clientY - g.y;
      if (!movedRef.current && Math.hypot(dxs, dys) > 4) movedRef.current = true;
      if (movedRef.current) setZoom({ k: g.z0.k, x: g.z0.x + dxs / S, y: g.z0.y + dys / S });
    } else if (g.mode === 'pinch' && t.length === 2) {
      const dist = Math.hypot(t[0].clientX - t[1].clientX, t[0].clientY - t[1].clientY);
      const kNew = Math.max(ZK_MIN, Math.min(ZK_MAX, g.z0.k * (dist / (g.dist || dist))));
      // Keep the point under the pinch midpoint fixed while scaling.
      const mx = (t[0].clientX + t[1].clientX) / 2 - g.rect.left;
      const my = (t[0].clientY + t[1].clientY) / 2 - g.rect.top;
      const vbx = (mx - offX) / S, vby = (my - offY) / S;
      const ratio = kNew / g.z0.k;
      setZoom({ k: kNew, x: vbx * (1 - ratio) + g.z0.x * ratio, y: vby * (1 - ratio) + g.z0.y * ratio });
    }
  };
  const onTouchEnd = (e) => {
    if (e.touches.length === 0) { gestureRef.current = null; return; }
    // Lifting one finger of a pinch → continue as a pan with the remaining one.
    if (e.touches.length === 1) {
      gestureRef.current = { mode: 'pan', x: e.touches[0].clientX, y: e.touches[0].clientY, z0: { ...zoomRef.current }, rect: e.currentTarget.getBoundingClientRect() };
    }
  };

  // Track the keyboard height (visualViewport) only while the search sheet is up.
  React.useEffect(() => {
    if (sheet !== 'search' || !window.visualViewport) { setKbInset(0); return undefined; }
    const vv = window.visualViewport;
    const update = () => setKbInset(Math.max(0, window.innerHeight - vv.height - vv.offsetTop));
    update();
    vv.addEventListener('resize', update);
    vv.addEventListener('scroll', update);
    return () => { vv.removeEventListener('resize', update); vv.removeEventListener('scroll', update); };
  }, [sheet]);

  // Focus the search input WITHOUT letting the browser scroll it into view —
  // that scroll (esp. with autoFocus) is what shoved the sheet off the top when
  // the keyboard opened. We keep the sheet pinned above the keyboard instead.
  const searchInputRef = React.useRef(null);
  React.useEffect(() => {
    if (sheet !== 'search') return undefined;
    const id = setTimeout(() => { try { searchInputRef.current?.focus({ preventScroll: true }); } catch { searchInputRef.current?.focus(); } }, 60);
    return () => clearTimeout(id);
  }, [sheet]);

  return (
    <div className="ldm-app">
      {/* ===== MAP / LIST STAGE ===== */}
      {view === 'map' ? (
        <div className="ldm-stage">
          <svg className="ldm-map" viewBox={`0 0 ${MVW} ${MVH}`} preserveAspectRatio="xMidYMid slice"
            onClick={() => { if (!movedRef.current && sheet) setSheet(null); }}
            onTouchStart={onTouchStart} onTouchMove={onTouchMove} onTouchEnd={onTouchEnd} onTouchCancel={onTouchEnd}>
            <rect x={0} y={0} width={MVW} height={MVH} fill="transparent" />
            <defs>
              <pattern id="ldm-grid" width="74.5" height="74.5" patternUnits="userSpaceOnUse">
                <path d="M 74.5 0 L 0 0 0 74.5" fill="none" stroke="white" strokeOpacity="0.14" strokeWidth="0.6" />
              </pattern>
            </defs>
            <g transform={`translate(${zoom.x} ${zoom.y}) scale(${zoom.k})`}>
              {/* Effectively-infinite grid: a huge rect tiled with the grid
                  pattern, so panning / zooming out never reveals an edge. */}
              <rect x={-6000} y={-6000} width={12000} height={12000} fill="url(#ldm-grid)" style={{ pointerEvents: 'none' }} />
              {playing && [44, 90, 150, 220].map((r, i) => { const p = dotPosM(playing); return <circle key={i} cx={p.x} cy={p.y} r={r} fill="none" stroke="var(--el-yellow-500)" strokeOpacity={[0.55, 0.35, 0.22, 0.12][i]} strokeWidth={1} style={{ pointerEvents: 'none' }} />; })}
              {playlistTracks.length > 1 && playlistTracks.slice(1).map((b, i) => { const a = playlistTracks[i], pa = dotPosM(a), pb = dotPosM(b); const active = candidates && ((candidates.aId === a.id && candidates.bId === b.id) || (candidates.aId === b.id && candidates.bId === a.id)); const mx = (pa.x + pb.x) / 2, my = (pa.y + pb.y) / 2;
                return (<g key={`s${a.id}${b.id}`} onClick={onTap(() => onInterpolate(a, b))}><line x1={pa.x} y1={pa.y} x2={pb.x} y2={pb.y} stroke="transparent" strokeWidth="20" /><line x1={pa.x} y1={pa.y} x2={pb.x} y2={pb.y} stroke="var(--el-indigo-500)" strokeOpacity={active ? 0.95 : 0.55} strokeWidth={active ? 3 : 2} strokeDasharray="4 4" /><circle cx={mx} cy={my} r={11} fill="var(--el-bg-secondary)" stroke="var(--el-indigo-500)" strokeWidth="1.5" /><path d={`M${mx - 5} ${my} h10 M${mx} ${my - 5} v10`} stroke="var(--el-indigo-500)" strokeWidth="1.5" strokeLinecap="round" /></g>); })}
              {playlistTracks.map((t) => { const p = dotPosM(t); return <circle key={'r' + t.id} cx={p.x} cy={p.y} r={13} fill="none" stroke="var(--el-indigo-500)" strokeWidth="2" strokeOpacity="0.6" style={{ pointerEvents: 'none' }} />; })}
              {visibleTracks.map(({ track: t, color }) => { const p = dotPosM(t), isPlay = t.id === playingId, isSel = t.id === selectedId, inPl = playlistById.has(t.id); const r = isPlay ? 11 : isSel ? 9 : 7;
                return (<g key={t.id} onClick={onTap(() => openDetail(t.id))}>
                  {isSel && <circle cx={p.x} cy={p.y} r={r + 7} fill="none" stroke={color} strokeWidth="1.5" />}
                  <circle cx={p.x} cy={p.y} r={r} fill={color} opacity={inPl ? 1 : 0.88} style={{ filter: isPlay ? `drop-shadow(0 0 8px ${color})` : 'none' }} />
                  {inPl && <circle cx={p.x} cy={p.y} r={r + 3} fill="none" stroke="white" strokeWidth="1" />}
                </g>); })}
              {candidates && candidates.tracks.map((t) => { if (entryByTrackId.has(t.id)) return null; const p = dotPosM(t);
                return (<g key={'c' + t.id} onClick={onTap(() => openDetail(t.id))}><circle cx={p.x} cy={p.y} r={12} fill="none" stroke={CANDIDATE_COLOR} strokeWidth="1.2" strokeOpacity="0.7" strokeDasharray="3 2" /><circle cx={p.x} cy={p.y} r={6} fill={CANDIDATE_COLOR} opacity="0.9" /></g>); })}
            </g>
          </svg>

          <div className="ldm-caption">MERT embeddings</div>
          {visibleLayers.length > 0 && (
            <div className="ldm-legend">
              {visibleLayers.slice(0, 5).map((l) => (<div key={l.id} className="ldm-legend-row"><span className="ldm-legend-dot" style={{ background: l.color }} />{layerTag(l)}</div>))}
            </div>
          )}
        </div>
      ) : (
        <div className="ldm-listview">
          {visibleTracks.map(({ track: t, color, sources }) => { const inPl = playlistById.has(t.id), isPlay = playingId === t.id;
            return (<div key={t.id} className={'ldm-row ' + (isPlay ? 'is-playing' : '')} onClick={() => playTrack(t)}>
              <span className="ldm-row-dot" style={{ background: color }} />
              <div className="ldm-row-info"><div className="ldm-row-title">{t.title}</div><div className="ldm-row-sub">{t.artist} · {sources.map(layerTag).join(', ')}</div></div>
              <button className={'ldm-row-add ' + (inPl ? 'is-active' : '')} onClick={(e) => { e.stopPropagation(); addToPlaylist(t); }}>{inPl ? <IconCheck size={16} /> : <IconListPlus size={16} />}</button>
            </div>); })}
          {visibleTracks.length === 0 && <div className="ldm-onboard-eyebrow" style={{ textAlign: 'center', marginTop: 40 }}>No results yet. Add a vibe to start.</div>}
        </div>
      )}

      {/* ===== TOP CHROME ===== */}
      <div className="ldm-top">
        <div className="ldm-brand"><Wordmark size="lg" /></div>
        <div className="ldm-top-row">
          <button className="ldm-search" onClick={() => setSheet('search')}><IconSearch size={15} /><span>{layers.length ? `${layers.length} ${layers.length === 1 ? 'search' : 'searches'} active` : 'Tag vibes or describe a mood…'}</span></button>
          <div className="ldm-seg">
            <button className={'ldm-seg-btn ' + (view === 'map' ? 'is-active' : '')} onClick={() => setView('map')}><svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor"><circle cx="12" cy="12" r="2.5" /><circle cx="12" cy="12" r="6" fill="none" stroke="currentColor" strokeWidth="1.4" /><circle cx="12" cy="12" r="10" fill="none" stroke="currentColor" strokeWidth="1.4" opacity="0.5" /></svg></button>
            <button className={'ldm-seg-btn ' + (view === 'list' ? 'is-active' : '')} onClick={() => setView('list')}><svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor"><rect x="3" y="5" width="18" height="2" rx="1" /><rect x="3" y="11" width="18" height="2" rx="1" /><rect x="3" y="17" width="18" height="2" rx="1" /></svg></button>
          </div>
        </div>
        {layers.length > 0 && (
          <div className="ldm-chips">
            {layers.map((l) => (
              <span key={l.id} className={'ldm-chip ' + (l.visible ? '' : 'is-hidden ') + (soloLayerId === l.id ? 'is-solo' : '')} style={{ borderColor: l.color }} onClick={() => toggleSolo(l.id)}>
                <span className="ldm-chip-swatch" style={{ background: l.color }} />{layerTag(l)}
                <button className="ldm-chip-x" onClick={(e) => { e.stopPropagation(); removeLayer(l.id); }}>×</button>
              </span>
            ))}
            <button className="ldm-chip ldm-chip-add" onClick={() => setSheet('search')}><IconPlus size={13} /> add</button>
          </div>
        )}
      </div>

      {/* ===== BOTTOM CHROME ===== */}
      <div className="ldm-bottom">
        <div className="ldm-fab-row">
          {view === 'map' && (
            <div className="ldm-zoombtns">
              <button className="lo-btn-icon" onClick={() => zoomBy(1.3)}><IconZoomIn size={16} /></button>
              <button className="lo-btn-icon" onClick={() => zoomBy(1 / 1.3)}><IconZoomOut size={16} /></button>
            </div>
          )}
          <button className="ldm-fab" onClick={() => setSheet('playlist')} style={{ marginLeft: 'auto' }}>
            <IconListPlus size={16} /> Playlist <span className="ldm-fab-badge">{playlistTracks.length}</span>
          </button>
        </div>
        {playing && (
          <div className="ldm-player" style={{ position: 'relative' }} onClick={() => setSheet('now')}>
            <div className="ldm-player-art"><img src={`${ASSET}assets/artwork.svg`} alt="" /></div>
            <div className="ldm-player-info"><div className="ldm-player-title">{playing.title}</div><div className="ldm-player-sub">{playing.artist}</div></div>
            <button className="ldm-player-play" onClick={(e) => { e.stopPropagation(); togglePlay(); }}>{isPlaying ? <svg viewBox="0 0 24 24" fill="white" width="16" height="16"><path d="M6 5h4v14H6zm8 0h4v14h-4z" /></svg> : <svg viewBox="0 0 24 24" fill="white" width="16" height="16"><path d="M8 5v14l11-7z" /></svg>}</button>
            <div className="ldm-player-prog"><span style={{ width: `${progress * 100}%` }} /></div>
          </div>
        )}
      </div>

      {/* ===== SHEETS ===== */}
      {sheet && <div className="ldm-scrim" onClick={() => setSheet(null)} />}

      {sheet === 'search' && (
        <Sheet onClose={() => setSheet(null)} style={{ maxHeight: kbInset ? `${Math.max(240, window.innerHeight - kbInset - 56)}px` : '70%', bottom: kbInset }}>
          <input ref={searchInputRef} className="ldm-sheet-input" placeholder="Describe a mood…" value={vibeQuery}
            onChange={(e) => setVibeQuery(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter' && vibeQuery.trim()) { addVibeLayer(vibeQuery.trim()); setVibeQuery(''); } }} />
          <div className="ldm-sheet-scroll">
            <div className="lo-eyebrow" style={{ marginBottom: 8 }}>{vibeQuery ? `Matching “${vibeQuery}”` : 'Suggested vibes'}</div>
            <div className="ldm-chipwrap">
              {vibeSuggestions.map((v) => (
                <button key={v} className="el-chip" onClick={() => { addVibeLayer(v); setVibeQuery(''); }}>+ {v}</button>
              ))}
              {vibeQuery && !vibeSuggestions.some((v) => v.toLowerCase() === vibeQuery.toLowerCase()) && (
                <button className="el-chip" onClick={() => { addVibeLayer(vibeQuery.trim()); setVibeQuery(''); }}>+ Add “{vibeQuery}”</button>
              )}
            </div>
            {layers.length > 0 && (<>
              <div className="lo-eyebrow" style={{ margin: '18px 0 8px' }}>Active searches</div>
              <div className="ldm-layer-manage">
                {layers.map((l) => (
                  <div key={l.id} className="ldm-layer-manage-row">
                    <span className="ldm-chip-swatch" style={{ background: l.color, width: 10, height: 10 }} />
                    <span className="ldm-lm-label">{layerKindWord(l)} · {l.label}{l.enhancedQuery ? ' ✨' : ''}</span>
                    <button className="ldm-lm-btn" onClick={() => toggleLayerVisible(l.id)} style={l.visible ? null : { opacity: 0.5 }}>{l.visible ? <IconEye size={15} /> : <IconEyeOff size={15} />}</button>
                    <button className="ldm-lm-btn" onClick={() => removeLayer(l.id)}><IconClose size={13} /></button>
                  </div>
                ))}
              </div>
            </>)}
          </div>
        </Sheet>
      )}

      {sheet === 'detail' && selected && (() => { const t = selected; const cand = isCandidate(t.id); const sources = entryByTrackId.get(t.id)?.sources || []; const inPl = playlistById.has(t.id);
        return (
          <Sheet onClose={() => setSheet(null)}>
            <div className="ldm-detail-sources">
              {cand && <span className="lc-source-tag" style={{ borderColor: CANDIDATE_COLOR, color: CANDIDATE_COLOR }}>interpolation</span>}
              {sources.map((l) => (<span key={l.id} className="lc-source-tag" style={{ borderColor: l.color, color: l.color }}><span className="ld-layer-swatch" style={{ background: l.color }} />{layerTag(l)}</span>))}
              {playing && playing.id !== t.id && <span className="ld-detail-dist" style={{ marginLeft: 'auto' }}>{distBetween(playing, t).toFixed(2)} away</span>}
            </div>
            <div className="ldm-detail-title">{t.title}</div>
            <div className="ldm-detail-sub">{t.artist} — {t.album}</div>
            {t.track_url && (
              <a className="ld-detail-url" href={t.track_url} target="_blank" rel="noopener noreferrer" style={{ marginTop: 6 }}><IconExternal size={12} />{prettyUrl(t.track_url)}</a>
            )}
            <div className="ldm-detail-fb"><FeedbackPills track={t} value={labelsByTrackId[t.id]} onLabel={labelTrack} /></div>
            <div className="ldm-detail-actions">
              <button className="ldm-act is-primary" onClick={() => { playTrack(t); setSheet('now'); }}><svg viewBox="0 0 24 24" fill="currentColor" width="18" height="18"><path d="M8 5v14l11-7z" /></svg> Play</button>
              <button className="ldm-act" onClick={() => (cand ? insertCandidate(t) : addToPlaylist(t))}>{inPl ? <IconCheck size={16} /> : <IconListPlus size={16} />} {inPl ? 'In playlist' : 'Add'}</button>
              <button className="ldm-act" onClick={() => { addSeedLayer('similar', t); setSheet(null); }}><IconSimilar size={16} /> Similar</button>
              <button className="ldm-act" onClick={() => { addSeedLayer('dissimilar', t); setSheet(null); }}><IconDissimilar size={16} /> Dissimilar</button>
            </div>
          </Sheet>
        ); })()}

      {sheet === 'now' && playing && (
        <Sheet onClose={() => setSheet(null)} style={{ maxHeight: '92%' }}>
          <div className="ldm-sheet-scroll">
            <div className="ldm-now-art"><img src={`${ASSET}assets/artwork.svg`} alt="" /></div>
            <div className="lo-eyebrow-strong">Now playing</div>
            <div className="ldm-now-title">{playing.title}</div>
            <div className="ldm-now-sub">{playing.artist} — {playing.album}</div>
            <div style={{ marginTop: 14 }}><Waveform width={350} height={40} progress={progress} bars={56} seed={(playingId || 'x').charCodeAt(0) + 3} /></div>
            <div className="ldm-now-times"><span>{fmtTime(playingTotal * progress)}</span><span>{fmtTime(playingTotal)}</span></div>
            <div className="ldm-now-transport">
              <button className="ldm-now-tbtn" onClick={() => step(-1)}><svg viewBox="0 0 24 24" fill="currentColor" width="18" height="18"><path d="M6 6h2v12H6zm3.5 6l8.5 6V6z" /></svg></button>
              <button className="ldm-now-tbtn is-play" onClick={togglePlay}>{isPlaying ? <svg viewBox="0 0 24 24" fill="white" width="22" height="22"><path d="M6 5h4v14H6zm8 0h4v14h-4z" /></svg> : <svg viewBox="0 0 24 24" fill="white" width="22" height="22"><path d="M8 5v14l11-7z" /></svg>}</button>
              <button className="ldm-now-tbtn" onClick={() => step(1)}><svg viewBox="0 0 24 24" fill="currentColor" width="18" height="18"><path d="M6 18l8.5-6L6 6v12zM16 6v12h2V6h-2z" /></svg></button>
            </div>
            <div className="ldm-detail-fb"><FeedbackPills track={playing} value={labelsByTrackId[playing.id]} onLabel={labelTrack} /></div>
          </div>
          {/* Pinned below the scroll so these always stay on-screen. */}
          <div className="ldm-now-quick">
            <button className="ldm-act" onClick={() => { addSeedLayer('similar', playing); setSheet(null); }}><IconSimilar size={18} /> Similar</button>
            <button className="ldm-act" onClick={() => { addSeedLayer('dissimilar', playing); setSheet(null); }}><IconDissimilar size={18} /> Dissimilar</button>
            <button className="ldm-act" onClick={() => addToPlaylist(playing)}><IconListPlus size={18} /> Add</button>
          </div>
        </Sheet>
      )}

      {sheet === 'playlist' && (
        <Sheet onClose={() => setSheet(null)}>
          <div className="ldm-sheet-head">
            <h3 className="el-h2" style={{ fontSize: '1.2rem' }}>Your playlist</h3>
            <button className="lo-btn-ghost ld-mini-btn" onClick={clearPlaylist}>Clear</button>
          </div>
          <div className="ldm-onboard-eyebrow" style={{ marginBottom: 10 }}>{playlistTracks.length > 1 ? 'Tap a link between two tracks to find tracks in between.' : 'Add tracks, then tap between them to interpolate.'}</div>
          <div className="ldm-sheet-scroll">
            <div className="ldm-pl-list">
              {playlist.map((slot, i) => { const t = slot.track; if (!t) return null; const prev = playlist[i - 1]?.track; const active = candidates && prev && ((candidates.aId === prev.id && candidates.bId === t.id) || (candidates.aId === t.id && candidates.bId === prev.id));
                return (<React.Fragment key={slot.id}>
                  {i > 0 && prev && <button className={'ldm-pl-link ' + (active ? 'is-active' : '')} onClick={() => onInterpolate(prev, t)}><IconPlus size={12} /> find in between</button>}
                  <div className={'ldm-pl-card ' + (playingId === t.id ? 'is-playing' : '')}>
                    <span className="ldm-pl-dot" style={{ background: slot.color || 'var(--el-indigo-500)' }} />
                    <div className="ldm-pl-info" onClick={() => playTrack(t)}><div className="ldm-pl-title">{t.title}</div><div className="ldm-pl-sub">{t.artist}{slot.dist != null ? ` · ${slot.dist.toFixed(2)} step` : ''}</div></div>
                    <div className="ldm-pl-ctl">
                      <button className="ldm-lm-btn" disabled={i === 0} onClick={() => movePlaylist(slot.id, -1)} style={i === 0 ? { opacity: 0.3 } : null}><IconUp size={14} /></button>
                      <button className="ldm-lm-btn" disabled={i === playlist.length - 1} onClick={() => movePlaylist(slot.id, 1)} style={i === playlist.length - 1 ? { opacity: 0.3 } : null}><IconDown size={14} /></button>
                      <button className="ldm-lm-btn" onClick={() => removeFromPlaylist(slot.id)}><IconClose size={13} /></button>
                    </div>
                  </div>
                </React.Fragment>); })}
              {playlist.length === 0 && <div className="ldm-onboard-eyebrow" style={{ textAlign: 'center', padding: '24px 0' }}>No tracks yet. Tap a dot on the map, then “Add”.</div>}
            </div>
            {candidates && candidates.tracks.length > 0 && (<>
              <div className="lo-eyebrow" style={{ margin: '16px 0 8px' }}>Tracks in between</div>
              {candidates.tracks.map((t) => (
                <div key={t.id} className="ldm-pl-card" style={{ marginBottom: 6 }}>
                  <span className="ldm-pl-dot" style={{ background: CANDIDATE_COLOR }} />
                  <div className="ldm-pl-info"><div className="ldm-pl-title">{t.title}</div><div className="ldm-pl-sub">{t.artist}</div></div>
                  <button className="ldm-lm-btn" onClick={() => insertCandidate(t)}><IconPlus size={15} /></button>
                </div>
              ))}
            </>)}
          </div>
        </Sheet>
      )}
    </div>
  );
}

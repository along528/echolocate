// Sonar — desktop view. The landscape "sonar map + list" layout: top tagger bar,
// suggestion strip, left playlist rail, center map/list, right now-playing rail,
// and the About modal. All state/logic comes from the shared useSonar hook
// (passed in as `s`); this component owns only the desktop map geometry
// (760×540 landscape) and its pan / zoom / nearest-track interactions.
import React from 'react';
import { Wordmark, Waveform, DistanceChip } from './svg-bits.jsx';
import {
  IconListPlus, IconSimilar, IconDissimilar, IconCheck, IconClose,
  IconExternal, IconEye, IconEyeOff, IconUp, IconDown, IconPlus,
  IconZoomIn, IconZoomOut, IconRecenter, IconInfo,
} from './icons.jsx';
import {
  CANDIDATE_COLOR, FALLBACK_COLOR, fmtTime, coordsOf, distBetween, distChipValue,
  layerTag, layerKindWord, prettyUrl, FeedbackPills, SourceLink,
} from './sonar-utils.jsx';

const VW = 760;
const VH = 540;
// Inner plot margin (was 60 — shrunk so the graph fills more of the canvas).
const PAD = 26;
const ASSET = import.meta.env.BASE_URL;

// SVG position. x: left -> right. y: high values at top.
function dotPos(t) {
  const [cx, cy] = coordsOf(t);
  return { x: PAD + cx * (VW - 2 * PAD), y: PAD + (1 - cy) * (VH - 2 * PAD) };
}

export default function SonarDesktop({ s }) {
  const {
    view, setView, vibeQuery, setVibeQuery, suggestions, aboutOpen, setAboutOpen,
    layers, playingId, hoverId, setHoverId, selectedId, setSelectedId,
    isPlaying, progress, playlist, candidates, labelsByTrackId, soloLayerId,
    zoom, setZoom,
    addVibeLayer, addSeedLayer, restoreLayer, removeLayer, clearLayers,
    toggleLayerVisible, toggleSolo, showAllLayers,
    visibleLayers, anyLoading, allVisible, visibleTracks, entryByTrackId,
    playlistById, playing, selected, flatResults, vibeSuggestions, playlistTracks,
    navSource, detail, detailPinned, isCandidate, playingTotal,
    addToPlaylist, insertCandidate, removeFromPlaylist, movePlaylist, clearPlaylist,
    dragId, dropIdx, onDragStartSlot, onDragOverCard, onDragEndSlot, onDropSlot,
    interpolateEdge, clearCandidates,
    playTrack, togglePlay, seekTo, step, labelTrack, resetZoom,
  } = s;

  // Pan drag bookkeeping (click-drag to pan when zoomed in).
  const panRef = React.useRef(null); // { sx, sy, ox, oy } during a drag
  const didPanRef = React.useRef(false); // set true once a drag actually moves

  const onLayerKeyDown = (e) => {
    if (e.key === 'Enter' && vibeQuery.trim()) {
      // Add the *typed* text — suggestions are never auto-selected.
      addVibeLayer(vibeQuery.trim());
      setVibeQuery('');
    } else if (e.key === 'Backspace' && !vibeQuery && layers.length) {
      removeLayer(layers[layers.length - 1].id);
    }
  };

  // ---- map zoom / pan ----
  const zoomBy = (factor) => setZoom((z) => {
    const k = Math.max(1, Math.min(8, z.k * factor));
    // keep the plot centered while zooming
    const cx = VW / 2, cy = VH / 2;
    return { k, x: cx - (cx - z.x) * (k / z.k), y: cy - (cy - z.y) * (k / z.k) };
  });
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
  const onMapPointerUp = () => {
    panRef.current = null;
    // The click that follows mouseup fires synchronously (before this timeout),
    // so onMapBackgroundClick still sees didPanRef and swallows it. Clearing it
    // afterwards prevents a drag that ends without a click (e.g. released over a
    // child, or while zoomed then zoomed back out) from wedging the flag true
    // and swallowing the next legitimate background click.
    if (didPanRef.current) setTimeout(() => { didPanRef.current = false; }, 0);
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

          <div className="la-trail-list lo-scroll"
            onDragOver={(e) => { if (dragId.current) e.preventDefault(); }}
            onDrop={onDropSlot}>
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
                  {dropIdx === i && <div className="la-trail-drop" aria-hidden="true" />}
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
                    className={'la-trail-card ' + (playingId === t.id ? 'is-playing ' : '')}
                    draggable
                    onDragStart={(e) => onDragStartSlot(e, slot.id)}
                    onDragOver={(e) => onDragOverCard(e, i)}
                    onDragEnd={onDragEndSlot}
                    onDrop={onDropSlot}
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
            {dropIdx === playlist.length && playlist.length > 0 && <div className="la-trail-drop" aria-hidden="true" />}
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
              {/* Call as a function (not <DetailCard/>) so it doesn't remount on
                  every re-render — remounting resets button :hover and makes the
                  action buttons flicker as the mouse moves over the map. */}
                {detail
                ? DetailCard({ t: detail, pinned: detailPinned })
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
                        onDoubleClick={(e) => { e.stopPropagation(); addToPlaylist(t); }}
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
                        onDoubleClick={(e) => { e.stopPropagation(); addToPlaylist(t); }}
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
                        onDoubleClick={(e) => { e.stopPropagation(); insertCandidate(t); }}
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
              <button className="lo-now-btn" title="Previous (←)" onClick={() => step(-1)}>
                <svg viewBox="0 0 24 24" fill="currentColor" width="16" height="16"><path d="M6 6h2v12H6zm3.5 6l8.5 6V6z" /></svg>
              </button>
              <button className="lo-now-btn is-play" title={isPlaying ? 'Pause (Space)' : 'Play (Space)'} onClick={togglePlay}>
                {isPlaying
                  ? <svg viewBox="0 0 24 24" fill="white" width="18" height="18"><path d="M6 5h4v14H6zm8 0h4v14h-4z" /></svg>
                  : <svg viewBox="0 0 24 24" fill="white" width="18" height="18"><path d="M8 5v14l11-7z" /></svg>}
              </button>
              <button className="lo-now-btn" title="Next (→)" onClick={() => step(1)}>
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

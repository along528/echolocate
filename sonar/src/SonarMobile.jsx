// Sonar — mobile (map-first) view. Immersive full-bleed portrait sonar map with
// a Radio Garden-style layered bottom stack: a peeking track-detail panel over
// a docked now-playing strip over a bottom tab bar. The map has a fixed center
// reticle — panning "tunes" the nearest dot to center on release and plays it.
// All state/services/audio come from the shared useSonar hook (passed as `s`)
// so this drives the exact same brain as the desktop view.
import React from 'react';
import { MascotSmall, Waveform } from './svg-bits.jsx';
import {
  IconSearch, IconListPlus, IconCheck, IconPlus, IconSimilar, IconDissimilar,
  IconEye, IconEyeOff, IconClose, IconExternal, IconUp, IconDown,
  IconZoomIn, IconZoomOut, IconTilde,
} from './icons.jsx';
import {
  CANDIDATE_COLOR, FALLBACK_COLOR, fmtTime, coordsOf, distBetween,
  layerTag, layerKindWord, prettyUrl, FeedbackPills, AboutModal,
} from './sonar-utils.jsx';

const MVW = 390, MVH = 780, MPAD = 46;
const ASSET = import.meta.env.BASE_URL;
const PEEK_HEAD = 92; // px of the peek panel that stays visible when collapsed

function dotPosM(t) {
  const [cx, cy] = coordsOf(t);
  return { x: MPAD + cx * (MVW - 2 * MPAD), y: MPAD + (1 - cy) * (MVH - 2 * MPAD) };
}

// Rotate a point by `a` radians (matches SVG rotate()'s matrix, y-down).
// The map transform is screen = T + k·R(r)·p, so inverting screen→plot is
// rot((s − T)/k, −r).
const rot = (p, a) => ({
  x: Math.cos(a) * p.x - Math.sin(a) * p.y,
  y: Math.sin(a) * p.x + Math.cos(a) * p.y,
});

// A modal bottom sheet (search / now / playlist). The whole sheet — not just the
// grip — can be dragged down to dismiss: a drag past ~90px (or a quick flick)
// closes it. A drag that starts inside the scroll body only "engages" the
// dismiss when that body is already scrolled to the top and the drag is
// downward; otherwise it scrolls normally. Buttons/taps still work because the
// drag only engages after an 8px threshold. Tapping the scrim closes it too.
function Sheet({ onClose, style, className = '', children }) {
  const [dragY, setDragY] = React.useState(0);
  const [dragging, setDragging] = React.useState(false);
  const startRef = React.useRef(null);
  const onStart = (e) => {
    const scroller = e.currentTarget.querySelector('.ldm-sheet-scroll');
    startRef.current = {
      y: e.touches[0].clientY, t: Date.now(), engaged: false,
      scroller, inScroll: !!scroller && scroller.contains(e.target),
    };
    setDragY(0);
  };
  const onMove = (e) => {
    const st = startRef.current; if (!st) return;
    const dy = e.touches[0].clientY - st.y;
    if (!st.engaged) {
      const atTop = !st.inScroll || !st.scroller || st.scroller.scrollTop <= 0;
      if (dy > 8 && atTop) { st.engaged = true; setDragging(true); }
      else if (dy < -4 || !atTop) { startRef.current = null; return; } // hand off to native scroll
      else return; // below threshold — let taps through
    }
    setDragY(dy > 0 ? dy : 0);
  };
  const onEnd = () => {
    const st = startRef.current;
    setDragging(false);
    startRef.current = null;
    if (!st || !st.engaged) { setDragY(0); return; }
    const dt = Date.now() - st.t, dy = dragY;
    if (dy > 90 || (dt > 0 && dy / dt > 0.5 && dy > 30)) onClose();
    else setDragY(0);
  };
  return (
    <div className={'ldm-sheet ' + className}
      onTouchStart={onStart} onTouchMove={onMove} onTouchEnd={onEnd} onTouchCancel={onEnd}
      style={{ ...style, transform: dragY ? `translateY(${dragY}px)` : undefined, transition: dragging ? 'none' : 'transform 0.2s ease' }}>
      <div className="ldm-grip"><div className="ldm-handle" /></div>
      {children}
    </div>
  );
}

// The non-modal peek panel. It sits above the dock (the map stays pannable
// underneath) and snaps between three states: hidden, a 76px "peek" header, and
// a full sheet. Dragging the header moves between states; in the full state a
// downward drag on the body (when scrolled to the top) collapses back to peek.
function PeekSheet({ mode, onFull, onPeek, onHide, header, children }) {
  const ref = React.useRef(null);
  const [dragY, setDragY] = React.useState(null);
  const startRef = React.useRef(null);
  const movedRef = React.useRef(false);
  const baseY = () => {
    const h = ref.current?.offsetHeight || 0;
    return mode === 'full' ? 0 : Math.max(0, h - PEEK_HEAD);
  };
  const onStart = (e) => {
    const body = ref.current?.querySelector('.ldm-peek-body');
    const inBody = !!body && body.contains(e.target);
    movedRef.current = false;
    startRef.current = { y: e.touches[0].clientY, t: Date.now(), base: baseY(), body, engaged: !inBody };
  };
  const onMove = (e) => {
    const s = startRef.current; if (!s) return;
    const dy = e.touches[0].clientY - s.y;
    if (Math.abs(dy) > 3) movedRef.current = true;
    if (!s.engaged) {
      const atTop = !s.body || s.body.scrollTop <= 0;
      if (dy > 8 && atTop) s.engaged = true; // dragging down from a top-scrolled body
      else return; // let the body scroll
    }
    const h = ref.current?.offsetHeight || 0;
    setDragY(Math.max(0, Math.min(h, s.base + dy)));
  };
  const onEnd = () => {
    const s = startRef.current; startRef.current = null;
    if (!s || !s.engaged) { setDragY(null); return; }
    const cur = dragY == null ? s.base : dragY;
    const dy = cur - s.base, dt = Date.now() - s.t;
    setDragY(null);
    const flick = dt > 0 && Math.abs(dy) / dt > 0.5 && Math.abs(dy) > 30;
    if (mode === 'peek') {
      if (dy < -60 || (flick && dy < 0)) onFull();
      else if (dy > 60 || (flick && dy > 0)) onHide();
    } else if (dy > 90 || (flick && dy > 0)) onPeek();
  };
  const onHeadClick = () => {
    if (movedRef.current) { movedRef.current = false; return; }
    if (mode === 'peek') onFull(); else onPeek();
  };
  return (
    <div ref={ref} className={'ldm-peek ' + (mode === 'full' ? 'is-full' : '')}
      onTouchStart={onStart} onTouchMove={onMove} onTouchEnd={onEnd} onTouchCancel={onEnd}
      style={dragY != null ? { transform: `translateY(${dragY}px)`, transition: 'none' } : undefined}>
      <div className="ldm-peek-head" onClick={onHeadClick}>
        <div className="ldm-handle" />
        {header}
      </div>
      <div className="ldm-peek-body">{children}</div>
    </div>
  );
}

export default function SonarMobile({ s }) {
  const {
    view, setView, vibeQuery, setVibeQuery, aboutOpen, setAboutOpen,
    layers, playingId, isPlaying, progress, peaks, selectedId, setSelectedId,
    backdrop,
    candidates, labelsByTrackId, soloLayerId, zoom, setZoom,
    addVibeLayer, addSeedLayer, removeLayer, toggleLayerVisible, toggleSolo,
    showAllLayers, hideAllLayers,
    visibleTracks, visibleLayers, displayLayers, anyLoading,
    entryByTrackId, playlistById, playlist, tracksById,
    playing, playingOrigin, selected, playlistTracks, playingTotal, vibeSuggestions, isCandidate, sourceTagFor,
    addToPlaylist, insertCandidate, removeFromPlaylist, movePlaylist, clearPlaylist,
    interpolateEdge, clearCandidates, playTrack, togglePlay, step, labelTrack, seekTo,
  } = s;

  // Mobile-only UI state. `sheet` is the modal layer (search / now / playlist);
  // `detailMode` is the separate non-modal peek panel over the dock.
  const [sheet, setSheet] = React.useState(null);
  const [detailMode, setDetailMode] = React.useState('hidden'); // 'hidden' | 'peek' | 'full'
  const [kbInset, setKbInset] = React.useState(0);
  // Whether the snap-to-center "tuning" auto-plays the track (persisted).
  const [autoPlay, setAutoPlay] = React.useState(() => {
    try { return localStorage.getItem('sonar-autoplay') !== '0'; } catch { return true; }
  });
  const autoPlayRef = React.useRef(autoPlay);
  autoPlayRef.current = autoPlay;
  const toggleAutoPlay = () => setAutoPlay((v) => {
    try { localStorage.setItem('sonar-autoplay', v ? '0' : '1'); } catch { /* ignore */ }
    return !v;
  });

  // Inverse zoom so dots/rings stay a constant screen size (zoom between dots).
  const iz = 1 / zoom.k;

  // Latest zoom in a ref so the touch handlers never read a stale closure.
  const zoomRef = React.useRef(zoom);
  zoomRef.current = zoom;
  // Active touch gesture (pan / pinch) bookkeeping, and a flag that a drag
  // actually moved — so a drag that starts on a dot doesn't also tap it.
  const gestureRef = React.useRef(null);
  const movedRef = React.useRef(false);

  // Composition wrappers over shared handlers. A dot tap opens the peek panel
  // (non-modal) rather than a modal sheet.
  const openDetail = (id) => { setSelectedId(id); setDetailMode('peek'); };

  // The currently-soloed layer ("expanded pill") and, for similar/dissimilar
  // pills, the track it's compared against. The seed track is only surfaced on
  // the map / in the drop-down detail while its pill is expanded.
  const soloLayer = soloLayerId ? layers.find((l) => l.id === soloLayerId) : null;
  const soloSeed = soloLayer
    && (soloLayer.kind === 'similar' || soloLayer.kind === 'dissimilar')
    ? soloLayer.seedTrack : null;
  // Origin (plot coords) of the candidate reveal wave — the charged dot for a
  // long-press, the link midpoint for a playlist-sheet interpolation. The wave
  // plays when the candidates mount (i.e., when the API responds).
  const waveRef = React.useRef(null);
  const onInterpolate = (a, b) => {
    const pa = dotPosM(a), pb = dotPosM(b);
    waveRef.current = { x: (pa.x + pb.x) / 2, y: (pa.y + pb.y) / 2 };
    interpolateEdge(a, b); setSheet(null); setView('map');
  };
  // Adding a vibe always closes the search sheet and drops you on the map to
  // watch the new dots land.
  const addVibe = (q) => { const v = q.trim(); if (!v) return; addVibeLayer(v); setVibeQuery(''); setSheet(null); setView('map'); };
  // Run a map tap action unless the touch was actually a drag (pan/pinch).
  const onTap = (fn) => (e) => {
    e.stopPropagation();
    if (movedRef.current) return;
    fn();
  };

  // ---- haptics ----
  // Android: Vibration API (patterns, cancellable). iOS Safari has no vibrate;
  // programmatically toggling a hidden checkbox-switch produces a single
  // system tick on iOS 17.4+ — a best-effort fallback that no-ops elsewhere.
  const hapticSwitchRef = React.useRef(null);
  const haptic = (pattern) => {
    try {
      if (navigator.vibrate) navigator.vibrate(pattern);
      else hapticSwitchRef.current?.click();
    } catch { /* ignore */ }
  };

  // ---- double-tap to interpolate ----
  // Dot: double-tap interpolates between the reticle-tuned track and that dot.
  // Playlist link: double-tap interpolates between its two endpoints. A single
  // tap on a dot still opens its detail; a single tap on a link does nothing.
  const DOUBLE_TAP_MS = 300;
  const lastTapRef = React.useRef({ key: null, t: 0, anchor: null });
  // First tap selects the dot (opening its detail) and remembers the track that
  // was tuned *before* this tap — the interpolation anchor; a quick second tap on
  // the same dot fires the interpolation against that anchor.
  const handleDotTap = (t) => {
    const now = Date.now();
    const prev = lastTapRef.current;
    if (prev.key === t.id && now - prev.t < DOUBLE_TAP_MS && prev.anchor && prev.anchor.id !== t.id) {
      lastTapRef.current = { key: null, t: 0, anchor: null };
      const p = dotPosM(t);
      waveRef.current = { x: p.x, y: p.y }; // reveal wave radiates from the dot
      haptic(35); // confirm buzz
      interpolateEdge(prev.anchor, t); // candidates appear between the two
    } else {
      lastTapRef.current = { key: t.id, t: now, anchor: selected };
      openDetail(t.id);
    }
  };
  // A quick double-tap on a playlist link interpolates its two endpoints.
  const handleEdgeTap = (a, b) => {
    const now = Date.now();
    const key = `e:${a.id}:${b.id}`;
    const prev = lastTapRef.current;
    if (prev.key === key && now - prev.t < DOUBLE_TAP_MS) {
      lastTapRef.current = { key: null, t: 0, anchor: null };
      haptic(35);
      onInterpolate(a, b); // sets the reveal wave + requests candidates
    } else {
      lastTapRef.current = { key, t: now, anchor: null };
    }
  };

  // When the selection clears, the peek panel has nothing to show.
  React.useEffect(() => { if (!selected) setDetailMode('hidden'); }, [selected]);

  // ---- bottom dock height → CSS var + JS value (drives reticle centering,
  // list padding, legend/zoom offsets). Re-measures when the strip mounts. ----
  const appRef = React.useRef(null);
  const topRef = React.useRef(null);
  const dockRef = React.useRef(null);
  const [dockH, setDockH] = React.useState(0);
  React.useEffect(() => {
    if (typeof ResizeObserver === 'undefined') return undefined;
    const setVar = (name, px) => appRef.current?.style.setProperty(name, `${px}px`);
    const roTop = topRef.current && new ResizeObserver(() => setVar('--ldm-top-h', topRef.current.offsetHeight));
    const roDock = dockRef.current && new ResizeObserver(() => {
      const h = dockRef.current.offsetHeight;
      setDockH(h); setVar('--ldm-bottom-h', h);
    });
    if (roTop) roTop.observe(topRef.current);
    if (roDock) roDock.observe(dockRef.current);
    return () => { roTop && roTop.disconnect(); roDock && roDock.disconnect(); };
  }, []);

  // Mobile zoom — clamped k ∈ [0.3, 5].
  // (Scaling about a fixed screen point is rotation-agnostic: c−T' = (k'/k)(c−T).)
  // When a track is selected (tuned under the reticle), scale about the RETICLE
  // so it stays pinned; otherwise scale about the screen center and let the
  // reticle drift.
  const ZK_MIN = 0.3, ZK_MAX = 5;
  const zoomBy = (f) => {
    const el = mapRef.current;
    const tuned = selected;
    setZoom((z) => {
      const k = Math.max(ZK_MIN, Math.min(ZK_MAX, z.k * f));
      let cx = MVW / 2, cy = MVH / 2;
      if (tuned && el) {
        const rect = el.getBoundingClientRect();
        if (rect.width) { const { S, offX, offY } = rectMetrics(rect); cx = (rect.width / 2 - offX) / S; cy = ((rect.height - dockH) / 2 - offY) / S; }
      }
      return { k, r: z.r || 0, x: cx - (cx - z.x) * (k / z.k), y: cy - (cy - z.y) * (k / z.k) };
    });
  };

  // ---- snap-to-center animation (rAF tween of zoom state) ----
  const animRef = React.useRef(0);
  const lastSnapIdRef = React.useRef(null);
  const animateZoomTo = (target, ms = 280) => {
    cancelAnimationFrame(animRef.current);
    const from = { ...zoomRef.current };
    const t0 = performance.now();
    const ease = (u) => 1 - (1 - u) ** 3; // easeOutCubic
    const tick = (now) => {
      const u = Math.min(1, (now - t0) / ms), e = ease(u);
      setZoom({
        k: from.k + (target.k - from.k) * e,
        x: from.x + (target.x - from.x) * e,
        y: from.y + (target.y - from.y) * e,
        r: (from.r || 0) + ((target.r || 0) - (from.r || 0)) * e,
      });
      if (u < 1) animRef.current = requestAnimationFrame(tick);
    };
    animRef.current = requestAnimationFrame(tick);
  };
  React.useEffect(() => () => cancelAnimationFrame(animRef.current), []);

  // ---- touch: one-finger pan, two-finger pinch, snap on release ----
  // The SVG uses preserveAspectRatio="slice", so screen↔viewBox needs the cover
  // scale S = max(W/MVW, H/MVH) and the centering offsets.
  const rectMetrics = (rect) => {
    const S = Math.max(rect.width / MVW, rect.height / MVH);
    return { S, offX: (rect.width - S * MVW) / 2, offY: (rect.height - S * MVH) / 2 };
  };
  const SNAP_MAX_PX = 70;
  const snapToCenter = (rect) => {
    const z = zoomRef.current;
    const { S, offX, offY } = rectMetrics(rect);
    // reticle sits at the center of the visible band (above the dock)
    const cvx = (rect.width / 2 - offX) / S;
    const cvy = ((rect.height - dockH) / 2 - offY) / S;
    // plot coords under the reticle (inverting translate∘scale∘rotate)
    const cp = rot({ x: (cvx - z.x) / z.k, y: (cvy - z.y) / z.k }, -(z.r || 0));
    let best = null, bestD = Infinity;
    const consider = (t) => {
      const p = dotPosM(t);
      const d = Math.hypot(p.x - cp.x, p.y - cp.y); // rotation preserves distance
      if (d < bestD) { bestD = d; best = t; }
    };
    if (candidates) {
      // Interpolation focus mode: only the candidates and the two endpoints
      // are on the map, so only they are snappable.
      candidates.tracks.forEach(consider);
      const ea = tracksById.get(candidates.aId), eb = tracksById.get(candidates.bId);
      if (ea) consider(ea);
      if (eb) consider(eb);
    } else {
      visibleTracks.forEach((e) => consider(e.track));
      playlistTracks.forEach(consider);
    }
    if (!best || bestD * z.k * S > SNAP_MAX_PX) { lastSnapIdRef.current = null; return; }
    const rp = rot(dotPosM(best), z.r || 0);
    animateZoomTo({ k: z.k, r: z.r || 0, x: cvx - z.k * rp.x, y: cvy - z.k * rp.y });
    if (autoPlayRef.current) {
      if (best.id !== lastSnapIdRef.current && best.id !== playingId) {
        lastSnapIdRef.current = best.id;
        playTrack(best); // auto-play the tuned track; selects it too
      }
    } else {
      lastSnapIdRef.current = best.id;
      setSelectedId(best.id); // tune silently — the peek shows it, nothing plays
    }
    setDetailMode((m) => (m === 'hidden' ? 'peek' : m));
  };

  // Glide the map so `tracks` fill the screen. Modes:
  //  • default — if a track is tuned (playing/selected), keep IT under the
  //    reticle and only adjust zoom; otherwise center on the dots' bounding box.
  //  • { fill: true } — ignore the tuned track and center on the bounding box,
  //    so the dots truly fill the screen (e.g. when a search resolves).
  //  • { keepReticle: true } — DON'T pan at all: keep whatever's under the
  //    reticle right now planted there and only zoom to fit the dots around it
  //    (used when clicking/deleting a pill, so the reticle never jumps).
  // Rotation is preserved throughout.
  const FIT_MAX = 3.5;
  const mapRef = React.useRef(null);
  const recenterOn = (tracks, opts = {}) => {
    const el = mapRef.current;
    if (!el || !tracks || !tracks.length) return;
    const rect = el.getBoundingClientRect();
    if (!rect.width) return;
    const { S, offX, offY } = rectMetrics(rect);
    const z = zoomRef.current, r = z.r || 0;
    const peekH = appRef.current
      ? parseFloat(getComputedStyle(appRef.current).getPropertyValue('--ldm-peek-h')) || 0
      : 0;
    const PAD = 0.78;                                   // leave a margin around the dots
    const halfW = (rect.width / S) / 2;
    const cvx = (rect.width / 2 - offX) / S;
    // The reticle center MUST match the .ldm-reticle element (and snapToCenter),
    // which offsets only by the dock — NOT the peek — so an anchored fit keeps the
    // tuned/reticle point exactly under the visible reticle. The peek is handled by
    // shrinking the usable half-height *below* the reticle, not by moving the center.
    const cvyR = ((rect.height - dockH) / 2 - offY) / S;
    const halfHkeep = Math.max(0.06 * (rect.height / S), ((rect.height - dockH) / 2 - peekH) / S);
    // Work in the screen-aligned frame (rotate dots by the current map rotation).
    const qs = tracks.map((t) => rot(dotPosM(t), r));
    // The fixed point (rotated-frame) to fit around: keepReticle → whatever's
    // under the reticle right now; default → the tuned track; fill → none (bbox).
    let qa = null;
    if (opts.keepReticle) qa = { x: (cvx - z.x) / z.k, y: (cvyR - z.y) / z.k };
    else if (!opts.fill) { const at = tracksById.get(selectedId) || playing; if (at) qa = rot(dotPosM(at), r); }
    let k, cx, cy, tx, ty;
    if (qa) {
      // Keep the fixed point under the reticle; fit everything around it (no pan).
      let mdx = 1e-3, mdy = 1e-3;
      qs.forEach((q) => { mdx = Math.max(mdx, Math.abs(q.x - qa.x)); mdy = Math.max(mdy, Math.abs(q.y - qa.y)); });
      k = Math.min((halfW * PAD) / mdx, (halfHkeep * PAD) / mdy);
      cx = qa.x; cy = qa.y; tx = cvx; ty = cvyR;
    } else {
      // Center on the bounding box of the dots, framed in the band above ALL the
      // bottom chrome (dock + peek). Panning is allowed in this mode.
      const cvyFit = ((rect.height - dockH - peekH) / 2 - offY) / S;
      const halfHfit = ((rect.height - dockH - peekH) / S) / 2;
      let minx = Infinity, maxx = -Infinity, miny = Infinity, maxy = -Infinity;
      qs.forEach((q) => { minx = Math.min(minx, q.x); maxx = Math.max(maxx, q.x); miny = Math.min(miny, q.y); maxy = Math.max(maxy, q.y); });
      const bw = Math.max(1e-3, maxx - minx), bh = Math.max(1e-3, maxy - miny);
      k = Math.min((halfW * 2 * PAD) / bw, (halfHfit * 2 * PAD) / bh);
      cx = (minx + maxx) / 2; cy = (miny + maxy) / 2; tx = cvx; ty = cvyFit;
    }
    k = Math.max(ZK_MIN, Math.min(FIT_MAX, k));
    animateZoomTo({ k, r, x: tx - k * cx, y: ty - k * cy }, 520);
  };

  // Recenter when a search finishes loading (dots just popped in) — frame the
  // new pill's tracks together with everything else currently highlighted
  // (other results + playlist dots).
  const wasLoadingRef = React.useRef(anyLoading);
  React.useEffect(() => {
    if (wasLoadingRef.current && !anyLoading) {
      const m = new Map();
      visibleTracks.forEach((e) => m.set(e.track.id, e.track));
      playlistTracks.forEach((t) => m.set(t.id, t));
      recenterOn([...m.values()]);
    }
    wasLoadingRef.current = anyLoading;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [anyLoading]);
  // …when a pill is soloed / un-soloed (the visible set changes). Zoom to fit
  // the now-visible dots WITHOUT moving the reticle (keepReticle), so clicking a
  // pill never yanks the view around.
  const prevSoloRef = React.useRef(soloLayerId);
  React.useEffect(() => {
    if (prevSoloRef.current !== soloLayerId) {
      prevSoloRef.current = soloLayerId;
      const vis = visibleTracks.map((e) => e.track);
      // Frame the seed track too when expanding a similar/dissimilar pill, so
      // "zooming into the pill" includes the track being compared against.
      const solo = soloLayerId ? layers.find((l) => l.id === soloLayerId) : null;
      if (solo?.seedTrack) vis.push(solo.seedTrack);
      if (vis.length) recenterOn(vis, { keepReticle: true });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [soloLayerId]);
  // …and when a pill is deleted (the visible set shrinks) — re-fit the dots that
  // remain (same keepReticle behavior). Adds are handled by the loading effect
  // above; only fire on a removal, and never mid-search.
  const prevLayerCountRef = React.useRef(layers.length);
  React.useEffect(() => {
    const removed = layers.length < prevLayerCountRef.current;
    prevLayerCountRef.current = layers.length;
    if (!removed || anyLoading) return;
    const vis = visibleTracks.map((e) => e.track);
    if (vis.length) recenterOn(vis, { keepReticle: true });
    else if (playlistTracks.length) recenterOn(playlistTracks, { keepReticle: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [layers]);
  // …when interpolation candidates arrive (frame endpoints + candidates), and
  // when they're dismissed — refit the dots that come back into view.
  const prevCandRef = React.useRef(candidates);
  React.useEffect(() => {
    const had = prevCandRef.current;
    prevCandRef.current = candidates;
    if (candidates) {
      const pts = [...candidates.tracks];
      const a = tracksById.get(candidates.aId), b = tracksById.get(candidates.bId);
      if (a) pts.push(a); if (b) pts.push(b);
      recenterOn(pts, { keepReticle: true }); // zoom to fit the endpoints+candidates without moving the reticle
    } else if (had) {
      const vis = visibleTracks.map((e) => e.track);
      if (vis.length) recenterOn(vis, { keepReticle: true });
      else if (playlistTracks.length) recenterOn(playlistTracks, { keepReticle: true });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [candidates]);

  const onTouchStart = (e) => {
    cancelAnimationFrame(animRef.current); // grab the map mid-tween
    const t = e.touches;
    const rect = e.currentTarget.getBoundingClientRect();
    movedRef.current = false;
    if (t.length === 1) {
      gestureRef.current = { mode: 'pan', x: t[0].clientX, y: t[0].clientY, z0: { ...zoomRef.current }, rect };
    } else if (t.length === 2) {
      const dist = Math.hypot(t[0].clientX - t[1].clientX, t[0].clientY - t[1].clientY);
      const angle = Math.atan2(t[1].clientY - t[0].clientY, t[1].clientX - t[0].clientX);
      gestureRef.current = { mode: 'pinch', dist, angle, z0: { ...zoomRef.current }, rect };
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
      g.maxDist = Math.max(g.maxDist || 0, Math.hypot(dxs, dys));
      if (!movedRef.current && Math.hypot(dxs, dys) > 4) { movedRef.current = true; }
      if (movedRef.current) setZoom({ k: g.z0.k, r: g.z0.r || 0, x: g.z0.x + dxs / S, y: g.z0.y + dys / S });
    } else if (g.mode === 'pinch' && t.length === 2) {
      // Two-finger pinch scales AND rotates, anchored on the RETICLE — the
      // tuned point stays put while the map zooms/spins around it.
      const dist = Math.hypot(t[0].clientX - t[1].clientX, t[0].clientY - t[1].clientY);
      const angle = Math.atan2(t[1].clientY - t[0].clientY, t[1].clientX - t[0].clientX);
      const kNew = Math.max(ZK_MIN, Math.min(ZK_MAX, g.z0.k * (dist / (g.dist || dist))));
      const rNew = (g.z0.r || 0) + (angle - g.angle);
      // reticle center in viewBox coords (center of the visible band above the dock)
      const cvx = (g.rect.width / 2 - offX) / S;
      const cvy = ((g.rect.height - dockH) / 2 - offY) / S;
      // plot point under the reticle at gesture start, re-projected with the new k/r
      const p0 = rot({ x: (cvx - g.z0.x) / g.z0.k, y: (cvy - g.z0.y) / g.z0.k }, -(g.z0.r || 0));
      const rp = rot(p0, rNew);
      setZoom({ k: kNew, r: rNew, x: cvx - kNew * rp.x, y: cvy - kNew * rp.y });
    }
  };
  const onTouchEnd = (e) => {
    if (e.touches.length === 0) {
      const g = gestureRef.current;
      gestureRef.current = null;
      // Snap only on a DELIBERATE one-finger pan (>24px of travel) — never
      // right after a pinch, and never from a sloppy tap's few-px jitter.
      if (g && g.mode === 'pan' && !g.fromPinch && movedRef.current && (g.maxDist || 0) > 24) snapToCenter(g.rect);
      return;
    }
    // Lifting one finger of a pinch → continue as a pan (but don't snap after).
    if (e.touches.length === 1) {
      gestureRef.current = { mode: 'pan', fromPinch: true, x: e.touches[0].clientX, y: e.touches[0].clientY, z0: { ...zoomRef.current }, rect: e.currentTarget.getBoundingClientRect() };
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

  // Focus the search input WITHOUT scrolling it into view (that scroll shoved
  // the sheet off the top); we keep the sheet pinned above the keyboard instead.
  const searchInputRef = React.useRef(null);
  React.useEffect(() => {
    if (sheet !== 'search') return undefined;
    const id = setTimeout(() => { try { searchInputRef.current?.focus({ preventScroll: true }); } catch { searchInputRef.current?.focus(); } }, 60);
    return () => clearTimeout(id);
  }, [sheet]);

  // Prev/next on the strip only make sense when the current track is actually
  // in the playlist (step() walks the playlist then) and there's somewhere to go.
  const stripNav = playlistTracks.length > 1 && playlistById.has(playingId);
  const playSvg = <svg viewBox="0 0 24 24" fill="white" width="16" height="16"><path d="M8 5v14l11-7z" /></svg>;
  const pauseSvg = <svg viewBox="0 0 24 24" fill="white" width="16" height="16"><path d="M6 5h4v14H6zm8 0h4v14h-4z" /></svg>;

  return (
    <div ref={appRef} className={'ldm-app' + (detailMode === 'peek' ? ' is-peek' : '')}>
      {/* iOS haptic shim — toggling a switch input produces a system tick. */}
      <input ref={hapticSwitchRef} type="checkbox" switch="" tabIndex={-1} aria-hidden="true"
        style={{ position: 'absolute', width: 1, height: 1, opacity: 0, pointerEvents: 'none' }}
        onChange={() => {}} />
      {/* ===== MAP / LIST STAGE ===== */}
      {view === 'map' ? (
        <div className="ldm-stage">
          <svg ref={mapRef} className="ldm-map" viewBox={`0 0 ${MVW} ${MVH}`} preserveAspectRatio="xMidYMid slice"
            onClick={() => { if (!movedRef.current) { if (sheet) setSheet(null); else if (detailMode !== 'hidden') setDetailMode('hidden'); } }}
            onTouchStart={onTouchStart} onTouchMove={onTouchMove} onTouchEnd={onTouchEnd} onTouchCancel={onTouchEnd}>
            <rect x={0} y={0} width={MVW} height={MVH} fill="transparent" />
            <defs>
              <pattern id="ldm-grid" width="74.5" height="74.5" patternUnits="userSpaceOnUse">
                <path d="M 74.5 0 L 0 0 0 74.5" fill="none" stroke="white" strokeOpacity="0.14" strokeWidth="0.6" />
              </pattern>
            </defs>
            <g transform={`translate(${zoom.x} ${zoom.y}) scale(${zoom.k}) rotate(${((zoom.r || 0) * 180) / Math.PI})`}>
              {/* Effectively-infinite grid (stays in plot space — scales with zoom). */}
              <rect x={-6000} y={-6000} width={12000} height={12000} fill="url(#ldm-grid)" style={{ pointerEvents: 'none' }} />
              {/* Dimmed backdrop field — spatial context for the whole corpus. */}
              {backdrop.length > 0 && (
                <g style={{ pointerEvents: 'none' }}>
                  {backdrop.map((pt) => { const p = dotPosM(pt); return <circle key={'bd' + pt.id} cx={p.x} cy={p.y} r={1.6 * iz} fill="white" opacity={0.1} />; })}
                </g>
              )}
              {playing && [44, 90, 150, 220].map((r, i) => { const p = dotPosM(playing); return <circle key={i} cx={p.x} cy={p.y} r={r * iz} fill="none" stroke="var(--el-yellow-500)" strokeOpacity={[0.55, 0.35, 0.22, 0.12][i]} strokeWidth={iz} style={{ pointerEvents: 'none' }} />; })}
              {/* The now-playing rings must always sit on a dot. If the playing
                  track isn't otherwise drawn (its layer was hidden/deleted and
                  it's not in the playlist, or it's off-stage in focus mode), draw
                  a standalone marker — in the track's retained origin color — that
                  stays tappable so it's still peekable. */}
              {playing && !(candidates
                ? (candidates.aId === playing.id || candidates.bId === playing.id || candidates.tracks.some((t) => t.id === playing.id))
                : (entryByTrackId.has(playing.id) || playlistById.has(playing.id))
              ) && (() => { const p = dotPosM(playing); const color = playingOrigin?.color || FALLBACK_COLOR; return (
                <g onClick={onTap(() => handleDotTap(playing))}>
                  <circle cx={p.x} cy={p.y} r={14 * iz} fill="transparent" />
                  <circle cx={p.x} cy={p.y} r={9.5 * iz} fill={color} style={{ filter: `drop-shadow(0 0 8px ${color})` }} />
                  <circle cx={p.x} cy={p.y} r={10 * iz} fill="none" stroke="white" strokeWidth={iz} strokeOpacity="0.7" />
                </g>); })()}
              {candidates ? (
                /* ===== INTERPOLATION FOCUS MODE — only the two endpoints and
                   the candidates between them; everything else hides (like
                   solo-ing a pill) until the ✕ chip dismisses it. The
                   candidates reveal as a wave: a ring expands from the charged
                   dot and each one fades in as the ring reaches it. ===== */
                (() => {
                  const wave = waveRef.current;
                  const setKey = candidates.aId + candidates.bId; // remount per interpolation
                  const dists = candidates.tracks.map((t) => { const p = dotPosM(t); return wave ? Math.hypot(p.x - wave.x, p.y - wave.y) : 0; });
                  const maxD = Math.max(1, ...dists);
                  const WAVE_MS = 500; // ring sweep time; per-dot delay tracks it
                  return (<>
                    {(() => { const a = tracksById.get(candidates.aId), b = tracksById.get(candidates.bId); if (!a || !b) return null; const pa = dotPosM(a), pb = dotPosM(b);
                      return <line x1={pa.x} y1={pa.y} x2={pb.x} y2={pb.y} stroke={CANDIDATE_COLOR} strokeOpacity="0.45" strokeWidth={1.5 * iz} strokeDasharray={`${4 * iz} ${4 * iz}`} style={{ pointerEvents: 'none' }} />; })()}
                    {wave && (
                      <circle key={'w' + setKey} className="ldm-wave-ring" cx={wave.x} cy={wave.y} r={maxD * 1.1}
                        strokeWidth={1.5 * iz} style={{ pointerEvents: 'none', animationDuration: `${WAVE_MS + 150}ms` }} />
                    )}
                    {[candidates.aId, candidates.bId].map((id) => { const t = tracksById.get(id); if (!t) return null; const p = dotPosM(t); const color = entryByTrackId.get(id)?.color || playlistById.get(id)?.color || FALLBACK_COLOR; const isSel = id === selectedId, isPlay = id === playingId;
                      return (<g key={'ep' + id} onClick={onTap(() => handleDotTap(t))}>
                        <circle cx={p.x} cy={p.y} r={14 * iz} fill="transparent" />
                        {isSel && <circle cx={p.x} cy={p.y} r={13 * iz} fill="none" stroke={color} strokeWidth={1.5 * iz} />}
                        <circle cx={p.x} cy={p.y} r={(isPlay ? 9.5 : 7.5) * iz} fill={color} style={{ filter: isPlay ? `drop-shadow(0 0 8px ${color})` : 'none' }} />
                        <circle cx={p.x} cy={p.y} r={10 * iz} fill="none" stroke="white" strokeWidth={iz} strokeOpacity="0.7" />
                      </g>); })}
                    {candidates.tracks.map((t, i) => { const p = dotPosM(t); const isSel = t.id === selectedId, isPlay = t.id === playingId;
                      const delay = wave ? (dists[i] / maxD) * WAVE_MS : 0;
                      return (<g key={'c' + setKey + t.id} className={wave ? 'ldm-cand-in' : undefined}
                        style={wave ? { animationDelay: `${Math.round(delay)}ms` } : undefined}
                        onClick={onTap(() => handleDotTap(t))}>
                        <circle cx={p.x} cy={p.y} r={14 * iz} fill="transparent" />
                        {isSel && <circle cx={p.x} cy={p.y} r={12 * iz} fill="none" stroke={CANDIDATE_COLOR} strokeWidth={1.5 * iz} />}
                        <circle cx={p.x} cy={p.y} r={10 * iz} fill="none" stroke={CANDIDATE_COLOR} strokeWidth={1.2 * iz} strokeOpacity="0.7" strokeDasharray={`${3 * iz} ${2 * iz}`} />
                        <circle cx={p.x} cy={p.y} r={(isPlay ? 7 : 5) * iz} fill={CANDIDATE_COLOR} opacity="0.9" style={{ filter: isPlay ? `drop-shadow(0 0 8px ${CANDIDATE_COLOR})` : 'none' }} />
                      </g>); })}
                  </>);
                })()
              ) : (
                <>
                  {playlistTracks.length > 1 && playlistTracks.slice(1).map((b, i) => { const a = playlistTracks[i], pa = dotPosM(a), pb = dotPosM(b);
                    return (<g key={`s${a.id}${b.id}`} onClick={onTap(() => handleEdgeTap(a, b))}><line x1={pa.x} y1={pa.y} x2={pb.x} y2={pb.y} stroke="transparent" strokeWidth={20 * iz} /><line x1={pa.x} y1={pa.y} x2={pb.x} y2={pb.y} stroke="var(--el-indigo-500)" strokeOpacity={0.55} strokeWidth={2 * iz} strokeDasharray={`${4 * iz} ${4 * iz}`} /></g>); })}
                  {playlistTracks.map((t) => { const p = dotPosM(t); return <circle key={'r' + t.id} cx={p.x} cy={p.y} r={13 * iz} fill="none" stroke="var(--el-indigo-500)" strokeWidth={2 * iz} strokeOpacity="0.6" style={{ pointerEvents: 'none' }} />; })}
                  {visibleTracks.map(({ track: t, color }, i) => { const p = dotPosM(t), isPlay = t.id === playingId, isSel = t.id === selectedId, inPl = playlistById.has(t.id); const r = (isPlay ? 9.5 : isSel ? 8 : 5.5) * iz;
                    return (<g key={t.id} className="el-dot-pop" style={{ animationDelay: `${Math.min(i * 14, 320)}ms` }} onClick={onTap(() => handleDotTap(t))}>
                      <circle cx={p.x} cy={p.y} r={14 * iz} fill="transparent" />
                      {isSel && <circle cx={p.x} cy={p.y} r={r + 6 * iz} fill="none" stroke={color} strokeWidth={1.5 * iz} />}
                      <circle cx={p.x} cy={p.y} r={r} fill={color} opacity={inPl ? 1 : 0.88} style={{ filter: isPlay ? `drop-shadow(0 0 8px ${color})` : 'none' }} />
                      {inPl && <circle cx={p.x} cy={p.y} r={r + 3 * iz} fill="none" stroke="white" strokeWidth={iz} />}
                    </g>); })}
                  {/* Seed track of the expanded (soloed) similar/dissimilar pill:
                      a distinct dashed-ring marker, clickable to peek/play. Only
                      shown while that pill is soloed. */}
                  {soloSeed && (() => { const p = dotPosM(soloSeed); const isPlay = soloSeed.id === playingId, isSel = soloSeed.id === selectedId; const color = soloLayer.color; const core = (isPlay ? 9 : 7) * iz;
                    return (<g key={'seed' + soloSeed.id} onClick={onTap(() => handleDotTap(soloSeed))}>
                      <circle cx={p.x} cy={p.y} r={16 * iz} fill="transparent" />
                      <circle cx={p.x} cy={p.y} r={13 * iz} fill="none" stroke={color} strokeWidth={1.5 * iz} strokeDasharray={`${3 * iz} ${2 * iz}`} />
                      {isSel && <circle cx={p.x} cy={p.y} r={16 * iz} fill="none" stroke={color} strokeWidth={1.5 * iz} />}
                      <circle cx={p.x} cy={p.y} r={core} fill={color} style={{ filter: `drop-shadow(0 0 6px ${color})` }} />
                      <circle cx={p.x} cy={p.y} r={core + 2.5 * iz} fill="none" stroke="white" strokeWidth={iz} strokeOpacity="0.85" />
                    </g>); })()}
                  {/* playlist tracks whose source layer is no longer visible still
                      get a dot (colored by their saved origin), so the trail stays
                      on the map after the searches are cleared. */}
                  {playlistTracks.map((t) => { if (entryByTrackId.has(t.id)) return null; const p = dotPosM(t); const slot = playlistById.get(t.id); const color = slot?.color || FALLBACK_COLOR; const isPlay = t.id === playingId, isSel = t.id === selectedId;
                    return (<g key={'pl' + t.id} onClick={onTap(() => handleDotTap(t))}>
                      <circle cx={p.x} cy={p.y} r={14 * iz} fill="transparent" />
                      {isSel && <circle cx={p.x} cy={p.y} r={12 * iz} fill="none" stroke={color} strokeWidth={1.5 * iz} />}
                      <circle cx={p.x} cy={p.y} r={(isPlay ? 9.5 : 7) * iz} fill={color} opacity={0.9} />
                      <circle cx={p.x} cy={p.y} r={9.5 * iz} fill="none" stroke="white" strokeWidth={iz} strokeOpacity="0.7" />
                    </g>); })}
                </>
              )}
            </g>
          </svg>

          {/* Fixed center reticle — pan the map to "tune" the nearest dot to it. */}
          <div className="ldm-reticle" aria-hidden="true" />

          {/* Interpolation focus mode banner — one tap dismisses the candidates
              and un-hides the rest of the map. */}
          {candidates && (
            <button className="ldm-interp-clear" onClick={clearCandidates}>
              <span className="ldm-interp-dot" /> tracks in between — tap to dismiss ✕
            </button>
          )}
          <div className="ldm-zoombtns">
            <button className="lo-btn-icon" onClick={() => zoomBy(1.3)}><IconZoomIn size={16} /></button>
            <button className="lo-btn-icon" onClick={() => zoomBy(1 / 1.3)}><IconZoomOut size={16} /></button>
            <button className={'lo-btn-icon ldm-autoplay ' + (autoPlay ? 'is-on' : '')} onClick={toggleAutoPlay}
              title={autoPlay ? 'Tuning auto-plays — tap to explore silently' : 'Silent exploring — tap to auto-play on tune'}>
              <svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor">
                <path d="M9 6.5v11l8.5-5.5z" />
                {!autoPlay && <path d="M4.5 4.5 L19.5 19.5" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" fill="none" />}
              </svg>
            </button>
          </div>
        </div>
      ) : (
        <div className="ldm-listview">
          {visibleTracks.map(({ track: t, color, sources }) => { const inPl = playlistById.has(t.id), isPlay = playingId === t.id;
            return (<div key={t.id} className={'ldm-row ' + (isPlay ? 'is-playing' : '')} onClick={() => playTrack(t)}>
              <span className="ldm-row-dot" style={{ background: color }} />
              <div className="ldm-row-info"><div className="ldm-row-title">{t.title}</div><div className="ldm-row-sub">{t.artist}{t.duration ? ` · ${fmtTime(t.duration)}` : ''} · {sources.map(layerTag).join(', ')}</div></div>
              <button className={'ldm-row-add ' + (inPl ? 'is-active' : '')} onClick={(e) => { e.stopPropagation(); addToPlaylist(t); }}>{inPl ? <IconCheck size={16} /> : <IconListPlus size={16} />}</button>
            </div>); })}
          {/* When there are no search results but a playlist exists, show it here
              instead of a dead-end empty state. */}
          {visibleTracks.length === 0 && playlistTracks.length > 0 && (<>
            <div className="lo-eyebrow" style={{ margin: '4px 0 8px' }}>Your playlist</div>
            {playlist.map((slot) => { const t = slot.track; if (!t) return null; const isPlay = playingId === t.id;
              return (<div key={slot.id} className={'ldm-row ' + (isPlay ? 'is-playing' : '')} onClick={() => playTrack(t)}>
                <span className="ldm-row-dot" style={{ background: slot.color || 'var(--el-indigo-500)' }} />
                <div className="ldm-row-info"><div className="ldm-row-title">{t.title}</div><div className="ldm-row-sub">{t.artist}</div></div>
                <button className="ldm-row-add" onClick={(e) => { e.stopPropagation(); removeFromPlaylist(slot.id); }}><IconClose size={15} /></button>
              </div>); })}
          </>)}
          {visibleTracks.length === 0 && playlistTracks.length === 0 && <div className="ldm-onboard-eyebrow" style={{ textAlign: 'center', marginTop: 40 }}>No results yet. Add a vibe to start.</div>}
        </div>
      )}

      {/* ===== TOP CHROME — pills (scrolling row) over the full-bleed map, with a
          fixed second row of controls (hide/show-all + add) that never scrolls
          away, so a search and the visibility toggle are always one tap. ===== */}
      <div className="ldm-top" ref={topRef}>
        {displayLayers.length > 0 && (
          <div className="ldm-chips">
            {displayLayers.map((l) => (
              <span key={l.id} className={'ldm-chip ' + (l.visible ? '' : 'is-hidden ') + (soloLayerId === l.id ? 'is-solo' : '')} style={{ borderColor: l.color, background: `color-mix(in srgb, ${l.color} 12%, transparent)` }} onClick={() => { clearCandidates(); toggleSolo(l.id); }}>
                <span className="ldm-chip-swatch" style={{ background: l.color }} />{layerTag(l)}
                <button className="ldm-chip-x" onClick={(e) => { e.stopPropagation(); removeLayer(l.id); }}>×</button>
              </span>
            ))}
          </div>
        )}
        {/* Expanded-pill detail: drops down under the pills when one is soloed.
            Vibe → the AI-enhanced caption; similar/dissimilar → the seed track
            it's compared against (tap to peek it; it's also marked on the map). */}
        {soloLayer && (
          <div className="ldm-pill-detail" style={{ borderLeftColor: soloLayer.color }}>
            <span className="ldm-pill-detail-kind" style={{ color: soloLayer.color }}>{layerKindWord(soloLayer)}</span>
            {soloLayer.kind === 'vibe' ? (
              soloLayer.enhancedQuery
                ? <span className="ldm-pill-detail-enh">✨ {soloLayer.enhancedQuery}</span>
                : <span className="ldm-pill-detail-dim">{soloLayer.loading ? 'enhancing…' : 'no enhanced caption'}</span>
            ) : (
              soloSeed
                ? <button className="ldm-pill-detail-seed" onClick={() => openDetail(soloSeed.id)}>
                    {soloSeed.title} <span className="ldm-pill-detail-artist">— {soloSeed.artist}</span>
                  </button>
                : <span className="ldm-pill-detail-dim">seed track unavailable</span>
            )}
          </div>
        )}
        <div className="ldm-chips-ctl">
          {displayLayers.length > 0 && (() => { const anyShown = visibleLayers.length > 0;
            return (<button className="ldm-chip ldm-chip-eye" onClick={() => { clearCandidates(); (anyShown ? hideAllLayers : showAllLayers)(); }}
              title={anyShown ? 'Hide all searches' : 'Show all searches'} aria-label={anyShown ? 'Hide all searches' : 'Show all searches'}>
              {anyShown ? <IconEye size={14} /> : <IconEyeOff size={14} />}
            </button>); })()}
          <button className="ldm-chip ldm-chip-add" onClick={() => setSheet('search')}><IconPlus size={13} /> add</button>
        </div>
      </div>

      {/* ===== PEEK DETAIL (non-modal, above the dock) ===== */}
      {detailMode === 'full' && <div className="ldm-detail-scrim" onClick={() => setDetailMode('peek')} />}
      {detailMode !== 'hidden' && selected && (() => { const t = selected; const cand = isCandidate(t.id); const sources = entryByTrackId.get(t.id)?.sources || []; const inPl = playlistById.has(t.id); const slotOrigin = playlistById.get(t.id)?.origin; const playOrigin = (!sources.length && !slotOrigin && t.id === playingId) ? playingOrigin : null; const swatch = entryByTrackId.get(t.id)?.color || slotOrigin?.color || playOrigin?.color || (cand ? CANDIDATE_COLOR : FALLBACK_COLOR);
        return (
          <PeekSheet mode={detailMode} onFull={() => setDetailMode('full')} onPeek={() => setDetailMode('peek')} onHide={() => setDetailMode('hidden')}
            header={(
              <div className="ldm-peek-row">
                <span className="ldm-peek-swatch" style={{ background: swatch }} />
                <div className="ldm-peek-info">
                  <div className="ldm-peek-title">{t.title}</div>
                  <div className="ldm-peek-sub">{t.artist}</div>
                  <div className="ldm-peek-meta">
                    {cand && <span className="ldm-peek-tag" style={{ color: CANDIDATE_COLOR }}>interpolation</span>}
                    {!cand && sources[0] && <span className="ldm-peek-tag" style={{ color: sources[0].color }}>{layerTag(sources[0])}</span>}
                    {!cand && !sources.length && slotOrigin && <span className="ldm-peek-tag" style={{ color: slotOrigin.color }}>{layerKindWord(slotOrigin)} {slotOrigin.label}</span>}
                    {!cand && !sources.length && !slotOrigin && playOrigin && <span className="ldm-peek-tag" style={{ color: playOrigin.color }}>{layerTag(playOrigin)}</span>}
                    {t.album && <span className="ldm-peek-album">{t.album}</span>}
                    {playing && playing.id !== t.id && <span className="ldm-peek-dist">{distBetween(playing, t).toFixed(2)} away</span>}
                  </div>
                </div>
                {playing && playing.id !== t.id && (
                  <button className="ldm-peek-add" title="Sonic interpolation from the playing track"
                    aria-label="Sonic interpolation from the playing track"
                    onClick={(e) => { e.stopPropagation(); onInterpolate(playing, t); setDetailMode('hidden'); }}>
                    <IconTilde size={18} />
                  </button>
                )}
                <button className={'ldm-peek-add ' + (inPl ? 'is-active' : '')}
                  title={inPl ? 'Remove from playlist' : 'Add to playlist'} aria-label={inPl ? 'Remove from playlist' : 'Add to playlist'}
                  onClick={(e) => { e.stopPropagation(); if (inPl) { const slot = playlistById.get(t.id); if (slot) removeFromPlaylist(slot.id); } else (cand ? insertCandidate(t) : addToPlaylist(t)); }}>
                  {inPl ? <IconCheck size={18} /> : <IconListPlus size={18} />}
                </button>
              </div>
            )}>
            <div className="ldm-detail-sources">
              {cand && <span className="lc-source-tag" style={{ borderColor: CANDIDATE_COLOR, color: CANDIDATE_COLOR }}>interpolation</span>}
              {sources.map((l) => (<span key={l.id} className="lc-source-tag" style={{ borderColor: l.color, color: l.color }}><span className="ld-layer-swatch" style={{ background: l.color }} />{layerTag(l)}</span>))}
              {!sources.length && !cand && slotOrigin && (<span className="lc-source-tag" style={{ borderColor: slotOrigin.color, color: slotOrigin.color }}>{layerKindWord(slotOrigin)} {slotOrigin.label}</span>)}
              {!sources.length && !cand && !slotOrigin && playOrigin && (<span className="lc-source-tag" style={{ borderColor: playOrigin.color, color: playOrigin.color }}><span className="ld-layer-swatch" style={{ background: playOrigin.color }} />{layerTag(playOrigin)}</span>)}
              {playing && playing.id !== t.id && <span className="ld-detail-dist" style={{ marginLeft: 'auto' }}>{distBetween(playing, t).toFixed(2)} away</span>}
            </div>
            <div className="ldm-detail-title">{t.title}</div>
            <div className="ldm-detail-sub">{t.artist} — {t.album}{t.duration ? ` · ${fmtTime(t.duration)}` : ''}</div>
            {t.track_url && (<a className="ld-detail-url" href={t.track_url} target="_blank" rel="noopener noreferrer" style={{ marginTop: 6 }}><IconExternal size={12} />{prettyUrl(t.track_url)}</a>)}
            <div className="ldm-detail-fb"><FeedbackPills track={t} value={labelsByTrackId[t.id]} onLabel={labelTrack} source={sourceTagFor(t)} /></div>
            {/* No Add button here — the peek header's add button covers it. */}
            <div className="ldm-detail-actions">
              <button className="ldm-act is-primary" onClick={() => playTrack(t)}><svg viewBox="0 0 24 24" fill="currentColor" width="18" height="18"><path d="M8 5v14l11-7z" /></svg> Play</button>
              <button className="ldm-act" onClick={() => { addSeedLayer('similar', t); setDetailMode('peek'); }}><IconSimilar size={16} /> Similar</button>
              <button className="ldm-act" onClick={() => { addSeedLayer('dissimilar', t); setDetailMode('peek'); }}><IconDissimilar size={16} /> Dissimilar</button>
            </div>
          </PeekSheet>
        ); })()}

      {/* ===== DOCK — now-playing strip + tab bar ===== */}
      <div className="ldm-dock" ref={dockRef}>
        {/* The player bar is always present — it shows a muted placeholder when
            nothing is cued, so the dock never collapses to just the tabs. */}
        <div className={'ldm-strip ' + (playing ? '' : 'is-empty')} onClick={() => { if (playing) setSheet('now'); }}>
          <div className="ldm-strip-prog"><span style={{ width: `${(playing ? progress : 0) * 100}%` }} /></div>
          <div className="ldm-player-art"><img src={`${ASSET}assets/artwork.svg`} alt="" /></div>
          <div className="ldm-player-info">
            {/* Title only — artist/album live in the detail bar above, so the
                player bar stays distinct from it. */}
            {playing
              ? <div className="ldm-player-title">{playing.title}</div>
              : <><div className="ldm-player-title">Nothing playing</div><div className="ldm-player-sub">Tune a track on the map</div></>}
          </div>
          <div className="ldm-strip-ctl">
            {/* Prev/next are always present; disabled (grayed) unless the current
                track is in the playlist, where step() walks the playlist. */}
            <button className="ldm-strip-nav" aria-label="Previous" disabled={!stripNav} onClick={(e) => { e.stopPropagation(); step(-1); }}><svg viewBox="0 0 24 24" fill="currentColor" width="22" height="22"><path d="M6 6h2v12H6zm3.5 6l8.5 6V6z" /></svg></button>
            <button className="ldm-player-play" disabled={!playing} onClick={(e) => { e.stopPropagation(); togglePlay(); }}>{isPlaying ? pauseSvg : playSvg}</button>
            <button className="ldm-strip-nav" aria-label="Next" disabled={!stripNav} onClick={(e) => { e.stopPropagation(); step(1); }}><svg viewBox="0 0 24 24" fill="currentColor" width="22" height="22"><path d="M6 18l8.5-6L6 6v12zM16 6v12h2V6h-2z" /></svg></button>
          </div>
        </div>
        <nav className="ldm-tabbar">
          <button className={'ldm-tab ' + (view === 'map' ? 'is-active' : '')} onClick={() => { setView('map'); setSheet(null); }}>
            <svg viewBox="0 0 24 24" width="22" height="22" fill="currentColor"><circle cx="12" cy="12" r="2.5" /><circle cx="12" cy="12" r="6" fill="none" stroke="currentColor" strokeWidth="1.4" /><circle cx="12" cy="12" r="10" fill="none" stroke="currentColor" strokeWidth="1.4" opacity="0.5" /></svg>
            <span>Map</span>
          </button>
          <button className={'ldm-tab ' + (view === 'list' ? 'is-active' : '')} onClick={() => { setView('list'); setSheet(null); }}>
            <svg viewBox="0 0 24 24" width="22" height="22" fill="currentColor"><rect x="3" y="5" width="18" height="2" rx="1" /><rect x="3" y="11" width="18" height="2" rx="1" /><rect x="3" y="17" width="18" height="2" rx="1" /></svg>
            <span>List</span>
          </button>
          <button className={'ldm-tab ' + (sheet === 'search' ? 'is-active' : '')} onClick={() => setSheet('search')}>
            <IconSearch size={20} /><span>Search</span>
          </button>
          <button className={'ldm-tab ' + (sheet === 'playlist' ? 'is-active' : '')} onClick={() => setSheet('playlist')}>
            <span className="ldm-tab-iconwrap"><IconListPlus size={20} />{playlistTracks.length > 0 && <span className="ldm-tab-badge">{playlistTracks.length}</span>}</span>
            <span>Playlist</span>
          </button>
          <button className={'ldm-tab ' + (aboutOpen ? 'is-active' : '')} onClick={() => setAboutOpen(true)}>
            <span className="ldm-tab-logo"><MascotSmall size={18} /></span>
            <span>About</span>
          </button>
        </nav>
      </div>

      {/* ===== ABOUT MODAL (shared with desktop) ===== */}
      {aboutOpen && <AboutModal onClose={() => setAboutOpen(false)} />}

      {/* ===== MODAL SHEETS ===== */}
      {sheet && <div className={'ldm-scrim ' + (sheet === 'search' || sheet === 'playlist' ? 'is-clear' : '')} onClick={() => setSheet(null)} />}

      {sheet === 'search' && (
        <Sheet onClose={() => setSheet(null)} style={{ maxHeight: kbInset ? `${Math.max(240, window.innerHeight - kbInset - 56)}px` : '70%', bottom: kbInset }}>
          <input ref={searchInputRef} className="ldm-sheet-input" placeholder="Describe a mood…" value={vibeQuery}
            onChange={(e) => setVibeQuery(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter' && vibeQuery.trim()) addVibe(vibeQuery); }} />
          <div className="ldm-sheet-scroll">
            <div className="lo-eyebrow" style={{ marginBottom: 8 }}>{vibeQuery ? `Matching “${vibeQuery}”` : 'Suggested vibes'}</div>
            <div className="ldm-chipwrap">
              {vibeSuggestions.map((v) => (
                <button key={v} className="el-chip" onClick={() => addVibe(v)}>+ {v}</button>
              ))}
              {vibeQuery && !vibeSuggestions.some((v) => v.toLowerCase() === vibeQuery.toLowerCase()) && (
                <button className="el-chip" onClick={() => addVibe(vibeQuery)}>+ Add “{vibeQuery}”</button>
              )}
            </div>
            {layers.length > 0 && (<>
              <div className="lo-eyebrow" style={{ margin: '18px 0 8px' }}>Active searches</div>
              <div className="ldm-layer-manage">
                {displayLayers.map((l) => (
                  <div key={l.id} className="ldm-layer-manage-row">
                    <span className="ldm-chip-swatch" style={{ background: l.color, width: 10, height: 10 }} />
                    <div className="ldm-lm-text">
                      <span className="ldm-lm-label">{layerKindWord(l)} · {l.label}</span>
                      {l.enhancedQuery && <span className="ldm-lm-enh">✨ {l.enhancedQuery}</span>}
                      {l.seedTrack && (
                        <button className="ldm-lm-seed" onClick={() => { openDetail(l.seedTrack.id); setSheet(null); }}>
                          {layerTag(l)} {l.seedTrack.title} <span className="ldm-lm-seed-artist">— {l.seedTrack.artist}</span>
                        </button>
                      )}
                    </div>
                    <button className="ldm-lm-btn" onClick={() => toggleLayerVisible(l.id)} style={l.visible ? null : { opacity: 0.5 }}>{l.visible ? <IconEye size={15} /> : <IconEyeOff size={15} />}</button>
                    <button className="ldm-lm-btn" onClick={() => removeLayer(l.id)}><IconClose size={13} /></button>
                  </div>
                ))}
              </div>
            </>)}
          </div>
        </Sheet>
      )}

      {sheet === 'now' && playing && (
        <Sheet onClose={() => setSheet(null)} style={{ maxHeight: '92%' }}>
          <div className="ldm-sheet-scroll">
            <div className="ldm-now-art"><img src={`${ASSET}assets/artwork.svg`} alt="" /></div>
            <div className="lo-eyebrow-strong">Now playing</div>
            <div className="ldm-now-title">{playing.title}</div>
            <div className="ldm-now-sub">{playing.artist} — {playing.album}</div>
            <div style={{ marginTop: 14 }}><Waveform width={350} height={40} progress={progress} bars={56} seed={(playingId || 'x').charCodeAt(0) + 3} peaks={peaks} onSeek={seekTo} /></div>
            <div className="ldm-now-times"><span>{fmtTime(playingTotal * progress)}</span><span>{fmtTime(playingTotal)}</span></div>
            <div className="ldm-now-transport">
              <button className="ldm-now-tbtn" onClick={() => step(-1)}><svg viewBox="0 0 24 24" fill="currentColor" width="18" height="18"><path d="M6 6h2v12H6zm3.5 6l8.5 6V6z" /></svg></button>
              <button className="ldm-now-tbtn is-play" onClick={togglePlay}>{isPlaying ? <svg viewBox="0 0 24 24" fill="white" width="22" height="22"><path d="M6 5h4v14H6zm8 0h4v14h-4z" /></svg> : <svg viewBox="0 0 24 24" fill="white" width="22" height="22"><path d="M8 5v14l11-7z" /></svg>}</button>
              <button className="ldm-now-tbtn" onClick={() => step(1)}><svg viewBox="0 0 24 24" fill="currentColor" width="18" height="18"><path d="M6 18l8.5-6L6 6v12zM16 6v12h2V6h-2z" /></svg></button>
            </div>
            <div className="ldm-detail-fb"><FeedbackPills track={playing} value={labelsByTrackId[playing.id]} onLabel={labelTrack} source={sourceTagFor(playing)} /></div>
          </div>
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
                    <div className="ldm-pl-info" onClick={() => { hideAllLayers(); playTrack(t); }}><div className="ldm-pl-title">{t.title}</div><div className="ldm-pl-sub">{t.artist}{slot.dist != null ? ` · ${slot.dist.toFixed(2)} step` : ''}</div></div>
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

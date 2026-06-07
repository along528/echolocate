// Shared SVG bits, ported from the prototype to ES modules.
import React from 'react';

export function MascotSmall({ size = 28 }) {
  return (
    <img
      src={`${import.meta.env.BASE_URL}assets/logo.svg`}
      alt=""
      width={size}
      height={size * 1.2}
      style={{ display: 'block', filter: 'drop-shadow(0 2px 6px rgba(99,102,241,0.35))' }}
    />
  );
}

export function Wordmark({ size = 'lg' }) {
  const fs = size === 'sm' ? '0.95rem' : size === 'md' ? '1.15rem' : '1.5rem';
  const px = size === 'sm' ? 22 : size === 'md' ? 26 : 36;
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 10 }}>
      <MascotSmall size={px} />
      <span className="el-h1" style={{ fontSize: fs, letterSpacing: '-0.015em' }}>EchoLocate</span>
    </span>
  );
}

// Waveform — still a deterministic pseudo-envelope (real peaks tracked in TODO.md);
// `progress` is driven by the real <audio> element. When `onSeek` is supplied
// the bar becomes a scrubber: clicking (or dragging) navigates to that fraction
// of the track.
export function Waveform({ width = 320, height = 36, progress = 0.32, accent = 'var(--el-indigo-500)', muted = 'rgba(255,255,255,0.12)', bars = 64, seed = 7, onSeek = null }) {
  const heights = React.useMemo(() => {
    const arr = [];
    let s = seed;
    for (let i = 0; i < bars; i++) {
      s = (s * 9301 + 49297) % 233280;
      const env = Math.sin((i / bars) * Math.PI);
      const noise = (s / 233280) * 0.6 + 0.4;
      arr.push(Math.max(0.12, env * noise));
    }
    return arr;
  }, [bars, seed]);

  const gap = 2;
  const barW = (width - gap * (bars - 1)) / bars;
  const playedIdx = Math.round(progress * bars);

  const seekFromEvent = (e) => {
    if (!onSeek) return;
    const rect = e.currentTarget.getBoundingClientRect();
    const frac = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
    onSeek(frac);
  };

  return (
    <svg
      width={width} height={height} viewBox={`0 0 ${width} ${height}`}
      className={onSeek ? 'lo-wave-seek' : undefined}
      role={onSeek ? 'slider' : undefined}
      aria-label={onSeek ? 'Seek' : undefined}
      aria-valuenow={onSeek ? Math.round(progress * 100) : undefined}
      onClick={onSeek ? seekFromEvent : undefined}
      onPointerDown={onSeek ? (e) => { e.currentTarget.setPointerCapture?.(e.pointerId); seekFromEvent(e); } : undefined}
      onPointerMove={onSeek ? (e) => { if (e.buttons === 1) seekFromEvent(e); } : undefined}
    >
      {/* full-height hit target so thin bars + gaps are all clickable */}
      {onSeek && <rect x={0} y={0} width={width} height={height} fill="transparent" />}
      {heights.map((h, i) => {
        const bh = h * height;
        const x = i * (barW + gap);
        const y = (height - bh) / 2;
        return (
          <rect key={i} x={x} y={y} width={barW} height={bh} rx={Math.min(barW / 2, 1.5)}
            fill={i < playedIdx ? accent : muted} style={{ pointerEvents: 'none' }} />
        );
      })}
      {/* playhead */}
      {onSeek && (
        <rect x={Math.max(0, Math.min(width - 2, progress * width - 1))} y={0} width={2} height={height}
          rx={1} fill="var(--el-fg-primary)" opacity={0.85} style={{ pointerEvents: 'none' }} />
      )}
    </svg>
  );
}

// Distance chip — value 0 = identical, 1 = very far.
export function DistanceChip({ value, kind = 'indigo' }) {
  const pct = Math.max(0, Math.min(1, value ?? 0));
  const isAmber = kind === 'amber';
  const fill = isAmber ? 'var(--el-yellow-500)' : 'var(--el-indigo-500)';
  return (
    <div className="el-dist">
      <div className="el-dist-track" aria-hidden="true">
        <div className="el-dist-fill" style={{ width: `${(1 - pct) * 100}%`, background: fill }} />
      </div>
      <span className="el-dist-num">{pct.toFixed(2)}</span>
    </div>
  );
}

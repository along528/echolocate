// Shared, view-agnostic helpers for Sonar — used by the useSonar hook and by
// both the desktop and mobile views so there's no duplicated logic. Pure
// functions + the two small reused components (FeedbackPills, SourceLink).
//
// Note: view-specific geometry (dotPos / VW / VH / PAD) deliberately lives in
// each view, since desktop is landscape (760×540) and mobile is portrait
// (390×780). Only the unitless coords math (coordsOf / distBetween) is shared.
import React from 'react';
import { IconCheck, IconTilde, IconX, IconExternal } from './icons.jsx';

// Per-search layer colors. A search's color is its identity everywhere (pill,
// dots, list rows). White is reserved for interpolation candidates. Eight
// evenly-spaced hues of similar luminance on the dark bg, with a deliberate
// gap around brand indigo (#6366f1) so no layer reads as the playlist color.
export const LAYER_COLORS = [
  '#22d3ee', // cyan
  '#34d399', // emerald
  '#a3e635', // lime
  '#fbbf24', // amber
  '#fb923c', // orange
  '#f87171', // coral
  '#f472b6', // pink
  '#c084fc', // violet
];
export const CANDIDATE_COLOR = '#ffffff';
export const FALLBACK_COLOR = '#94a3b8';

export function fmtTime(s) {
  if (s == null || isNaN(s)) return '0:00';
  const m = Math.floor(s / 60);
  const r = Math.floor(s % 60);
  return `${m}:${r.toString().padStart(2, '0')}`;
}

// Deterministic fallback coordinate from an id, so tracks lacking a projection
// still land somewhere stable rather than piling up at the origin.
export function hashCoord(id) {
  let h = 2166136261;
  for (let i = 0; i < id.length; i++) {
    h ^= id.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  const a = ((h >>> 0) % 1000) / 1000;
  const b = ((Math.imul(h, 2654435761) >>> 0) % 1000) / 1000;
  return [a, b];
}

export function coordsOf(t) {
  if (t && typeof t.x === 'number' && typeof t.y === 'number') return [t.x, t.y];
  return hashCoord(t?.id || '');
}

export function distBetween(a, b) {
  if (!a || !b) return 0;
  const [ax, ay] = coordsOf(a);
  const [bx, by] = coordsOf(b);
  return Math.min(1, Math.sqrt((ax - bx) ** 2 + (ay - by) ** 2));
}

export const distChipValue = (t) => (typeof t.similarity === 'number' ? 1 - t.similarity : 0);
export const layerTag = (l) => (l.kind === 'similar' ? '≈ ' : l.kind === 'dissimilar' ? '≠ ' : '') + l.label;
export const layerKindWord = (l) => (l.kind === 'similar' ? 'Similar to' : l.kind === 'dissimilar' ? 'Dissimilar to' : 'Vibe');

// Shorten a URL to "host/…/last-segment" for inline display; falls back to the raw string.
export const prettyUrl = (url) => {
  try {
    const u = new URL(url);
    const seg = u.pathname.split('/').filter(Boolean).pop();
    return u.hostname.replace(/^www\./, '') + (seg ? `/${seg}` : '');
  } catch { return url; }
};

// 3-way training-signal feedback (relevant / borderline / wrong). Styled to
// match the legacy frontend's "Match" pill exactly. Fires Labels.recordLabel.
export function FeedbackPills({ track, value, onLabel }) {
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
export function SourceLink({ track, className = '' }) {
  if (!track || !track.track_url) return null;
  return (
    <a className={'ld-srclink ' + className} href={track.track_url} target="_blank" rel="noopener noreferrer"
      onClick={(e) => e.stopPropagation()} title="Open source (Free Music Archive)">
      <IconExternal size={13} />
    </a>
  );
}

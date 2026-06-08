// Track-action icons, ported verbatim from the legacy frontend
// (frontend/components.js TRACK_ICONS) so sonar uses the *same* glyphs for
// add-to-playlist / similar / dissimilar / feedback as the old UI.
import React from 'react';

const base = {
  viewBox: '0 0 24 24',
  fill: 'none',
  stroke: 'currentColor',
  strokeLinecap: 'round',
  strokeLinejoin: 'round',
  'aria-hidden': true,
};

export function IconListPlus({ size = 16 }) {
  return (
    <svg width={size} height={size} {...base} strokeWidth="1.75">
      <path d="M11 12H3" /><path d="M16 6H3" /><path d="M16 18H3" /><path d="M18 9v6" /><path d="M21 12h-6" />
    </svg>
  );
}

export function IconSimilar({ size = 16 }) {
  return (
    <svg width={size} height={size} {...base} strokeWidth="1.75">
      <path d="M2 12h2" /><path d="M6 8v8" /><path d="M10 5v14" /><path d="M14 8v8" /><path d="M18 11v2" /><path d="M22 12h-2" />
    </svg>
  );
}

export function IconDissimilar({ size = 16 }) {
  return (
    <svg width={size} height={size} {...base} strokeWidth="1.75">
      <path d="M3 12h2" /><path d="M7 9v6" /><path d="M11 6v12" /><path d="M15 9v6" /><path d="M19 11v2" /><path d="M4 20 20 4" />
    </svg>
  );
}

export function IconCheck({ size = 16 }) {
  return (
    <svg width={size} height={size} {...base} strokeWidth="2">
      <polyline points="20 6 9 17 4 12" />
    </svg>
  );
}

export function IconTilde({ size = 16 }) {
  return (
    <svg width={size} height={size} {...base} strokeWidth="2">
      <path d="M3 13c1-2 2.5-3 4-3s2.5 1.5 4.5 3 3 3 4.5 3 3-1 5-3" />
    </svg>
  );
}

export function IconX({ size = 16 }) {
  return (
    <svg width={size} height={size} {...base} strokeWidth="2">
      <path d="M18 6 6 18" /><path d="m6 6 12 12" />
    </svg>
  );
}

export function IconClose({ size = 14 }) {
  return (
    <svg width={size} height={size} {...base} strokeWidth="2.25">
      <path d="M18 6 6 18" /><path d="m6 6 12 12" />
    </svg>
  );
}

// Small "open external" arrow used as the icon-only source link next to titles.
export function IconExternal({ size = 13 }) {
  return (
    <svg width={size} height={size} {...base} strokeWidth="2">
      <path d="M7 17 17 7" /><path d="M7 7h10v10" />
    </svg>
  );
}

export function IconEye({ size = 15 }) {
  return (
    <svg width={size} height={size} {...base} strokeWidth="1.75">
      <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7Z" /><circle cx="12" cy="12" r="3" />
    </svg>
  );
}

export function IconEyeOff({ size = 15 }) {
  return (
    <svg width={size} height={size} {...base} strokeWidth="1.75">
      <path d="M9.9 4.2A10.9 10.9 0 0 1 12 4c6.5 0 10 7 10 7a18 18 0 0 1-3 3.7" />
      <path d="M6.6 6.6A18 18 0 0 0 2 11s3.5 7 10 7a10.9 10.9 0 0 0 4.4-.9" />
      <path d="m2 2 20 20" />
    </svg>
  );
}

export function IconSolo({ size = 15 }) {
  // "show only this" — a single highlighted dot
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
      <circle cx="12" cy="12" r="4" />
      <circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" strokeWidth="1.5" opacity="0.45" />
    </svg>
  );
}

export function IconUp({ size = 14 }) {
  return (
    <svg width={size} height={size} {...base} strokeWidth="2"><path d="m6 15 6-6 6 6" /></svg>
  );
}

export function IconDown({ size = 14 }) {
  return (
    <svg width={size} height={size} {...base} strokeWidth="2"><path d="m6 9 6 6 6-6" /></svg>
  );
}

export function IconPlus({ size = 14 }) {
  return (
    <svg width={size} height={size} {...base} strokeWidth="2"><path d="M12 5v14" /><path d="M5 12h14" /></svg>
  );
}

export function IconZoomIn({ size = 16 }) {
  return (
    <svg width={size} height={size} {...base} strokeWidth="2">
      <circle cx="11" cy="11" r="7" /><path d="m21 21-4.3-4.3" /><path d="M11 8v6" /><path d="M8 11h6" />
    </svg>
  );
}

export function IconZoomOut({ size = 16 }) {
  return (
    <svg width={size} height={size} {...base} strokeWidth="2">
      <circle cx="11" cy="11" r="7" /><path d="m21 21-4.3-4.3" /><path d="M8 11h6" />
    </svg>
  );
}

export function IconRecenter({ size = 16 }) {
  return (
    <svg width={size} height={size} {...base} strokeWidth="2">
      <path d="M3 9V5a2 2 0 0 1 2-2h4" /><path d="M21 9V5a2 2 0 0 0-2-2h-4" />
      <path d="M3 15v4a2 2 0 0 0 2 2h4" /><path d="M21 15v4a2 2 0 0 1-2 2h-4" />
    </svg>
  );
}

export function IconInfo({ size = 14 }) {
  return (
    <svg width={size} height={size} {...base} strokeWidth="2">
      <circle cx="12" cy="12" r="9" /><path d="M12 16v-4" /><path d="M12 8h.01" />
    </svg>
  );
}

export function IconSearch({ size = 16 }) {
  return (
    <svg width={size} height={size} {...base} strokeWidth="2">
      <circle cx="11" cy="11" r="7" /><path d="m21 21-4.3-4.3" />
    </svg>
  );
}

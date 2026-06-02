# Sonar — deferred features

Things intentionally left out of the sonar map + list v1, with notes on
how to bring them in later.

## Per-track vibe chips
The prototype showed 2–3 "vibe" tag chips per track (tooltip, list rows, now-playing).
There is **no backend source** for discrete tags today — "vibes" are only query terms.
v1 omits per-track chips; the vibe tagger still drives search by joining vibes into the
semantic query.
- **Future:** classify each track against a fixed vibe vocabulary via CLAP similarity
  (text-anchor each vibe, take top-k per track), store as a column, return in responses.

## Track duration (M:SS) in the list
The list mockup shows a per-row duration. Duration is computed in
`embeddings/embedding_lib.py` but **dropped at DB-build time** (not a column).
v1 omits the list duration column; the now-playing total/elapsed time comes from the
real `<audio>` element instead.
- **Future:** add a `duration` column in a DB rebuild and surface it in track responses.

## Real waveform / peaks
`Waveform` still renders a deterministic pseudo-random envelope; only `progress` is real
(from the audio element).
- **Future:** precompute peaks (or analyze in-browser) and feed real amplitude data.

## Projection method
Coordinates currently come from a **PCA layout on the MERT `v_mid` vector**
(`embeddings/generate_projection.py` defaults: `--method pca --vector mid`). Axes are
the directions of maximum variance (not interpretable, but capture the dominant
sonic structure).
- **Future / alternative:** evaluate the `clap-axes` (interpretable semantic axes) or
  `umap` layouts. They write the same `x,y` columns and the same API contract, so it's a
  pipeline-only swap — no frontend/API changes.

## CSS consolidation
The prototype CSS is carried verbatim (`style.css` + `styles/layout-{a,c,d}.css`).
The handoff suggests consolidating the A/C class families into the component's own styles.

## Misc
- Sort control in the center header (mockup shows "distance ↓") is not yet wired.
- Mobile/responsive layout not yet adapted.

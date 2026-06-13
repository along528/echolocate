# Sonar — deferred features

Things intentionally left out of the sonar map + list v1, with notes on
how to bring them in later.

## Per-track vibe chips
The prototype showed 2–3 "vibe" tag chips per track (tooltip, list rows, now-playing).
There is **no backend source** for discrete tags today — "vibes" are only query terms.
v1 omits per-track chips; the vibe tagger still drives search by joining vibes into the
semantic query.
- **In progress:** classify each track against a fixed vibe vocabulary via CLAP similarity
  (text-anchor each vibe, take top-k per track), store as a column, return in responses.
  Tracked on its own branch/PR (`generate_vibes.py` + `vibes` column + `VibeChips`).

## Track duration (M:SS) in the list — **DONE** (needs DB rebuild to populate)
`generate_db.py` now carries `duration` through to a `duration` column (it was already in
the embedding JSONL), `generate_index_db.py` copies it into the baked index, and the
vector service returns it. The list rows / detail / mobile rows show `M:SS` when present.
Needs a DB rebuild + redeploy to populate (the now-playing total still comes from the
real `<audio>` element either way).

## Real waveform / peaks — **DONE**
`Waveform` (`svg-bits.jsx`) renders real amplitude `peaks` when supplied. `useSonar`
fetches the playing track's audio, decodes it via the Web Audio API, downsamples to
`WAVE_BUCKETS` peak amplitudes (cached per track id), and feeds them to the players in
both views. Falls back to the deterministic pseudo-envelope on any failure
(unsupported browser, CORS, decode error).

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
- ~~Mobile/responsive layout not yet adapted.~~ **Done:** a map-first mobile view
  ships (`SonarMobile.jsx`, `sonar-mobile.css`) from the `design_handoff_mobile`
  handoff. State/logic is now shared between desktop and mobile via the `useSonar`
  hook (`Sonar.jsx` is a responsive shell that renders `SonarDesktop` or
  `SonarMobile` by viewport width), so both share one playlist / layer set / player
  / audio element. Pure helpers + `FeedbackPills`/`SourceLink` live in
  `sonar-utils.jsx`. Mobile ships the desktop dot model only (layer colors); the
  prototype's mock-only `sonic`/`clusters`/`axes` variations were not ported.

## Click-to-probe: nearest across the whole corpus — **DONE** (desktop)
Implemented option (b): a `GET /map/nearest?x=&y=&source=` endpoint in vector-rs
returns the exact globally-nearest track to a clicked coordinate. On the desktop view,
clicking empty map space selects the nearest already-loaded track for instant feedback,
then probes the corpus via `/map/nearest` and selects/draws the true nearest (added to a
`probes` set in `useSonar`). A dimmed `/map/backdrop` field is rendered behind the
results in both views for spatial context.
- **Mobile:** the gesture model is reticle-tuning (pan to center the nearest dot), not
  tap-to-select, so click-to-probe is desktop-only for now. The backdrop field still
  renders on mobile for parity.

## Done (sonar feedback pass)
The following review suggestions are now implemented:
- Suggestions strip is always visible; layers have solo / hide (eye) / show-all /
  clear-all controls and an expanded color palette. Searching no longer
  auto-selects a track or a suggested chip.
- Track detail popup moved to a bar **above** the map (no longer overlaps dots);
  its actions are always visible. Clicking empty space drops an ✕ probe and
  selects the nearest x,y point.
- Map: zoom in/out/reset + ctrl-wheel, larger plot area (smaller margins),
  clickable-line affordance (midpoint ＋), "2D PCA of MERT v_mid" caption.
- Feedback buttons reuse the legacy "Match" pill styling; similar / dissimilar /
  add-to-playlist use the legacy Lucide icons. Source link is icon-only next to
  the title. Search origin is shown in list rows and now-playing.
- "Trail" renamed to "playlist"; reorderable (drag + up/down); no special "start"
  track. Dissimilar button added to the player. Waveform/progress is seekable.
- Interpolation candidates are clearable and constrained to FMA. Playlist tracks
  keep their map dot even when their layer is hidden/removed, and the layer can be
  restored from the playlist row.
- State persists across refresh (localStorage), the menu button opens an About
  modal, and suggested chips + the semantic-search results come from the Firestore
  cache (with a baked-in fallback list).

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
- ~~Mobile/responsive layout not yet adapted.~~ **Done:** a map-first mobile view
  ships (`SonarMobile.jsx`, `sonar-mobile.css`) from the `design_handoff_mobile`
  handoff. State/logic is now shared between desktop and mobile via the `useSonar`
  hook (`Sonar.jsx` is a responsive shell that renders `SonarDesktop` or
  `SonarMobile` by viewport width), so both share one playlist / layer set / player
  / audio element. Pure helpers + `FeedbackPills`/`SourceLink` live in
  `sonar-utils.jsx`. Mobile ships the desktop dot model only (layer colors); the
  prototype's mock-only `sonic`/`clusters`/`axes` variations were not ported.

## Click-to-probe: nearest across the whole corpus
Today the ✕ probe (click empty map space) selects the nearest track **already
loaded in the UI** — visible search-layer results, interpolation candidates, and
playlist tracks (`nearestTrack` in `Sonar.jsx`). It does not discover new tracks
at the clicked location.
- **Future:** support finding the true nearest track at any x,y. Either
  (a) client-side via a large `/map/backdrop` sample + `/tracks/by-ids` lookup
  (approximate; nearest within the sampled field, and would add a dimmed backdrop
  layer), or (b) a new `/map/nearest?x=&y=` endpoint in vector-rs for the exact
  globally-nearest track (Rust change + redeploy).

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

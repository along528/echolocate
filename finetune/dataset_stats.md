# FMA fine-tuning dataset — Phase 2 stats

Generated from `manifest.parquet` and the stage `*.meta.json` provenance files.

## Headline

- **Tracks:** 103,810
- **Chunks (10 s windows):** 311,430  (offsets [0, 10, 20])
- **(chunk, caption) training pairs:** 1,259,772
- **Tracks with LLM captions:** 124 (0.1%)
- **Tracks dropped (no caption):** 1,343

## Per-split

| split | tracks | chunks | (chunk,caption) pairs |
|---|---|---|---|
| training | 89,667 | 269,001 | 1,090,407 |
| validation | 7,377 | 22,131 | 88,017 |
| test | 6,766 | 20,298 | 81,348 |

## Captions

- **Source breakdown (caption instances over unique tracks):** template=419,553, llm=371
- **Words per caption:** min=1 p50=3 p90=5 max=14
- **Avg captions/track:** 4.05

## Leakage + holdout

- **Artist leakage before repair:** 0 artists
- **Album leakage before repair:** 669 albums
- **Repaired:** 122 components, 8141 tracks moved; **leakage after: 0**
- **Eval-holdout tracks pulled from train/val/test:** 238 of 238 judged (excluded from the manifest entirely)

## Corpus coverage (from metadata load)

| field | tracks | coverage |
|---|---|---|
| genres_leaf | 103,200 | 97.9% |
| genres_top | 103,200 | 97.9% |
| tags | 46,815 | 44.4% |
| decade | 71,413 | 67.8% |
| location | 69,339 | 65.8% |
| language | 14,758 | 14.0% |
| echonest_words | 12,826 | 12.2% |

- **Missing audio on disk (skipped):** 0

## Top leaf genres (unique tracks)

| genre | tracks |
|---|---|
| Experimental | 37,751 |
| Electronic | 33,878 |
| Rock | 32,696 |
| Instrumental | 14,777 |
| Pop | 13,515 |
| Folk | 12,617 |
| Punk | 9,210 |
| Avant-Garde | 8,604 |
| Hip-Hop | 8,254 |
| Noise | 7,173 |
| Ambient | 7,124 |
| Experimental Pop | 6,862 |
| Electroacoustic | 6,078 |
| Lo-Fi | 5,992 |
| Soundtrack | 5,838 |
| Ambient Electronic | 5,495 |
| Indie-Rock | 5,412 |
| International | 5,226 |
| Improv | 4,222 |
| Singer-Songwriter | 4,128 |
| Jazz | 4,098 |
| Classical | 4,055 |
| Garage | 3,537 |
| IDM | 3,448 |
| Field Recordings | 3,216 |

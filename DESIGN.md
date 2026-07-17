# Design decisions

The reasoning behind EchoLocate's non-obvious choices — what was considered, what was picked, and what the tradeoff costs. Newest-relevant first is not the ordering here; it follows the data path: storage → serving → models → UI.

## DuckDB + VSS instead of a dedicated vector database

**Decision:** Store embeddings in DuckDB with the [VSS extension](https://duckdb.org/docs/extensions/vss)'s HNSW indexes, rather than Qdrant/Weaviate/Milvus or Postgres+pgvector.

**Why:**

- **A single file is an artifact.** The entire index — vectors, HNSW graphs, and track metadata — is one `.duckdb` file that can be versioned, copied to GCS, committed as a test fixture (the 600-track sample index), and, critically, `COPY`'d into a container image. The baked-index architecture below is only possible because the store is an embeddable file, not a server.
- **Scale-to-zero economics.** A dedicated vector DB is another always-on service to run and pay for. DuckDB runs in-process inside the same Cloud Run container, so the whole system scales to zero (~$0–$0.10/user/day compute).
- **SQL where SQL helps.** Metadata filtering, joins against track info, and ad-hoc analysis during development are plain SQL in the same store as the vectors — no sync between a metadata DB and a vector index.

**Tradeoffs accepted:** The corpus is read-only at serve time; index updates are an offline rebuild (`generate_index_db.py`) plus a redeploy, not incremental upserts. That's the right shape for a music library that changes in batches, and would be the wrong shape for a write-heavy product. Recall/latency tuning knobs are also coarser than a dedicated engine's.

## Bake the index into the container image

**Decision:** Strip the ~23 GB full database down to a ~1.4 GB index (metadata + `v_mid` + `v_clap` + map coordinates + HNSW graphs) and `COPY` it into the Docker image as its own layer, instead of mounting the database from GCS.

**Why:** The first deployment served the full DB over a GCS FUSE mount. HNSW traversal is a random-I/O workload, and every page miss became a network round trip — cold starts hit **~250 s**. Alternatives considered:

- *Persistent disk / volume mounts* — Cloud Run's volume options still put the index behind a network filesystem, keep the cold-start problem in a milder form, and add infra to manage.
- *Loading from GCS at startup* — downloading 1.4 GB before serving traffic rebuilds the latency into every cold start.
- *Baking into the image* — Cloud Run gen2 streams container image blocks **lazily and on demand**, so the instance starts serving while index pages fault in from the image layer. Startup work (page-cache preload, HNSW warmup on both indexes, ONNX model load, client init) runs in parallel. Cold start: **~10–15 s**.

The image layer ordering makes this cheap to live with: the index is a separate layer placed before the binary, so code changes rebuild only the binary layer and the 1.4 GB layer stays cached.

**Tradeoffs accepted:** A fat image (index updates mean a rebuild + redeploy), and a hard ceiling on index size — this works at 1.4 GB and would need rethinking at 50 GB. Deploys stay fast in practice because `vector-rs-deploy` is idempotent: it compares the commit SHA and the GCS index generation against the serving revision and skips unchanged builds.

## Python → Rust rewrite, with the old service as a test oracle

**Decision:** Rewrite the original FastAPI/Python vector service in Rust (Axum), keeping the HTTP API, the DuckDB file, and the ONNX model identical.

**Why:** The Python service's cold start stacked interpreter startup, uvicorn init, and model-loading overhead on top of the I/O problem, and the GIL limited concurrent request handling. Rust removes the runtime tax entirely — the binary starts in milliseconds, and the remaining cold-start time is genuinely the index warmup, which can be parallelized precisely.

**The migration practice worth naming:** because the rewrite was API-compatible by design, the Python service stayed deployed as a **differential-testing oracle**. One verification script ([`vector-rs/scripts/verify_service.py`](vector-rs/scripts/verify_service.py)) ran the same requests against both services and compared behavior endpoint-by-endpoint before traffic cutover. The CLAP text encoder was held constant across both by exporting it once to ONNX ([`export_clap_text.py`](vector-rs/scripts/export_clap_text.py), which self-verifies torch↔ONNX max-abs-diff < 1e-4), so responses were comparable at the numeric level, not just structurally. After cutover, the Python service and the first-generation UI were archived to the [`legacy`](https://github.com/along528/echolocate/tree/legacy) branch.

**Tradeoffs accepted:** Rust's ML ecosystem is thinner — the CLAP text encoder runs via ONNX Runtime bindings rather than `transformers`, which is exactly why the export-parity check exists. Iteration on model-adjacent code is slower than in Python; that work stays in Python (`embeddings/`, `finetune/`) and only inference crosses the boundary.

## Two embedding models instead of one

**Decision:** Embed every track twice — [MERT](https://arxiv.org/abs/2306.00107) (768-dim) and [CLAP](https://arxiv.org/abs/2206.04769) (512-dim) — with separate HNSW indexes.

**Why:** The two models answer different questions, and neither answers both. MERT is trained by self-supervision on audio alone; its space encodes how a track *sounds*, which is what similarity, interpolation, and the sonar map's geometry need. CLAP is trained contrastively against text; its space is where a sentence like "warm analog synths" can land near audio, which is what semantic search needs — but its audio geometry is warped by language alignment and makes for worse audio-to-audio similarity. Using CLAP for everything would degrade the map and interpolation; using MERT for everything would make text search impossible.

**Tradeoffs accepted:** Double embedding cost in the offline pipeline, two vector columns and two HNSW graphs in the index (a size cost the baked-index budget has to carry), and results from the two spaces are not directly comparable — a search layer is either sonic or semantic, never blended (so far).

## PCA for the sonar map projection

**Decision:** The map's `x,y` coordinates are the first two principal components of the MERT `v_mid` embedding, min-max normalized ([`embeddings/generate_projection.py`](embeddings/generate_projection.py)).

**Why (and what was tried):** Three methods are implemented behind the same `x,y` contract, so swapping is a pipeline re-run with no frontend/API changes:

- **`clap-axes`** — interpretable, text-anchored axes (X: acoustic→synthetic, Y: dark→bright, each axis a difference of CLAP prompt-pole embeddings). Readable axes, but it projects the *CLAP* space while similarity search and interpolation operate in the *MERT* space — a map that disagrees with the geometry the engine actually searches.
- **`umap`** — tighter visual clusters via local-neighborhood preservation, but arbitrary axes, slower, and less stable under corpus changes.
- **`pca`** (shipped) — projects the same MERT space the engine searches, so map proximity and search results share one geometry; deterministic and stable across re-runs.

**Tradeoffs accepted:** PCA axes mean nothing nameable — the UI can't label them — and two components necessarily flatten most of a 768-dim space: distant map points can still be sonically close along dimensions PCA discarded. The click-to-probe interaction (`GET /map/nearest`) is deliberately defined in projection space, not embedding space, so the map stays honest about what it is: a navigation surface, not a claim that 2D distance equals sonic distance.

## Gemini query expansion in front of CLAP

**Decision:** Optionally rewrite terse user queries ("dreamy") into descriptive acoustic captions ("dreamy ambient textures with washed-out reverb…") with Gemini 2.5 Flash before CLAP-embedding them (`vector-rs/src/gemini.rs`).

**Why:** CLAP was trained on caption-style text; two-word queries sit far from its training distribution. The eval harness quantifies how load-bearing the expansion is: on the frozen baseline qrels, scoring the stored *expanded* queries yields **NDCG@10 ≈ 0.44**, while replaying the raw queries collapses it to **≈ 0.09** (see [`finetune/BASELINE.md`](finetune/BASELINE.md)). The labels live on the expanded retrieval path — expansion isn't a nicety, it's most of the retrieval quality on short queries.

**Tradeoffs accepted:** A network dependency and ~hundreds of ms in the query path (mitigated by a Firestore cache for suggested queries), plus nondeterminism in what a query "means" between expansions. Expansion is a per-request flag (`enhance`), so the raw path stays available and measurable.

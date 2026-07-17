# Firestore

Firestore configuration and security rules for Cloud Crate.

## Security Rules

`firestore.rules` defines access control for the default Firestore database:

- **`semantic_search_cache`** — public read-only. Contains pre-cached semantic search results to mask vector-rs cold start latency.
- All other collections — default deny.

## Deploy Rules

```bash
./deploy.sh
```

Uses `npx firebase-tools` (no global install required). Requires Firebase auth — run `npx -y firebase-tools login` first if needed.

## Related

- **`../sonar/populate_cache.py`** — populates `semantic_search_cache` by querying the deployed vector-rs service (the legacy frontend's equivalents live on the `legacy` branch)

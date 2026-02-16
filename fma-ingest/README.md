# FMA Dataset Ingestion

Ingest the 879GB FMA Full dataset into Google Cloud Storage.

Because the source server is in Switzerland and the file is massive, we use a **two-step process** for reliability:

1. **Transfer**: Use Google Storage Transfer Service to robustly download the zip to GCS.
2. **Extract**: Use a Cloud Run Job to unzip the file *within* GCS (region-local).

## Architecture

Extraction uses **ZIP central directory + GCS range reads** for maximum speed:

1. Reads ~10MB from the end of the zip to parse the file index
2. Lists existing files in GCS to find what's already extracted
3. Extracts only missing files — each as an independent parallel range read

This means **resume is instant** (no re-reading 879GB) and extraction is **fully parallel**.

## Prerequisites

- Google Cloud Project (`cloud-crate-485418`)
- GCS Bucket (`cloud-crate-vector-db`)
- `gcloud` CLI authenticated

## Step 1: Transfer Zip to GCS

Use Google's managed transfer service to download the 879GB zip file. This handles retries and resumes automatically.

```bash
# 1. Edit fma_urls.tsv if you want a different dataset size
# 2. Run the transfer script
./download_to_gcs.sh
```

Monitor the job in the [Google Cloud Console](https://console.cloud.google.com/storage/transfer).
Target: `gs://cloud-crate-vector-db/fma-source/fma_full.zip`

## Step 2: Extract to MP3s

Once the zip is in GCS, run the Cloud Run job to extract it.

```bash
# Deploy and start the extraction job
./deploy.sh
```

### Resume Capability

If the extraction job times out or fails, simply run it again.
The job reads the ZIP central directory (~10MB) and lists existing files — it only extracts what's missing. Resume setup takes seconds, not hours.

## Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `BUCKET_NAME` | Target GCS bucket | `cloud-crate-vector-db` |
| `ZIP_BLOB` | Source zip in bucket | `fma-source/fma_full.zip` |
| `PREFIX` | Extraction destination | `fma/fma_full/` |
| `MAX_WORKERS` | Concurrent extraction threads | `32` |

## Dataset Options

To change the dataset, update `fma_urls.tsv` (for Step 1) and `ZIP_BLOB`/`PREFIX` env vars in `deploy.sh` (for Step 2).

| Dataset | Size | URL |
|---------|------|-----|
| Small | 7.2 GB | `https://os.unil.cloud.switch.ch/fma/fma_small.zip` |
| Medium | 22 GB | `https://os.unil.cloud.switch.ch/fma/fma_medium.zip` |
| Large | 93 GB | `https://os.unil.cloud.switch.ch/fma/fma_large.zip` |
| Full | 879 GB | `https://os.unil.cloud.switch.ch/fma/fma_full.zip` |

**Note:** The byte size in `fma_urls.tsv` enables transfer verification. For `fma_full.zip`, `943642698636` bytes was retrieved via `curl -I` from the source server. If using a different dataset, update this value.

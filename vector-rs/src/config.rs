use std::env;

#[derive(Debug, Clone)]
pub struct Config {
    pub db_path: String,
    pub index_db_path: Option<String>,
    pub port: u16,
    pub gcp_project_id: Option<String>,
    pub gcp_location: String,
    pub gemini_model: String,
    pub clap_onnx_dir: String,
    pub cors_allow_origins: Option<String>,
    pub gcs_bucket_name: String,
    pub gcs_audio_prefix: String,
    pub labels_bucket: String,
    pub index_version: String,
    pub model_version: String,
    pub git_sha: String,
}

impl Config {
    pub fn from_env() -> Self {
        Self {
            db_path: env::var("DB_PATH").unwrap_or_else(|_| "cloudcrate.duckdb".into()),
            index_db_path: env::var("INDEX_DB_PATH").ok(),
            port: env::var("PORT")
                .ok()
                .and_then(|p| p.parse().ok())
                .unwrap_or(8080),
            gcp_project_id: env::var("GCP_PROJECT_ID")
                .or_else(|_| env::var("GOOGLE_CLOUD_PROJECT"))
                .ok(),
            gcp_location: env::var("GCP_LOCATION").unwrap_or_else(|_| "us-central1".into()),
            gemini_model: env::var("GEMINI_MODEL").unwrap_or_else(|_| "gemini-2.5-flash".into()),
            clap_onnx_dir: env::var("CLAP_ONNX_DIR")
                .unwrap_or_else(|_| "/app/clap_text_onnx".into()),
            cors_allow_origins: env::var("CORS_ALLOW_ORIGINS").ok(),
            gcs_bucket_name: env::var("GCS_BUCKET_NAME")
                .unwrap_or_else(|_| "cloud-crate-vector-db".into()),
            gcs_audio_prefix: env::var("GCS_AUDIO_PREFIX")
                .unwrap_or_else(|_| "fma/fma_full/fma_full".into()),
            labels_bucket: env::var("LABELS_BUCKET")
                .unwrap_or_else(|_| "cloud-crate-vector-db".into()),
            index_version: env::var("INDEX_VERSION").unwrap_or_else(|_| "unknown".into()),
            model_version: env::var("MODEL_VERSION")
                .unwrap_or_else(|_| "mert-v1-95m+clap-htsat".into()),
            git_sha: env::var("GIT_SHA").unwrap_or_else(|_| "unknown".into()),
        }
    }
}

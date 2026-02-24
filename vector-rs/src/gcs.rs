use google_cloud_storage::client::{Client, ClientConfig};
use google_cloud_storage::http::objects::download::Range;
use google_cloud_storage::http::objects::get::GetObjectRequest;

pub struct GcsClient {
    client: Client,
}

impl GcsClient {
    pub async fn new() -> Result<Self, Box<dyn std::error::Error + Send + Sync>> {
        let config = ClientConfig::default().with_auth().await?;
        let client = Client::new(config);
        Ok(Self { client })
    }

    pub async fn download_blob(
        &self,
        bucket: &str,
        object: &str,
    ) -> Result<Vec<u8>, Box<dyn std::error::Error + Send + Sync>> {
        let data = self
            .client
            .download_object(
                &GetObjectRequest {
                    bucket: bucket.to_string(),
                    object: object.to_string(),
                    ..Default::default()
                },
                &Range::default(),
            )
            .await?;
        Ok(data)
    }
}

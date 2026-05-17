use google_cloud_storage::client::{Client, ClientConfig};
use google_cloud_storage::http::objects::download::Range;
use google_cloud_storage::http::objects::get::GetObjectRequest;
use google_cloud_storage::http::objects::upload::{Media, UploadObjectRequest, UploadType};

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

    pub async fn upload_object(
        &self,
        bucket: &str,
        object: &str,
        bytes: Vec<u8>,
        content_type: &str,
    ) -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
        let mut media = Media::new(object.to_string());
        media.content_type = content_type.to_string().into();
        let upload_type = UploadType::Simple(media);
        let req = UploadObjectRequest {
            bucket: bucket.to_string(),
            ..Default::default()
        };
        self.client.upload_object(&req, bytes, &upload_type).await?;
        Ok(())
    }
}

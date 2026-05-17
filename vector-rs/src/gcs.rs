use google_cloud_storage::client::{Client, ClientConfig};
use google_cloud_storage::http::objects::download::Range;
use google_cloud_storage::http::objects::get::GetObjectRequest;
use google_cloud_storage::http::objects::list::ListObjectsRequest;
use google_cloud_storage::http::objects::upload::{Media, UploadObjectRequest, UploadType};

#[derive(Clone)]
pub struct GcsClient {
    client: Client,
}

#[derive(Debug, Clone)]
pub struct GcsObjectMeta {
    pub name: String,
    pub time_created: Option<chrono::DateTime<chrono::Utc>>,
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

    /// List every object under `prefix` (paginated internally).
    /// Returns name + time_created for each item.
    pub async fn list_objects(
        &self,
        bucket: &str,
        prefix: &str,
    ) -> Result<Vec<GcsObjectMeta>, Box<dyn std::error::Error + Send + Sync>> {
        let mut out = Vec::new();
        let mut page_token: Option<String> = None;
        loop {
            let req = ListObjectsRequest {
                bucket: bucket.to_string(),
                prefix: Some(prefix.to_string()),
                max_results: Some(1000),
                page_token: page_token.clone(),
                ..Default::default()
            };
            let resp = self.client.list_objects(&req).await?;
            if let Some(items) = resp.items {
                for o in items {
                    let tc = o.time_created.and_then(|t| {
                        chrono::DateTime::<chrono::Utc>::from_timestamp(
                            t.unix_timestamp(),
                            t.nanosecond(),
                        )
                    });
                    out.push(GcsObjectMeta { name: o.name, time_created: tc });
                }
            }
            match resp.next_page_token {
                Some(tok) if !tok.is_empty() => page_token = Some(tok),
                _ => break,
            }
        }
        Ok(out)
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

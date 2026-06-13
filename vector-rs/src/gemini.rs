use google_cloud_auth::credentials::{self, Credential};

pub struct GeminiClient {
    http: reqwest::Client,
    endpoint: String,
    credential: Credential,
}

impl GeminiClient {
    pub async fn new(project_id: &str, location: &str, model: &str) -> Result<Self, Box<dyn std::error::Error + Send + Sync>> {
        let credential = credentials::create_access_token_credential().await
            .map_err(|e| format!("Failed to create GCP credential: {e}"))?;

        let endpoint = format!(
            "https://{location}-aiplatform.googleapis.com/v1/projects/{project_id}/locations/{location}/publishers/google/models/{model}:generateContent"
        );

        Ok(Self {
            http: reqwest::Client::new(),
            endpoint,
            credential,
        })
    }

    pub async fn enhance_query(&self, raw_query: &str) -> Result<String, Box<dyn std::error::Error + Send + Sync>> {
        let token = self.credential.get_token().await
            .map_err(|e| format!("Failed to get token: {e}"))?;

        let body = serde_json::json!({
            "contents": [{
                "role": "user",
                "parts": [{ "text": format!("Input: '{raw_query}'") }]
            }],
            "systemInstruction": {
                "parts": [{ "text": "You are an expert audio engineer. Convert short user queries into detailed audio captions for a LAION-CLAP model. Describe instrumentation, mood, and texture in a single technical sentence under 30 words. Output ONLY the caption." }]
            },
            "generationConfig": {
                "temperature": 0.3,
                "maxOutputTokens": 60,
                "candidateCount": 1
            }
        });

        let resp = self
            .http
            .post(&self.endpoint)
            .bearer_auth(&token.token)
            .json(&body)
            .send()
            .await?;

        let status = resp.status();
        if !status.is_success() {
            let text = resp.text().await.unwrap_or_default();
            return Err(format!("Gemini API error {status}: {text}").into());
        }

        let json: serde_json::Value = resp.json().await?;
        let expanded = json["candidates"][0]["content"]["parts"][0]["text"]
            .as_str()
            .unwrap_or(raw_query)
            .trim()
            .to_string();

        Ok(expanded)
    }
}

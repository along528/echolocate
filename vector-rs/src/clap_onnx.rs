use ort::session::Session;
use ort::value::Tensor;
use std::path::Path;
use std::sync::Mutex;
use tokenizers::Tokenizer;

pub struct ClapOnnxModel {
    session: Mutex<Session>,
    tokenizer: Tokenizer,
}

impl ClapOnnxModel {
    pub fn load(onnx_dir: &str) -> Result<Self, Box<dyn std::error::Error + Send + Sync>> {
        let onnx_path = Path::new(onnx_dir).join("clap_text.onnx");
        let tokenizer_path = Path::new(onnx_dir).join("tokenizer.json");

        tracing::info!("Loading CLAP ONNX model from {onnx_dir}...");

        let session = Session::builder()?
            .with_intra_threads(1)?
            .commit_from_file(&onnx_path)?;

        let mut tokenizer = Tokenizer::from_file(&tokenizer_path)
            .map_err(|e| format!("Failed to load tokenizer: {e}"))?;

        tokenizer
            .with_padding(Some(tokenizers::PaddingParams::default()));
        tokenizer
            .with_truncation(Some(tokenizers::TruncationParams {
                max_length: 512,
                ..Default::default()
            }))
            .map_err(|e| format!("Failed to set truncation: {e}"))?;

        tracing::info!("CLAP ONNX model loaded successfully.");
        Ok(Self { session: Mutex::new(session), tokenizer })
    }

    pub fn encode_text(&self, text: &str) -> Result<Vec<f32>, Box<dyn std::error::Error + Send + Sync>> {
        let encoding = self
            .tokenizer
            .encode(text, true)
            .map_err(|e| format!("Tokenization failed: {e}"))?;

        let input_ids: Vec<i64> = encoding.get_ids().iter().map(|&id| id as i64).collect();
        let attention_mask: Vec<i64> = encoding.get_attention_mask().iter().map(|&m| m as i64).collect();

        let seq_len = input_ids.len();

        let input_ids_tensor = Tensor::from_array(([1, seq_len], input_ids.into_boxed_slice()))?;
        let attention_mask_tensor = Tensor::from_array(([1, seq_len], attention_mask.into_boxed_slice()))?;

        let mut session = self.session.lock().map_err(|e| format!("Session lock poisoned: {e}"))?;
        let outputs = session.run(ort::inputs![
            "input_ids" => input_ids_tensor,
            "attention_mask" => attention_mask_tensor,
        ])?;

        let text_features = outputs[0]
            .try_extract_tensor::<f32>()?;

        // Output shape is (1, 512) — take the first row
        let embedding: Vec<f32> = text_features.1.iter().copied().collect();

        Ok(embedding)
    }
}

use duckdb::{Connection, Result};
use std::sync::Mutex;

/// Open a read-only DuckDB connection and load the VSS extension.
pub fn get_connection(db_path: &str) -> Result<Connection> {
    let conn = Connection::open_with_flags(
        db_path,
        duckdb::Config::default()
            .access_mode(duckdb::AccessMode::ReadOnly)?,
    )?;
    conn.execute_batch("INSTALL vss; LOAD vss; SET hnsw_enable_experimental_persistence = true;")?;
    Ok(conn)
}

/// A simple connection pool for DuckDB. Each connection has VSS pre-loaded.
pub struct DbPool {
    db_path: String,
    pool: Mutex<Vec<Connection>>,
}

impl DbPool {
    /// Create a new pool with `size` pre-initialized connections.
    pub fn new(db_path: &str, size: usize) -> Result<Self> {
        let mut conns = Vec::with_capacity(size);
        for _ in 0..size {
            conns.push(get_connection(db_path)?);
        }
        Ok(Self {
            db_path: db_path.to_string(),
            pool: Mutex::new(conns),
        })
    }

    /// Get a connection from the pool, or create a new one if empty.
    pub fn get(&self) -> Result<Connection> {
        let mut pool = self.pool.lock().unwrap();
        if let Some(conn) = pool.pop() {
            Ok(conn)
        } else {
            drop(pool);
            get_connection(&self.db_path)
        }
    }

    /// Return a connection to the pool.
    pub fn put(&self, conn: Connection) {
        let mut pool = self.pool.lock().unwrap();
        pool.push(conn);
    }
}

/// Build a distance expression. When `use_hnsw` is false, wraps the call so
/// the HNSW optimizer cannot pattern-match it, forcing a sequential scan.
pub fn dist_expr(col: &str, vec_literal: &str, use_hnsw: bool) -> String {
    if use_hnsw {
        tracing::debug!("query mode: HNSW index ({col})");
        format!("array_cosine_distance({col}, {vec_literal})")
    } else {
        tracing::info!("query mode: brute-force scan ({col})");
        format!("(0.0 + array_cosine_distance({col}, {vec_literal}))")
    }
}

/// Return the per-source table name for HNSW-indexed queries.
/// For "all", returns the union view (no HNSW, used for text search / sample).
pub fn table_for_source(source: &str) -> &str {
    match source {
        "library" => "tracks_library",
        "fma" => "tracks_fma",
        _ => "tracks",
    }
}

/// Extract a FLOAT[] column value as Vec<f32> from a DuckDB row.
/// DuckDB returns list columns as duckdb::types::Value::List.
pub fn value_to_vec_f32(val: &duckdb::types::Value) -> Vec<f32> {
    let items = match val {
        duckdb::types::Value::List(items) => items,
        duckdb::types::Value::Array(items) => items,
        other => {
            tracing::warn!("Unexpected vector Value variant: {:?}", std::mem::discriminant(other));
            return vec![];
        }
    };
    items
        .iter()
        .map(|v| match v {
            duckdb::types::Value::Float(f) => *f,
            duckdb::types::Value::Double(d) => *d as f32,
            _ => 0.0,
        })
        .collect()
}

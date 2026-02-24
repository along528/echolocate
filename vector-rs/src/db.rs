use duckdb::{Connection, Result};

/// Open a read-only DuckDB connection and load the VSS extension.
pub fn get_connection(db_path: &str) -> Result<Connection> {
    let conn = Connection::open_with_flags(
        db_path,
        duckdb::Config::default()
            .access_mode(duckdb::AccessMode::ReadOnly)?,
    )?;
    conn.execute_batch("INSTALL vss; LOAD vss;")?;
    Ok(conn)
}

/// Extract a FLOAT[] column value as Vec<f32> from a DuckDB row.
/// DuckDB returns list columns as duckdb::types::Value::List.
pub fn value_to_vec_f32(val: &duckdb::types::Value) -> Vec<f32> {
    match val {
        duckdb::types::Value::List(items) => items
            .iter()
            .map(|v| match v {
                duckdb::types::Value::Float(f) => *f,
                duckdb::types::Value::Double(d) => *d as f32,
                _ => 0.0,
            })
            .collect(),
        _ => vec![],
    }
}

//! Read path for SearchEvent / LabelEvent records stored in GCS by `labels.rs`.
//!
//! Layout in the bucket:
//!   labels/search_events/YYYY-MM-DD/{search_id}.json
//!   labels/label_events/YYYY-MM-DD/{label_id}.json
//!
//! Listing returns name + GCS time_created (monotonic, close to event timestamp).
//! Sorting and pagination are done by time_created at list time; the in-payload
//! `timestamp` field is what the UI displays.

use std::sync::Arc;

use axum::extract::{Query, State};
use axum::Json;
use chrono::{DateTime, Duration, NaiveDate, Utc};
use serde::Deserialize;
use serde_json::{json, Value};
use tokio::task::JoinSet;

use crate::error::AppError;
use crate::gcs::{GcsClient, GcsObjectMeta};
use crate::AppState;

const SEARCH_PREFIX: &str = "labels/search_events/";
const LABEL_PREFIX: &str = "labels/label_events/";
const DEFAULT_LIMIT: usize = 500;
const MAX_LIMIT: usize = 2000;
const MAX_DAYS: i64 = 365;
const DOWNLOAD_CONCURRENCY: usize = 16;

#[derive(Debug, Deserialize)]
pub struct EventsQuery {
    pub from: Option<String>,
    pub to: Option<String>,
    pub endpoint: Option<String>,
    pub model: Option<String>,
    pub index: Option<String>,
    pub signals: Option<String>,
    pub limit: Option<usize>,
    pub cursor: Option<String>,
    pub since: Option<String>,
}

/// A single listed object tagged with which prefix it came from.
#[derive(Clone)]
struct Listed {
    kind: EventKind,
    meta: GcsObjectMeta,
    day: String,
}

#[derive(Clone, Copy, PartialEq, Eq)]
enum EventKind {
    Search,
    Label,
}

impl EventKind {
    fn as_str(&self) -> &'static str {
        match self {
            EventKind::Search => "search",
            EventKind::Label => "label",
        }
    }
}

pub async fn list_events(
    State(state): State<Arc<AppState>>,
    Query(q): Query<EventsQuery>,
) -> Result<Json<Value>, AppError> {
    let gcs = state.gcs.clone();
    let Some(gcs) = gcs.as_ref().as_ref() else {
        return Err(AppError::ServiceUnavailable("GCS unavailable".into()));
    };
    let bucket = state.config.labels_bucket.clone();

    // Clamp to [1, MAX_LIMIT].
    let limit = q
        .limit
        .unwrap_or(DEFAULT_LIMIT)
        .min(MAX_LIMIT)
        .max(1);

    let now = Utc::now();
    let to_dt = parse_rfc3339_or(&q.to, now)?;
    let from_dt = parse_rfc3339_or(
        &q.from,
        to_dt.checked_sub_signed(Duration::days(14)).unwrap_or(to_dt),
    )?;
    if (to_dt - from_dt).num_days() > MAX_DAYS {
        return Err(AppError::BadRequest(format!(
            "range too wide; max {MAX_DAYS} days"
        )));
    }

    let signals: Option<Vec<String>> = q.signals.as_ref().map(|s| {
        s.split(',')
            .map(|p| p.trim().to_string())
            .filter(|p| !p.is_empty())
            .collect()
    });

    // Cursor decode: "YYYY-MM-DD|rfc3339|object_name"
    let cursor_parts = q
        .cursor
        .as_deref()
        .map(decode_cursor)
        .transpose()?;

    // -------- "since" fast path: poll the last ~2 days only --------
    if let Some(since_raw) = q.since.as_deref() {
        let since_dt = parse_rfc3339(since_raw)?;
        return since_path(
            gcs,
            &bucket,
            since_dt,
            now,
            limit,
            q.endpoint.as_deref(),
            q.model.as_deref(),
            q.index.as_deref(),
            signals.as_deref(),
        )
        .await
        .map(Json);
    }

    // -------- Pagination path --------
    let range_start = from_dt.date_naive();
    let range_end = to_dt.date_naive();
    let cursor_day = cursor_parts
        .as_ref()
        .map(|c| NaiveDate::parse_from_str(&c.day, "%Y-%m-%d"))
        .transpose()
        .map_err(|e| AppError::BadRequest(format!("bad day in cursor: {e}")))?;

    // Discover which day-partitions actually have data, then iterate only those.
    // One GCS list (delimiter='/') per kind regardless of range width.
    let days = discover_days(gcs, &bucket, range_start, range_end, cursor_day).await?;

    // Walk discovered days newest -> oldest, collecting Listed entries until we have
    // at least `limit * 3` candidates (enough cushion for filtering and stable cursor).
    let mut listed: Vec<Listed> = Vec::new();
    let mut next_cursor: Option<(String, DateTime<Utc>, String)> = None;
    let mut newest_walked_day: Option<String> = None;
    let mut day_walked = false;

    for day_date in &days {
        let day = day_date.format("%Y-%m-%d").to_string();
        if newest_walked_day.is_none() {
            newest_walked_day = Some(day.clone());
        }
        let mut day_items = list_day(gcs, &bucket, &day).await?;

        // If we're resuming from a cursor, drop everything at-or-after that point.
        if !day_walked {
            if let Some(c) = cursor_parts.as_ref() {
                if c.day == day {
                    day_items.retain(|l| is_strictly_older(&l.meta, c.created_at, &c.name));
                }
            }
        }
        day_walked = true;

        listed.append(&mut day_items);

        if listed.len() >= limit * 3 {
            break;
        }
    }

    // Sort by created_at desc, falling back to name for stable order.
    listed.sort_by(|a, b| {
        b.meta
            .time_created
            .cmp(&a.meta.time_created)
            .then(b.meta.name.cmp(&a.meta.name))
    });

    // Pick the page; mark next cursor if more exist.
    // The cursor's day field is the newest day we actually walked — *not* the boundary
    // item's day. This ensures the resume scan re-checks days that may contain items
    // whose `time_created` is older than the boundary even though their path-day is
    // newer (e.g. clock skew, backfilled writes). The per-day `is_strictly_older`
    // dedupe handles the boundary correctly.
    let take = listed.len().min(limit);
    if listed.len() > take {
        let last = &listed[take - 1];
        if let Some(tc) = last.meta.time_created {
            let cursor_day = newest_walked_day
                .clone()
                .unwrap_or_else(|| last.day.clone());
            next_cursor = Some((cursor_day, tc, last.meta.name.clone()));
        }
    }
    listed.truncate(take);

    let events = download_and_filter(
        gcs,
        &bucket,
        listed,
        q.endpoint.as_deref(),
        q.model.as_deref(),
        q.index.as_deref(),
        signals.as_deref(),
    )
    .await?;

    Ok(Json(json!({
        "events": events,
        "next_cursor": next_cursor.map(|(d, t, n)| encode_cursor(&d, t, &n)),
    })))
}

// ---------------- helpers ----------------

struct CursorParts {
    day: String,
    created_at: DateTime<Utc>,
    name: String,
}

fn encode_cursor(day: &str, created_at: DateTime<Utc>, name: &str) -> String {
    format!("{}|{}|{}", day, created_at.to_rfc3339(), name)
}

fn decode_cursor(s: &str) -> Result<CursorParts, AppError> {
    let mut parts = s.splitn(3, '|');
    let day = parts
        .next()
        .ok_or_else(|| AppError::BadRequest("bad cursor".into()))?;
    let ts = parts
        .next()
        .ok_or_else(|| AppError::BadRequest("bad cursor".into()))?;
    let name = parts
        .next()
        .ok_or_else(|| AppError::BadRequest("bad cursor".into()))?;
    NaiveDate::parse_from_str(day, "%Y-%m-%d")
        .map_err(|_| AppError::BadRequest("bad day in cursor".into()))?;
    let created_at = DateTime::parse_from_rfc3339(ts)
        .map_err(|_| AppError::BadRequest("bad timestamp in cursor".into()))?
        .with_timezone(&Utc);
    Ok(CursorParts {
        day: day.into(),
        created_at,
        name: name.into(),
    })
}

fn is_strictly_older(m: &GcsObjectMeta, c_created: DateTime<Utc>, c_name: &str) -> bool {
    match m.time_created {
        Some(t) if t < c_created => true,
        Some(t) if t == c_created => m.name.as_str() < c_name,
        _ => false,
    }
}

fn parse_rfc3339(s: &str) -> Result<DateTime<Utc>, AppError> {
    DateTime::parse_from_rfc3339(s)
        .map(|d| d.with_timezone(&Utc))
        .map_err(|e| AppError::BadRequest(format!("bad timestamp '{s}': {e}")))
}

fn parse_rfc3339_or(opt: &Option<String>, default: DateTime<Utc>) -> Result<DateTime<Utc>, AppError> {
    match opt {
        Some(s) => parse_rfc3339(s),
        None => Ok(default),
    }
}

/// Discover the days that have data, intersected with the request range.
///
/// Two GCS list calls (one per kind) using `delimiter='/'`, which returns the set of
/// child "directories" without enumerating their contents. Output is sorted desc and
/// clipped to `[range_start, range_end]`. If `cursor_day` is provided, drop days
/// strictly newer than it (we'll let `is_strictly_older` re-filter the boundary day).
async fn discover_days(
    gcs: &GcsClient,
    bucket: &str,
    range_start: NaiveDate,
    range_end: NaiveDate,
    cursor_day: Option<NaiveDate>,
) -> Result<Vec<NaiveDate>, AppError> {
    let (s_res, l_res) = tokio::join!(
        gcs.list_day_prefixes(bucket, SEARCH_PREFIX),
        gcs.list_day_prefixes(bucket, LABEL_PREFIX),
    );
    let s_days = s_res.map_err(|e| AppError::Internal(format!("list search days: {e}")))?;
    let l_days = l_res.map_err(|e| AppError::Internal(format!("list label days: {e}")))?;

    let mut seen = std::collections::BTreeSet::new();
    for d in s_days.into_iter().chain(l_days.into_iter()) {
        if let Ok(date) = NaiveDate::parse_from_str(&d, "%Y-%m-%d") {
            if date >= range_start && date <= range_end {
                if let Some(c) = cursor_day {
                    if date > c {
                        continue;
                    }
                }
                seen.insert(date);
            }
        }
    }

    // BTreeSet is asc; reverse for newest-first.
    Ok(seen.into_iter().rev().collect())
}

/// Lists both prefixes for one day, in parallel.
async fn list_day(gcs: &GcsClient, bucket: &str, day: &str) -> Result<Vec<Listed>, AppError> {
    let s_prefix = format!("{SEARCH_PREFIX}{day}/");
    let l_prefix = format!("{LABEL_PREFIX}{day}/");

    let (s_res, l_res) = tokio::join!(
        gcs.list_objects(bucket, &s_prefix),
        gcs.list_objects(bucket, &l_prefix),
    );
    let searches = s_res.map_err(|e| AppError::Internal(format!("list searches: {e}")))?;
    let labels = l_res.map_err(|e| AppError::Internal(format!("list labels: {e}")))?;

    let mut out = Vec::with_capacity(searches.len() + labels.len());
    for meta in searches {
        out.push(Listed { kind: EventKind::Search, meta, day: day.into() });
    }
    for meta in labels {
        out.push(Listed { kind: EventKind::Label, meta, day: day.into() });
    }
    Ok(out)
}

/// Download a batch of listed objects in parallel and filter them.
/// Returns events tagged with `type` in timestamp-desc order.
async fn download_and_filter(
    gcs: &GcsClient,
    bucket: &str,
    listed: Vec<Listed>,
    endpoint: Option<&str>,
    model: Option<&str>,
    index: Option<&str>,
    signals: Option<&[String]>,
) -> Result<Vec<Value>, AppError> {
    // Owned, sendable filter state for each spawned task.
    let filt = Arc::new(FilterArgs {
        endpoint: endpoint.map(String::from),
        model: model.map(String::from),
        index: index.map(String::from),
        signals: signals.map(|s| s.to_vec()),
    });

    let mut iter = listed.into_iter();
    let mut set: JoinSet<Result<Option<Value>, String>> = JoinSet::new();
    let mut events: Vec<Value> = Vec::new();

    let launch = |set: &mut JoinSet<Result<Option<Value>, String>>, item: Listed| {
        let gcs = gcs.clone();
        let bucket = bucket.to_string();
        let filt = filt.clone();
        set.spawn(async move {
            let bytes = gcs
                .download_blob(&bucket, &item.meta.name)
                .await
                .map_err(|e| format!("download {}: {e}", item.meta.name))?;
            let v: Value = serde_json::from_slice(&bytes)
                .map_err(|e| format!("parse {}: {e}", item.meta.name))?;
            Ok(passes_filter(
                item.kind,
                v,
                filt.endpoint.as_deref(),
                filt.model.as_deref(),
                filt.index.as_deref(),
                filt.signals.as_deref(),
            ))
        });
    };

    // Seed the pool.
    for _ in 0..DOWNLOAD_CONCURRENCY {
        match iter.next() {
            Some(item) => launch(&mut set, item),
            None => break,
        }
    }

    while let Some(res) = set.join_next().await {
        let v = res
            .map_err(|e| AppError::Internal(format!("join: {e}")))?
            .map_err(AppError::Internal)?;
        if let Some(v) = v {
            events.push(v);
        }
        if let Some(item) = iter.next() {
            launch(&mut set, item);
        }
    }

    // Sort by in-payload timestamp desc.
    events.sort_by(|a, b| {
        let ta = a.get("timestamp").and_then(|v| v.as_str()).unwrap_or("");
        let tb = b.get("timestamp").and_then(|v| v.as_str()).unwrap_or("");
        tb.cmp(ta)
    });
    Ok(events)
}

struct FilterArgs {
    endpoint: Option<String>,
    model: Option<String>,
    index: Option<String>,
    signals: Option<Vec<String>>,
}

/// Since-path: list the current day and the previous day, filter by `timestamp > since`,
/// trim to limit. No cursor — caller calls again with a newer `since`.
#[allow(clippy::too_many_arguments)]
async fn since_path(
    gcs: &GcsClient,
    bucket: &str,
    since: DateTime<Utc>,
    now: DateTime<Utc>,
    limit: usize,
    endpoint: Option<&str>,
    model: Option<&str>,
    index: Option<&str>,
    signals: Option<&[String]>,
) -> Result<Value, AppError> {
    let today = now.date_naive();
    let yesterday = today.pred_opt().unwrap_or(today);

    let mut listed: Vec<Listed> = Vec::new();
    for day in [today, yesterday] {
        let day_s = day.format("%Y-%m-%d").to_string();
        let mut items = list_day(gcs, bucket, &day_s).await?;
        // Keep only items whose GCS time_created is > since (cheap pre-filter).
        items.retain(|l| match l.meta.time_created {
            Some(t) => t > since,
            None => true,
        });
        listed.append(&mut items);
    }
    listed.sort_by(|a, b| {
        b.meta
            .time_created
            .cmp(&a.meta.time_created)
            .then(b.meta.name.cmp(&a.meta.name))
    });
    listed.truncate(limit);

    let events = download_and_filter(gcs, bucket, listed, endpoint, model, index, signals).await?;
    // Hard filter on in-payload timestamp.
    let since_s = since.to_rfc3339();
    let events: Vec<Value> = events
        .into_iter()
        .filter(|v| {
            v.get("timestamp")
                .and_then(|x| x.as_str())
                .map(|t| t > since_s.as_str())
                .unwrap_or(false)
        })
        .collect();

    Ok(json!({ "events": events, "next_cursor": Value::Null }))
}

/// Apply server-side filters to a downloaded event payload.
/// Returns Some(value-with-type-tag) if it passes, None otherwise.
fn passes_filter(
    kind: EventKind,
    mut v: Value,
    endpoint: Option<&str>,
    model: Option<&str>,
    index: Option<&str>,
    signals: Option<&[String]>,
) -> Option<Value> {
    match kind {
        EventKind::Search => {
            if let Some(want) = endpoint {
                if v.get("endpoint").and_then(|x| x.as_str()) != Some(want) {
                    return None;
                }
            }
            if let Some(want) = model {
                if v.pointer("/versions/model").and_then(|x| x.as_str()) != Some(want) {
                    return None;
                }
            }
            if let Some(want) = index {
                if v.pointer("/versions/index").and_then(|x| x.as_str()) != Some(want) {
                    return None;
                }
            }
            // Signal filter ignores searches.
        }
        EventKind::Label => {
            if let Some(want) = signals {
                let got = v.get("signal").and_then(|x| x.as_str()).unwrap_or("");
                if !want.iter().any(|s| s == got) {
                    return None;
                }
            }
            // endpoint/model/index don't live on label events; can only be filtered
            // by joining via search_id, which the UI handles.
        }
    }
    if let Value::Object(ref mut map) = v {
        map.insert("type".into(), Value::String(kind.as_str().into()));
    }
    Some(v)
}

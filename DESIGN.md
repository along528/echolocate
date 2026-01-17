# **Design Document: Project "Cloud Crate"**

**Sub-title:** WXYC-Inspired Semantic Music Discovery Engine **Author:** Alex Long **Status:** Draft / MVP Definition **Target Platform:** macOS (Edge) / Google Cloud (Backend) / MCP (Interface)

## **1\. Executive Summary**

"Cloud Crate" is a personal music intelligence platform that transforms a standard Apple Music library into a semantically searchable "digital record crate." Unlike algorithmic discovery that focuses on popularity, Cloud Crate focuses on **thematic segues** and **historical/textural relationships**, mimicking the curation style of non-commercial college radio (WXYC).  
The system uses a Model Context Protocol (MCP) server to allow an LLM (Claude, Gemini) to act as a DJ assistant that can query, filter, and eventually curate playlists based on natural language "vibes."

## **2\. System Architecture**

The architecture is divided into the **Local Edge** (to interface with Apple's sandbox) and the **Cloud Intelligence Layer**.

### **2.1 High-Level Flow**

1. **Ingest (Local):** A Kotlin/Swift daemon on the Mac extracts library metadata and play history.  
2. **Process (GCP):** Data is pushed to BigQuery. A Cloud Run service generates semantic embeddings for tracks using Vertex AI.  
3. **Interface (MCP):** A Python-based MCP server hosted on Cloud Run exposes tools to the LLM.  
4. **Action (Future):** The LLM sends playlist definitions back to the Local Edge for Apple Music API write-back.

## **3\. Component Specifications**

### **3.1 The Edge Ingestor (macOS)**

* **Tech:** Kotlin Native or Swift.  
* **Responsibility:** \* Query MusicKit for local library state.  
  * Capture: PersistentID, CatalogID, PlayCount, LastPlayedDate, SkipCount, and EditorialNotes.  
  * Push differential updates to GCP via a secure REST endpoint.

### **3.2 The Cloud Backend (GCP)**

* **Database:** **BigQuery**.  
  * Use **BigQuery Vector Search** for storing 1536-dimensional embeddings.  
  * Standard SQL tables for metadata (Artist, Album, Label, Year).  
* **Compute:** **Cloud Run**.  
  * Hosting the Python/FastAPI backend.  
* **AI/LLM:** **Vertex AI (Gemini 1.5 Pro)**.  
  * Generates the "Thematic Paragraphs" (semantic descriptions) and converts them into vectors.

### **3.3 The MCP Layer (The Interface)**

* **Protocol:** Model Context Protocol (MCP).  
* **Tools exposed to LLM:**  
  * search\_library(query, limit): Semantic vector search (Local Library).  
  * search\_apple\_music(query, limit): Search the global Apple Music Catalog (Artists, Albums, Songs).
  * get\_track\_context(track\_id): Returns full metadata \+ "WXYC-style" summary.  
  * get\_rotation(category): Filters tracks by "Heavy," "Gold," or "Unplayed" logic.

## **4\. Implementation Phases**

### **Phase 1: MVP (The Semantic Chat)**

* **Goal:** Successfully chat with your library.  
* **Workflow:**  
  1. Manual trigger to export JSON from Mac.  
  2. Python script to upload JSON to BigQuery.  
  3. Cloud Run service that generates embeddings for the top 500 "High Rotation" tracks.  
  4. Local MCP setup to query BigQuery.  
* **Success Metric:** Asking "Show me something that sounds like 80s industrial but is more ambient" and getting relevant results from your library.

### **Phase 2: Write-Back (Playlist Creation)**

* **Goal:** Turn chat conversations into actionable music.  
* **Workflow:**  
  1. Add create\_playlist(name, track\_ids) tool to MCP.  
  2. **Native API Bridge**: The Python backend calls the local `edge` (Swift) CLI to perform write operations.
  3. **MusicKit Integration**: `edge` uses Apple's native MusicKit framework (or Web API) to create playlists and add tracks silently.
  4. **Catalog Support**: Seamlessly mixes Library tracks (UUIDs) and Catalog tracks (Store IDs).

### **Phase 3: Deep Enrichment**

* **Goal:** Expand the "Intelligence" of the crate.  
* **Workflow:**  
  1. **Discogs Integration:** Fetch record label and "Style" tags for every album.  
  2. **Last.fm Integration:** Pull "Global Listener Tags" to understand track popularity vs. niche appeal.  
  1. **Discogs Integration:** Fetch record label and "Style" tags for every album.
  2. **Last.fm Integration:** Pull "Global Listener Tags" to understand track popularity vs. niche appeal.
  3. **Cross-Library Segues:** If a song in the library doesn't have a good match, suggest a "Related Catalog" track to be added to the library.
  4. **Catalog Expansion:** Seamlessly mix "My Library" and "Apple Music" results in search.

## **5\. Data Schema (BigQuery)**

| Field | Type | Description |
| :---- | :---- | :---- |
| id | STRING | Apple Music Catalog ID (Primary Key) |
| title | STRING | Track Title |
| artist\_name | STRING | Artist Name |
| play\_count | INTEGER | User play history |
| last\_played\_at | TIMESTAMP | Last play date |
| editorial\_summary | STRING | LLM-generated WXYC-style description |
| vibe\_embedding | VECTOR | 1536-dim vector for semantic search |

## **6\. Security & Privacy**

* **Authentication:** GCP Service Accounts for the Mac-to-Cloud bridge.  
* **Token Management:** Apple Music User Tokens stored in macOS Keychain, never in the cloud DB.  
* **Access Control:** The MCP server will be protected via an API Key or IAP (Identity-Aware Proxy) to ensure only you can query your library.

## **7\. Next Steps**

1. **Initialize Git Repo:** Set up a monorepo with /edge (Kotlin/Swift) and /backend (Python).  
2. **GCP Setup:** Enable BigQuery and Vertex AI APIs.  
3. **Hello World:** Write the first script to pull 10 songs from MusicKit and print them to the console as JSON.

**End of Document**

### **How to use this:**

1. Open [Google Docs](https://docs.google.com).  
2. Create a New Document.  
3. Paste the content above.  
4. Use this as your "Reference Architecture" when you start prompting **Google Antigravity** or your LLM of choice to generate the specific code.

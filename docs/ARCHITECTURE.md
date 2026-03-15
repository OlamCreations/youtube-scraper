# Architecture Overview

The YouTube Scraper project utilizes a hybrid local/remote architecture to reliably extract, store, and build transcript libraries without tying up local resources or risking IP bans on residential networks.

## Pipeline Architecture

The system is split into two main components: a remote scraping service and a local library builder.

### 1. Remote Pipeline (VPS)

A remote VPS runs a Bun/TypeScript service (`youtube-pipeline.service`) responsible for all heavy lifting and interactions with YouTube. It operates on a Directed Acyclic Graph (DAG) workflow:

`scrape` -> `analyze` -> `generate` -> `produce` -> `upload`

*   **Scrape:** Uses `yt-dlp` to fetch video metadata and auto-generated captions for tracked channels. No AI models are involved; it strictly relies on YouTube's own auto-captions to ensure speed and low resource usage.
*   **Analyze:** Processes the raw captions, cleaning timestamps and formatting them into readable text.
*   **Generate/Produce/Upload:** Prepares the data for storage and potential remote syncing.

**Automation:**
*   A cron job is scheduled to run every 30 minutes, executing the `scrape` and `analyze` steps automatically to keep the database up-to-date with new videos.
*   A manual trigger run can be initiated to process the entire pipeline end-to-end.

### 2. The Source of Truth: SQLite

All data harvested by the VPS is stored in a structured SQLite database. This database acts as the single source of truth for the entire system.
*   `channels` table: Tracks the channels being monitored.
*   `videos` table: Stores metadata for all discovered videos.
*   `transcripts` table: Holds the cleaned, processed caption text.

### 3. Local Library Builder

The local machine acts as the consumer and presenter of this data.

1.  **Sync:** The local machine uses SSH/SCP (via `manage.ps1 sync`) to securely download the latest SQLite database from the VPS.
2.  **Build:** Once the database is local, Python scripts (`build_library.py`) query the SQLite data and generate a static, markdown-based folder structure.

This decouples the scraping from the viewing. The local builder organizes the data into two primary views:
*   **By Channel:** Human-readable filenames (e.g., `by_channel/kurzgesagt/The_Immune_System.md`) optimized for browsing and reading.
*   **By Video ID:** Programmatic structure (e.g., `videos/v_123456/transcript.md`) optimized for scripting and linking.

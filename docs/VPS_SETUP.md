# VPS Setup Guide

To run the remote scraping pipeline, you will need a Virtual Private Server (VPS) running Linux. This guide provides generic instructions for setting up the environment on Ubuntu 22.04 or newer.

## Prerequisites

Ensure your VPS has the following installed:
*   Ubuntu 22.04 LTS (or similar modern Linux distribution)
*   Bun (JavaScript runtime)
*   `yt-dlp` (Command-line video downloader)
*   SQLite3

## Installation Steps

### 1. Clone the Repository

Clone the runtime pipeline repository to your VPS. It is recommended to place this in a dedicated directory, for example, `/opt/youtube-pipeline` or a user's home directory.

```bash
git clone https://github.com/OlamCreations/youtube-pipeline.git /path/to/youtube-pipeline
cd /path/to/youtube-pipeline
```

### 2. Install Dependencies

Use Bun to install the required packages for the pipeline service.

```bash
bun install
```

### 3. Database Configuration

Initialize the SQLite database and configure the channels you want to scrape. You will need to insert rows into the `channels` table.

```bash
# Create the database schema (assuming a setup script exists)
bun run db:init

# Access sqlite to add a channel manually
sqlite3 data/pipeline.db
sqlite> INSERT INTO channels (channel_id, slug, name, category) VALUES ('UC...', 'example', 'Example Channel', 'tech');
sqlite> .exit
```

### 4. Systemd Service Setup

To ensure the pipeline runs reliably and starts on boot, create a systemd service.

Create a file at `/etc/systemd/system/youtube-pipeline.service`:

```ini
[Unit]
Description=YouTube Scraper Pipeline
After=network.target

[Service]
Type=simple
User=your_user
WorkingDirectory=/path/to/youtube-pipeline
ExecStart=/usr/local/bin/bun run start
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Enable and start the service:

```bash
sudo systemctl enable youtube-pipeline.service
sudo systemctl start youtube-pipeline.service
```

### 5. Automated Scraping (Cron)

Set up a cron job to automatically trigger the `scrape` and `analyze` phases of the pipeline every 30 minutes.

Open the crontab for the user running the service:

```bash
crontab -e
```

Add the following line (adjusting paths as necessary):

```cron
*/30 * * * * cd /path/to/youtube-pipeline && bun run trigger-scrape >> /path/to/youtube-pipeline/logs/cron.log 2>&1
```

### 6. Security Basics

*   **Firewall:** Ensure UFW or your preferred firewall is enabled and only allows necessary traffic (typically SSH on port 22, and any ports required by your specific setup).
    ```bash
    sudo ufw allow OpenSSH
    sudo ufw enable
    ```
*   **SSH Keys:** Disable password authentication for SSH and rely exclusively on SSH keys for logging into the VPS.

### 7. YouTube Authentication (Optional but Recommended)

To avoid rate limits and access age-restricted videos, you may need to provide `yt-dlp` with cookies from an authenticated YouTube session.

1.  Export your cookies from your local browser using an extension like "Get cookies.txt".
2.  Save the file as `cookies.txt` in the root of your pipeline directory on the VPS.
3.  Ensure your pipeline configuration is set to pass `--cookies cookies.txt` to `yt-dlp`.

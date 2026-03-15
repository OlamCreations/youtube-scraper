# Self-Hosted Setup

This document explains how to run `youtube-scraper` on your own Linux machine if you want scheduled scraping outside your laptop or desktop workflow.

This is a generic self-hosting guide. It does not describe any private deployment.

## Prerequisites

Install:
- Python 3.10+
- `yt-dlp`
- SQLite3

Optional:
- systemd, if you want a background service
- cron, if you want scheduled runs

## Basic Setup

```bash
git clone https://github.com/OlamCreations/youtube-scraper.git
cd youtube-scraper
python scripts/scrape.py ./data --seed channels.example.json
python scripts/scrape.py ./data
python scripts/build_library.py build ./data
```

## Scheduled Runs

If you want periodic scraping, schedule the scraper with cron.

Example:

```cron
*/30 * * * * cd /path/to/youtube-scraper && /usr/bin/python3 scripts/scrape.py ./data >> ./logs/scrape.log 2>&1
```

Then rebuild the library on your preferred cadence:

```cron
15 */2 * * * cd /path/to/youtube-scraper && /usr/bin/python3 scripts/build_library.py build ./data >> ./logs/build.log 2>&1
```

## Security Notes

- Do not commit `cookies.txt`, `.env`, or any local secrets.
- Use SSH keys instead of passwords if you automate remote access.
- Restrict host access with your firewall if you expose any services around this workflow.
- Keep all machine-specific paths and credentials outside the repository.

## Cookies

If `yt-dlp` needs authenticated cookies for some channels or videos:
- export them locally
- store them outside version control
- pass them only on the machine where scraping runs

Never publish real browser cookies in the repository.

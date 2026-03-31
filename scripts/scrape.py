#!/usr/bin/env python3
"""
Local YouTube transcript scraper using yt-dlp and SQLite.
"""

import sqlite3
import subprocess
import argparse
import pathlib
import re
import json
import datetime

def init_db(db_path: pathlib.Path):
    """Initializes the database schema if it doesn't exist."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS channels (
            id TEXT PRIMARY KEY,
            name TEXT,
            handle TEXT,
            category TEXT,
            language TEXT DEFAULT 'en',
            priority INTEGER DEFAULT 5,
            enabled INTEGER DEFAULT 1,
            last_scraped_at TEXT,
            total_videos INTEGER DEFAULT 0,
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS videos (
            id TEXT PRIMARY KEY,
            channel_id TEXT NOT NULL,
            title TEXT NOT NULL,
            description TEXT,
            published_at TEXT,
            duration_seconds INTEGER,
            view_count INTEGER,
            like_count INTEGER,
            has_transcript INTEGER DEFAULT 0,
            transcript_source TEXT,
            scraped_at TEXT,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (channel_id) REFERENCES channels(id)
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS transcripts (
            video_id TEXT PRIMARY KEY,
            raw_text TEXT NOT NULL,
            word_count INTEGER,
            language TEXT DEFAULT 'en',
            quality_score REAL,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (video_id) REFERENCES videos(id)
        )
    ''')
    
    conn.commit()
    return conn

def clean_vtt(text: str) -> str:
    """Cleans VTT file contents into deduplicated raw text.

    YouTube auto-subs use a rolling-context format: each cue has two lines —
    the first repeats the previous cue's text and the second contains the new
    words with inline ``<c>`` timestamps.  Cues with near-zero duration
    (< 50 ms) are pure context echoes and carry no new content.

    Strategy: parse cues, keep only the *second* line of real (non-echo) cues,
    strip inline tags, then join.
    """
    lines = text.splitlines()
    cues: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        # Skip headers and blanks
        if not line or "WEBVTT" in line or line.startswith("Kind:") or line.startswith("Language:"):
            i += 1
            continue
        # Detect timestamp line
        ts_match = re.match(
            r'^(\d{2}:\d{2}:\d{2}\.\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2}\.\d{3})', line
        )
        if not ts_match:
            i += 1
            continue
        # Parse start/end to detect echo cues (duration < 50 ms)
        start_ms = _ts_to_ms(ts_match.group(1))
        end_ms = _ts_to_ms(ts_match.group(2))
        is_echo = (end_ms - start_ms) < 50
        # Collect all payload lines until next blank or timestamp
        i += 1
        payload_lines: list[str] = []
        while i < len(lines):
            pl = lines[i].strip()
            if not pl:
                i += 1
                break
            if re.match(r'^\d{2}:\d{2}', pl):
                break
            payload_lines.append(pl)
            i += 1
        if is_echo or not payload_lines:
            continue
        # For rolling-context cues, the NEW content is the last payload line
        new_line = payload_lines[-1] if len(payload_lines) > 1 else payload_lines[0]
        # Strip inline tags like <c> </c> <00:00:01.234>
        new_line = re.sub(r'<[^>]+>', '', new_line).strip()
        if new_line:
            cues.append(new_line)

    text = " ".join(cues)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def _ts_to_ms(ts: str) -> int:
    """Convert 'HH:MM:SS.mmm' to milliseconds."""
    h, m, rest = ts.split(":")
    s, ms = rest.split(".")
    return int(h) * 3600000 + int(m) * 60000 + int(s) * 1000 + int(ms)

def seed_channels(conn, json_file):
    """Seeds channels from a JSON file into the database."""
    try:
        with open(json_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
            
        cursor = conn.cursor()
        channels = data.get('channels', [])
        for ch in channels:
            cursor.execute('''
                INSERT INTO channels (id, name, handle, category, language)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name=excluded.name,
                    handle=excluded.handle,
                    category=excluded.category,
                    language=excluded.language,
                    updated_at=datetime('now')
            ''', (
                ch.get('id'), 
                ch.get('name', ''), 
                ch.get('handle', ''), 
                ch.get('category', ''), 
                ch.get('language', 'en')
            ))
        conn.commit()
        print(f"Seeded {len(channels)} channels from {json_file}", flush=True)
    except Exception as e:
        print(f"Error seeding channels: {e}", flush=True)

def list_channels(conn):
    """Lists all channels and their video counts."""
    cursor = conn.cursor()
    cursor.execute("SELECT name, handle, id, total_videos, enabled FROM channels ORDER BY name")
    channels = cursor.fetchall()
    
    print(f"{'Name':<30} {'Handle':<20} {'ID':<25} {'Videos':<10} {'Enabled':<10}", flush=True)
    print("-" * 100, flush=True)
    for name, handle, ch_id, total, enabled in channels:
        print(f"{name or '':<30} {handle or '':<20} {ch_id:<25} {total:<10} {enabled:<10}", flush=True)

def scrape(conn, data_dir: pathlib.Path, limit: int, specific_channel: str = None):
    """Main scraping logic for channels and videos."""
    cursor = conn.cursor()
    
    query = "SELECT id, name, handle, language, total_videos FROM channels WHERE enabled = 1"
    params = []
    if specific_channel:
        query += " AND id = ?"
        params.append(specific_channel)
        
    cursor.execute(query, params)
    channels = cursor.fetchall()
    
    scrape_dir = data_dir / "tmp"
    scrape_dir.mkdir(parents=True, exist_ok=True)
    
    cookies_path = pathlib.Path("config/cookies.txt")
    
    for ch_id, name, handle, lang, total_videos in channels:
        url = f"https://www.youtube.com/{handle}" if handle else f"https://www.youtube.com/channel/{ch_id}"
        
        # 1. List recent videos
        cmd = [
            "yt-dlp",
            "--flat-playlist",
            "--print", "id",
            "--print", "title",
            "--playlist-end", str(limit),
            url
        ]
        
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', errors='replace', check=False)
        lines = (proc.stdout or "").splitlines()
        
        videos = []
        for i in range(0, len(lines) - 1, 2):
            videos.append((lines[i].strip(), lines[i+1].strip()))
            
        # Check existing
        cursor.execute("SELECT id FROM videos WHERE channel_id = ?", (ch_id,))
        existing_ids = {row[0] for row in cursor.fetchall()}
        
        new_videos = [(vid, vtitle) for vid, vtitle in videos if vid not in existing_ids]
        
        if not new_videos:
            continue
            
        print(f"=== Scraping {name} ({len(new_videos)} new / {total_videos} total) ===", flush=True)
        
        videos_added = 0
        transcripts_added = 0
        
        for idx, (vid, vtitle) in enumerate(new_videos, 1):
            now = datetime.datetime.utcnow().isoformat()
            
            # Insert into videos table
            cursor.execute('''
                INSERT INTO videos (id, channel_id, title, scraped_at)
                VALUES (?, ?, ?, ?)
            ''', (vid, ch_id, vtitle, now))
            
            # Download transcript
            sub_cmd = [
                "yt-dlp",
                "--write-auto-sub",
                "--sub-lang", lang,
                "--skip-download",
                "--no-check-formats",
                "-o", f"{scrape_dir}/%(id)s",
                f"https://www.youtube.com/watch?v={vid}"
            ]
            
            if cookies_path.exists():
                sub_cmd.extend(["--cookies", str(cookies_path)])
                
            subprocess.run(sub_cmd, capture_output=True, check=False)
            
            vtt_files = list(scrape_dir.glob(f"{vid}*.vtt"))
            if vtt_files:
                vtt_file = vtt_files[0]
                try:
                    with open(vtt_file, 'r', encoding='utf-8') as f:
                        raw_vtt = f.read()
                        
                    clean_text = clean_vtt(raw_vtt)
                    word_count = len(clean_text.split())
                    quality_score = min(word_count / 500.0, 1.0)
                    
                    cursor.execute('''
                        INSERT INTO transcripts (video_id, raw_text, word_count, language, quality_score)
                        VALUES (?, ?, ?, ?, ?)
                    ''', (vid, clean_text, word_count, lang, quality_score))
                    
                    cursor.execute("UPDATE videos SET has_transcript=1, transcript_source='auto-sub' WHERE id=?", (vid,))
                    
                    safe_title = vtitle.encode('ascii', errors='replace').decode('ascii')
                    print(f"[{idx}/{len(new_videos)}] {safe_title} ({vid})\n  -> {word_count} words", flush=True)
                    transcripts_added += 1
                except Exception as e:
                    safe_title = vtitle.encode('ascii', errors='replace').decode('ascii')
                    print(f"[{idx}/{len(new_videos)}] {safe_title} ({vid})\n  -> error processing transcript: {e}", flush=True)
                finally:
                    try:
                        vtt_file.unlink()
                    except OSError:
                        pass
            else:
                safe_title = vtitle.encode('ascii', errors='replace').decode('ascii')
                print(f"[{idx}/{len(new_videos)}] {safe_title} ({vid})\n  -> no transcript available", flush=True)
                
            videos_added += 1
            
            if videos_added % 20 == 0:
                conn.commit()
                print(f"  [checkpoint: {videos_added} videos, {transcripts_added} transcripts]", flush=True)
                
        conn.commit()
        
        # Update channel stats
        cursor.execute('''
            UPDATE channels 
            SET last_scraped_at = ?, total_videos = (SELECT COUNT(*) FROM videos WHERE channel_id = ?)
            WHERE id = ?
        ''', (datetime.datetime.utcnow().isoformat(), ch_id, ch_id))
        conn.commit()
        
        print(f"=== Done: {videos_added} videos added, {transcripts_added} transcripts ===", flush=True)

def rescrape_transcripts(conn, data_dir):
    """Re-download and re-clean all transcripts using the improved VTT parser."""
    cursor = conn.cursor()
    scrape_dir = data_dir / "tmp"
    scrape_dir.mkdir(parents=True, exist_ok=True)

    cursor.execute("""
        SELECT v.id, v.title, c.language
        FROM videos v
        JOIN channels c ON v.channel_id = c.id
        WHERE v.has_transcript = 1
        ORDER BY c.name, v.title
    """)
    rows = cursor.fetchall()
    print(f"=== Re-scraping {len(rows)} transcripts with dedup VTT parser ===", flush=True)

    updated = 0
    failed = 0
    for idx, (vid, title, lang) in enumerate(rows, 1):
        sub_cmd = [
            "yt-dlp",
            "--write-auto-sub",
            "--sub-lang", lang or "en",
            "--skip-download",
            "--no-check-formats",
            "-o", f"{scrape_dir}/%(id)s",
            f"https://www.youtube.com/watch?v={vid}"
        ]
        subprocess.run(sub_cmd, capture_output=True, check=False)
        vtt_files = list(scrape_dir.glob(f"{vid}*.vtt"))
        if vtt_files:
            try:
                with open(vtt_files[0], 'r', encoding='utf-8') as f:
                    raw_vtt = f.read()
                clean_text = clean_vtt(raw_vtt)
                word_count = len(clean_text.split())
                quality_score = min(word_count / 500.0, 1.0)
                cursor.execute("""
                    UPDATE transcripts
                    SET raw_text = ?, word_count = ?, quality_score = ?
                    WHERE video_id = ?
                """, (clean_text, word_count, quality_score, vid))
                updated += 1
                if idx % 20 == 0:
                    conn.commit()
                    print(f"  [checkpoint: {idx}/{len(rows)}, {updated} updated]", flush=True)
            except Exception as e:
                safe_title = title.encode('ascii', errors='replace').decode('ascii')
                print(f"  [{idx}] error {safe_title}: {e}", flush=True)
                failed += 1
            finally:
                for vf in vtt_files:
                    try:
                        vf.unlink()
                    except OSError:
                        pass
        else:
            failed += 1

    conn.commit()
    print(f"=== Done: {updated} updated, {failed} failed out of {len(rows)} ===", flush=True)


def main():
    parser = argparse.ArgumentParser(description="Local YouTube transcript scraper")
    parser.add_argument("data_dir", help="Directory for data storage (contains db/ and tmp/)")
    parser.add_argument("--limit", type=int, default=50, help="Max videos to check per channel (default: 50)")
    parser.add_argument("--channel", help="Scrape only specific channel ID")
    parser.add_argument("--seed", help="Seed channels from JSON file into DB")
    parser.add_argument("--list", action="store_true", help="List all channels with video counts")
    parser.add_argument("--rescrape-transcripts", action="store_true", help="Re-download and re-clean all transcripts with improved VTT dedup")

    args = parser.parse_args()

    data_dir = pathlib.Path(args.data_dir)
    db_dir = data_dir / "db"
    db_dir.mkdir(parents=True, exist_ok=True)

    db_path = db_dir / "pipeline.db"
    conn = init_db(db_path)

    try:
        if args.seed:
            seed_channels(conn, args.seed)
        elif args.list:
            list_channels(conn)
        elif args.rescrape_transcripts:
            rescrape_transcripts(conn, data_dir)
        else:
            scrape(conn, data_dir, args.limit, args.channel)
    finally:
        conn.close()

if __name__ == "__main__":
    main()

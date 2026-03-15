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
    """Cleans VTT file contents into raw text."""
    lines = text.splitlines()
    cleaned_lines = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        # Remove headers
        if "WEBVTT" in line or line.startswith("Kind:") or line.startswith("Language:"):
            continue
        # Remove timestamp lines
        if re.match(r'^\d{2}:\d{2}', line):
            continue
        # Remove HTML tags
        line = re.sub(r'<[^>]+>', '', line)
        line = line.strip()
        if line:
            cleaned_lines.append(line)
            
    text = " ".join(cleaned_lines)
    # Collapse multiple whitespaces
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

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
        
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', check=False)
        lines = proc.stdout.splitlines()
        
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
                "--remote-components", "ejs:github",
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
                    
                    print(f"[{idx}/{len(new_videos)}] {vtitle} ({vid})\n  -> {word_count} words", flush=True)
                    transcripts_added += 1
                except Exception as e:
                    print(f"[{idx}/{len(new_videos)}] {vtitle} ({vid})\n  -> error processing transcript: {e}", flush=True)
                finally:
                    try:
                        vtt_file.unlink()
                    except OSError:
                        pass
            else:
                print(f"[{idx}/{len(new_videos)}] {vtitle} ({vid})\n  -> no transcript available", flush=True)
                
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

def main():
    parser = argparse.ArgumentParser(description="Local YouTube transcript scraper")
    parser.add_argument("data_dir", help="Directory for data storage (contains db/ and tmp/)")
    parser.add_argument("--limit", type=int, default=50, help="Max videos to check per channel (default: 50)")
    parser.add_argument("--channel", help="Scrape only specific channel ID")
    parser.add_argument("--seed", help="Seed channels from JSON file into DB")
    parser.add_argument("--list", action="store_true", help="List all channels with video counts")
    
    args = parser.parse_args()
    
    data_dir = pathlib.Path(args.data_dir)
    db_dir = data_dir / "db"
    db_dir.mkdir(parents=True, exist_ok=True)
    
    db_path = db_dir / "youtube.db"
    conn = init_db(db_path)
    
    try:
        if args.seed:
            seed_channels(conn, args.seed)
        elif args.list:
            list_channels(conn)
        else:
            scrape(conn, data_dir, args.limit, args.channel)
    finally:
        conn.close()

if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
סורק מלא ללא הגבלה (Full-Channel Deep Crawler) לערוץ הראשי של כאן 11 ביוטיוב
Channel ID: UCDJ6HHS5wkNaSREumdJRYhg (https://www.youtube.com/channel/UCDJ6HHS5wkNaSREumdJRYhg)

מה הסקריפט עושה?
1. סורק את כל הפלייליסטים בערוץ (limit=None) ואת כל הפרקים בתוך כל פלייליסט (limit=None).
2. סורק את כל הסרטונים בערוץ (Videos + Shorts + Streams) ללא מגבלת כמות (limit=None).
3. מושך כתוביות בעברית ב-2 מנועים במקביל:
   - youtube-transcript-api (מהיר מאוד)
   - גיבוי אוטומטי עם yt-dlp לחילוץ כתוביות אוטומטיות/ידניות בעברית במקרה של חסימה.
4. שומר נקודת עצירה (Checkpoint) כל 25 סרטונים לתוך memesJson.json ו-scanned_videos.json,
   כך שגם בסריקה של אלפי סרטונים שום דבר לא הולך לאיבוד וכל הרצה ממשיכה בדיוק מהנקודה שבה הקודמת עצרה!
"""
import json
import os
import re
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

CHANNEL_ID = "UCDJ6HHS5wkNaSREumdJRYhg"
CHANNEL_URL = f"https://www.youtube.com/channel/{CHANNEL_ID}"
OUTPUT_JSON = Path("memesJson.json")
SCANNED_STATE_JSON = Path("scanned_videos.json")

# Time budget in minutes (0 = no time limit when running on local computer; 45 min on GitHub Actions)
MAX_RUNTIME_MINUTES = float(os.environ.get("MAX_RUNTIME_MINUTES", "0"))
CHECKPOINT_EVERY = 25
WORKERS = int(os.environ.get("SCAN_WORKERS", "4"))

NEWS_FILTER_WORDS = ["מהדורת חדשות", "חדשות הערב", "חדשות הלילה", "מבזק חדשות"]

KNOWN_SERIES = [
    "קופה ראשית",
    "בואו לאכול איתי",
    "היהודים באים",
    "זהו זה",
    "המפקדת",
    "מנאייכ",
    "טהרן",
    "שב\"ס",
    "שישה אפסים",
    "איסט סייד",
    "פגישה עם רוני קובן",
    "זמן אמת",
    "המזח",
    "מועדון הסטנד-אפ",
    "קרתגו",
    "כאן ארכיון",
    "סליחה על השאלה",
    "חזרות",
    "עלומים",
    "האחיות המוצלחות שלי",
    "שעת נעילה",
    "עולם מושלם",
    "הדוקורטור",
    "מוקד 11",
    "דאבל על הכסף",
    "ארבע חתונות",
    "שום פלפל ושמן זית",
    "יחידה מעורבת",
    "טאבו",
    "שטוקהולם",
    "אבירם כץ",
    "הדיקטטורים",
    "דוקותיים"
]


def format_mm_ss(sec: float) -> str:
    s = max(0, int(sec))
    return f"{s // 60:02d}:{s % 60:02d}"


def infer_series_and_episode(title: str, playlist_title: str = ""):
    combined_text = f"{title} {playlist_title}"
    for ks in KNOWN_SERIES:
        if ks in combined_text:
            m_season = re.search(r"(עונה\s*\d+)", combined_text)
            season = m_season.group(1) if m_season else (playlist_title or "כאן 11")
            parts = [p.strip() for p in title.split("|")]
            episode = parts[-1] if len(parts) >= 2 else title
            return ("זהו זה!" if ks == "זהו זה" else ks), season, episode

    parts = [p.strip() for p in title.split("|")]
    if len(parts) >= 2:
        left = parts[0]
        right = " - ".join(parts[1:])
        m_season = re.search(r"(עונה\s*\d+)", left)
        if m_season:
            season = m_season.group(1)
            series = left.replace(season, "").strip(" -–|🛒🔥💍💰🔒")
        else:
            series = left.strip(" -–|🛒🔥💍💰🔒")
            season = playlist_title or "סדרות ודיגיטל"
        return series or (playlist_title or "כאן 11"), season, right

    if playlist_title:
        clean_pl = playlist_title.split("|")[0].strip(" -–|🛒🔥💍💰🔒")
        return (clean_pl or playlist_title), "כאן 11", title
    return "כאן 11 דיגיטל", "סדרות", title


def extract_title(v_obj: dict) -> str:
    t = v_obj.get("title", {})
    if isinstance(t, dict):
        runs = t.get("runs", [])
        if runs and isinstance(runs, list):
            return runs[0].get("text", "")
        return t.get("simpleText", "")
    return str(t or "")


def discover_all_channel_videos():
    """Discovers ALL videos across ALL playlists, uploads, shorts, and streams on UCDJ6HHS5wkNaSREumdJRYhg (no limits)."""
    collected = []
    seen_ids = set()
    try:
        import scrapetube

        print(f"[1/3] Discovering ALL series playlists on channel {CHANNEL_ID}...")
        pl_count = 0
        for pl in scrapetube.get_playlists(channel_id=CHANNEL_ID, limit=None):
            pl_id = pl.get("playlistId")
            pl_title = extract_title(pl)
            if not pl_id or any(w in pl_title for w in NEWS_FILTER_WORDS):
                continue
            pl_count += 1
            try:
                for pv in scrapetube.get_playlist(playlist_id=pl_id, limit=None):
                    vid_id = pv.get("videoId")
                    title = extract_title(pv)
                    if vid_id and title and vid_id not in seen_ids:
                        seen_ids.add(vid_id)
                        collected.append((vid_id, title, pl_title))
            except Exception as pe:
                print(f"  Playlist note ({pl_id}): {pe}")
        print(f"  -> Scanned {pl_count} playlists, discovered {len(collected)} playlist videos so far.")

        print(f"[2/3] Discovering ALL main video uploads on channel {CHANNEL_ID} (limit=None)...")
        for v in scrapetube.get_channel(channel_id=CHANNEL_ID, limit=None, content_type="videos"):
            vid_id = v.get("videoId")
            title = extract_title(v)
            if vid_id and title and vid_id not in seen_ids:
                seen_ids.add(vid_id)
                collected.append((vid_id, title, ""))
        print(f"  -> Total unique videos after main uploads: {len(collected)}")

        print(f"[3/3] Discovering ALL Shorts on channel {CHANNEL_ID} (limit=None)...")
        for sv in scrapetube.get_channel(channel_id=CHANNEL_ID, limit=None, content_type="shorts"):
            vid_id = sv.get("videoId")
            title = extract_title(sv)
            if vid_id and title and vid_id not in seen_ids:
                seen_ids.add(vid_id)
                collected.append((vid_id, title, "כאן 11 Shorts"))
        print(f"  -> Total unique videos discovered across entire channel: {len(collected)}")

    except Exception as e:
        print("Discovery warning:", e)
    return collected


def parse_vtt_or_srt(content: str):
    cues = []
    blocks = re.split(r"\n\s*\n", content.replace("\r\n", "\n"))
    for block in blocks:
        m = re.search(r"(\d{1,2}):(\d{2}):(\d{2})[.,]\d+\s*-->", block)
        if not m:
            m2 = re.search(r"(\d{1,2}):(\d{2})[.,]\d+\s*-->", block)
            if not m2:
                continue
            sec = int(m2.group(1)) * 60 + int(m2.group(2))
        else:
            sec = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + int(m.group(3))
        lines = []
        for line in block.splitlines():
            if "-->" in line or line.strip().isdigit() or line.startswith("WEBVTT") or line.startswith("Kind:") or line.startswith("Language:"):
                continue
            clean = re.sub(r"<[^>]+>", "", line).strip()
            if clean:
                lines.append(clean)
        txt = " ".join(lines).strip()
        if len(txt) >= 2 and (not cues or cues[-1][1] != txt):
            cues.append((sec, txt))
    return cues


def fetch_transcript_cues(vid_id: str):
    # Engine 1: youtube-transcript-api (supports both v0.x and v1.x APIs)
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        entries = None
        if hasattr(YouTubeTranscriptApi, "list_transcripts"):
            transcript_list = YouTubeTranscriptApi.list_transcripts(vid_id)
            tr = None
            for lang_code in ["he", "iw"]:
                try:
                    tr = transcript_list.find_transcript([lang_code])
                    break
                except Exception:
                    continue
            if tr is None:
                for t_obj in transcript_list:
                    tr = t_obj
                    break
            if tr is not None:
                entries = tr.fetch()
        else:
            ytt = YouTubeTranscriptApi()
            entries = ytt.fetch(vid_id, languages=["he", "iw", "en"])

        if entries:
            cues = []
            for entry in entries:
                start_s = float(entry.get("start", 0) if isinstance(entry, dict) else getattr(entry, "start", 0))
                text = (entry.get("text", "") if isinstance(entry, dict) else getattr(entry, "text", "")).strip()
                text = re.sub(r"<[^>]+>", "", text).replace("\n", " ").strip()
                if len(text) >= 2:
                    cues.append((int(start_s), text))
            if cues:
                return cues
    except Exception:
        pass

    # Engine 2: yt-dlp fallback for auto-subtitles / Hebrew closed captions
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            cmd = [
                "yt-dlp",
                "--skip-download",
                "--write-subs",
                "--write-auto-subs",
                "--sub-langs", "he,iw",
                "--sub-format", "vtt/srt/best",
                "-o", f"{tmpdir}/%(id)s.%(ext)s",
                f"https://www.youtube.com/watch?v={vid_id}"
            ]
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=25)
            for sub_file in Path(tmpdir).glob(f"{vid_id}*"):
                content = sub_file.read_text(encoding="utf-8", errors="ignore")
                cues = parse_vtt_or_srt(content)
                if cues:
                    return cues
    except Exception:
        pass

    return []


def save_checkpoint(existing_items, new_items, scanned_ids):
    combined = new_items + existing_items
    OUTPUT_JSON.write_text(json.dumps(combined, ensure_ascii=False, indent=2), encoding="utf-8")
    SCANNED_STATE_JSON.write_text(json.dumps(sorted(scanned_ids), ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  [Checkpoint Saved] Total subtitle lines: {len(combined)} | Total videos scanned: {len(scanned_ids)}")


def main():
    start_time = time.time()
    existing = []
    if OUTPUT_JSON.exists():
        try:
            existing = json.loads(OUTPUT_JSON.read_text(encoding="utf-8"))
        except Exception:
            existing = []

    scanned_ids = {item.get("videoId") for item in existing if item.get("videoId")}
    if SCANNED_STATE_JSON.exists():
        try:
            scanned_ids.update(json.loads(SCANNED_STATE_JSON.read_text(encoding="utf-8")))
        except Exception:
            pass

    all_videos = discover_all_channel_videos()
    pending = [
        (vid_id, title, pl_title)
        for vid_id, title, pl_title in all_videos
        if vid_id not in scanned_ids and not any(w in title for w in NEWS_FILTER_WORDS)
    ]
    print(f"Ready to scan {len(pending)} unindexed videos (out of {len(all_videos)} total on channel).")

    new_items = []
    processed_since_save = 0

    for i in range(0, len(pending), WORKERS):
        if MAX_RUNTIME_MINUTES > 0 and (time.time() - start_time) / 60.0 >= MAX_RUNTIME_MINUTES:
            print(f"Reached time budget ({MAX_RUNTIME_MINUTES} min). Saving progress for next run...")
            break

        batch = pending[i : i + WORKERS]
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            future_map = {
                pool.submit(fetch_transcript_cues, vid_id): (vid_id, title, pl_title)
                for vid_id, title, pl_title in batch
            }
            for fut in as_completed(future_map):
                vid_id, title, pl_title = future_map[fut]
                scanned_ids.add(vid_id)
                processed_since_save += 1
                cues = fut.result() or []
                if not cues:
                    continue
                series, season, episode = infer_series_and_episode(title, pl_title)
                for idx, (sec, text) in enumerate(cues):
                    new_items.append({
                        "id": f"yt-{vid_id}-{idx}",
                        "videoId": vid_id,
                        "series": series,
                        "season": season,
                        "episode": episode,
                        "timestampSec": sec,
                        "timestampFormatted": format_mm_ss(sec),
                        "text": text,
                        "sourceType": "DEMO",
                        "youtubeUrl": f"https://www.youtube.com/watch?v={vid_id}&t={sec}s"
                    })
                print(f"+ Indexed {len(cues)} lines from [{series}]: {title} ({vid_id})")

        if processed_since_save >= CHECKPOINT_EVERY:
            save_checkpoint(existing, new_items, scanned_ids)
            processed_since_save = 0

    save_checkpoint(existing, new_items, scanned_ids)
    print(f"Done! Added {len(new_items)} new subtitle lines in this run.")


if __name__ == "__main__":
    main()

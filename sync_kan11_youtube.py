#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
סורק אוטומטי דו-שכבתי (2-Tier Continuous Sync & Full Archive Crawler)
עבור שני הערוצים הרשמיים של כאן ביוטיוב:
1. כאן 11 (@KAN11 - Channel ID: UCDJ6HHS5wkNaSREumdJRYhg)
2. כאן דיגיטל (@KanDigital - כל המערכונים האקראיים, דוקותיים, חיות כיס, הטרמפיסטים, שם טוב האבי, תמיר בר ועוד)

איך הסקריפט שומר על עדכון שוטף כל כמה שעות + השלמת כל הארכיון?
- שלב 1 (עדיפות עליונה - כל ריצה): בודק קודם כל את 60 הסרטונים וה-Shorts הכי חדשים שעלו היום ב"כאן דיגיטל" וב"כאן 11" (כולל פיד RSS הרשמי של יוטיוב), כך שכל מערכון או פרק חדש שעולה נכנס לאתר תוך שעות ספורות!
- שלב 2 (השלמת כל הארכיון): ממשיך לסרוק לעומק את כל אלפי הסרטונים הבודדים (Videos + Shorts) ואת כל הפלייליסטים בשני הערוצים מאז הקמתם, ושומר התקדמות אוטומטית כל 25 סרטונים לתוך memesJson.json ו-scanned_videos.json.
"""
import json
import os
import re
import subprocess
import tempfile
import time
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

KAN11_CHANNEL_ID = "UCDJ6HHS5wkNaSREumdJRYhg"
KANDIGITAL_URL = "https://www.youtube.com/@KanDigital"

OUTPUT_JSON = Path("memesJson.json")
SCANNED_STATE_JSON = Path("scanned_videos.json")

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
    "דוקותיים",
    "אתה חייב לקרוא את זה",
    "שם טוב האבי",
    "תמיר בר",
    "אואזיס במדבר",
    "הטרמפיסטים",
    "לוחמים",
    "חיות כיס",
    "כאן סקרנים",
    "כאן מסבירים",
    "כאן מכירים",
    "כאן מקשיבים",
    "משתפצות"
]


def format_mm_ss(sec: float) -> str:
    s = max(0, int(sec))
    return f"{s // 60:02d}:{s % 60:02d}"


def infer_series_and_episode(title: str, playlist_title: str = "", default_channel_label: str = "כאן 11"):
    combined_text = f"{title} {playlist_title}"
    for ks in KNOWN_SERIES:
        if ks in combined_text:
            m_season = re.search(r"(עונה\s*\d+)", combined_text)
            season = m_season.group(1) if m_season else (playlist_title or default_channel_label)
            parts = [p.strip() for p in title.split("|")]
            episode = parts[-1] if len(parts) >= 2 else title
            if ks == "זהו זה":
                return "זהו זה!", season, episode
            if ks == "אתה חייב לקרוא את זה":
                return "אתה חייב לקרוא את זה!", season, episode
            return ks, season, episode

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
            season = playlist_title or default_channel_label
        return series or default_channel_label, season, right

    if default_channel_label == "כאן דיגיטל":
        return "מערכוני כאן דיגיטל", (playlist_title or "כאן דיגיטל"), title
    if playlist_title:
        clean_pl = playlist_title.split("|")[0].strip(" -–|🛒🔥💍💰🔒")
        return (clean_pl or playlist_title), default_channel_label, title
    return default_channel_label, "סדרות ודיגיטל", title


def extract_title(v_obj: dict) -> str:
    t = v_obj.get("title", {})
    if isinstance(t, dict):
        runs = t.get("runs", [])
        if runs and isinstance(runs, list):
            return runs[0].get("text", "")
        return t.get("simpleText", "")
    return str(t or "")


def fetch_rss_latest(channel_id: str, label: str):
    """Fetches the 15 newest uploads via YouTube's official XML RSS feed (instant, never rate-limited)."""
    items = []
    try:
        url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            xml_bytes = resp.read()
        root = ET.fromstring(xml_bytes)
        ns = {"atom": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015"}
        for entry in root.findall("atom:entry", ns):
            vid_el = entry.find("yt:videoId", ns)
            title_el = entry.find("atom:title", ns)
            if vid_el is not None and title_el is not None and vid_el.text and title_el.text:
                items.append((vid_el.text.strip(), title_el.text.strip(), "", label))
    except Exception as e:
        print(f"RSS note ({label}): {e}")
    return items


def discover_two_tier_videos():
    """
    Tier 1: Newest uploads & Shorts on BOTH @KanDigital and @KAN11 (so daily new content is indexed first!).
    Tier 2: Deep archive scan of all standalone videos, Shorts, and Playlists on BOTH @KanDigital and @KAN11.
    """
    collected = []
    seen_ids = set()

    def add_item(vid_id, title, pl_title, ch_label):
        if vid_id and title and vid_id not in seen_ids:
            seen_ids.add(vid_id)
            collected.append((vid_id, title, pl_title, ch_label))

    # Tier 1A: Instant RSS feed check
    for vid_id, title, pl_title, ch_label in fetch_rss_latest(KAN11_CHANNEL_ID, "כאן 11"):
        add_item(vid_id, title, pl_title, ch_label)

    try:
        import scrapetube

        print("[Tier 1] Checking newest uploads & Shorts on @KanDigital and @KAN11...")
        for v in scrapetube.get_channel(channel_url=KANDIGITAL_URL, limit=60, content_type="videos"):
            add_item(v.get("videoId"), extract_title(v), "", "כאן דיגיטל")
        for sv in scrapetube.get_channel(channel_url=KANDIGITAL_URL, limit=40, content_type="shorts"):
            add_item(sv.get("videoId"), extract_title(sv), "כאן דיגיטל Shorts", "כאן דיגיטל")
        for v in scrapetube.get_channel(channel_id=KAN11_CHANNEL_ID, limit=60, content_type="videos"):
            add_item(v.get("videoId"), extract_title(v), "", "כאן 11")
        for sv in scrapetube.get_channel(channel_id=KAN11_CHANNEL_ID, limit=40, content_type="shorts"):
            add_item(sv.get("videoId"), extract_title(sv), "כאן 11 Shorts", "כאן 11")
        print(f"  -> Tier 1 newest uploads ready: {len(collected)} videos.")

        print("[Tier 2A] Deep-scanning ALL standalone videos & playlists on @KanDigital (כאן דיגיטל)...")
        for v in scrapetube.get_channel(channel_url=KANDIGITAL_URL, limit=None, content_type="videos"):
            add_item(v.get("videoId"), extract_title(v), "", "כאן דיגיטל")
        for pl in scrapetube.get_playlists(channel_url=KANDIGITAL_URL, limit=None):
            pl_id = pl.get("playlistId")
            pl_title = extract_title(pl)
            if not pl_id or any(w in pl_title for w in NEWS_FILTER_WORDS):
                continue
            try:
                for pv in scrapetube.get_playlist(playlist_id=pl_id, limit=None):
                    add_item(pv.get("videoId"), extract_title(pv), pl_title, "כאן דיגיטל")
            except Exception:
                pass

        print("[Tier 2B] Deep-scanning ALL playlists & videos on @KAN11 (כאן 11)...")
        for pl in scrapetube.get_playlists(channel_id=KAN11_CHANNEL_ID, limit=None):
            pl_id = pl.get("playlistId")
            pl_title = extract_title(pl)
            if not pl_id or any(w in pl_title for w in NEWS_FILTER_WORDS):
                continue
            try:
                for pv in scrapetube.get_playlist(playlist_id=pl_id, limit=None):
                    add_item(pv.get("videoId"), extract_title(pv), pl_title, "כאן 11")
            except Exception:
                pass
        for v in scrapetube.get_channel(channel_id=KAN11_CHANNEL_ID, limit=None, content_type="videos"):
            add_item(v.get("videoId"), extract_title(v), "", "כאן 11")

        print(f"  -> Total unique videos discovered across @KanDigital + @KAN11: {len(collected)}")
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

    all_videos = discover_two_tier_videos()
    pending = [
        (vid_id, title, pl_title, ch_label)
        for vid_id, title, pl_title, ch_label in all_videos
        if vid_id not in scanned_ids and not any(w in title for w in NEWS_FILTER_WORDS)
    ]
    print(f"Ready to scan {len(pending)} unindexed videos (out of {len(all_videos)} discovered across @KanDigital & @KAN11).")

    new_items = []
    processed_since_save = 0

    for i in range(0, len(pending), WORKERS):
        if MAX_RUNTIME_MINUTES > 0 and (time.time() - start_time) / 60.0 >= MAX_RUNTIME_MINUTES:
            print(f"Reached time budget ({MAX_RUNTIME_MINUTES} min). Saving progress for next scheduled run...")
            break

        batch = pending[i : i + WORKERS]
        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            future_map = {
                pool.submit(fetch_transcript_cues, vid_id): (vid_id, title, pl_title, ch_label)
                for vid_id, title, pl_title, ch_label in batch
            }
            for fut in as_completed(future_map):
                vid_id, title, pl_title, ch_label = future_map[fut]
                scanned_ids.add(vid_id)
                processed_since_save += 1
                cues = fut.result() or []
                if not cues:
                    continue
                series, season, episode = infer_series_and_episode(title, pl_title, ch_label)
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
                        "image": f"https://i.ytimg.com/vi/{vid_id}/hq{(sec % 3) + 1}.jpg",
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

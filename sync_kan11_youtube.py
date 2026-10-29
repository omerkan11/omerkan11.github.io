#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
סורק אוטומטי לערוץ הראשי של כאן 11 ביוטיוב (@KAN11 - סדרות ודיגיטל ללא חדשות)
משתמש ב-scrapetube + youtube-transcript-api כדי לעקוף חסימות שרתים ב-GitHub Actions,
ומוסיף אוטומטית כל פרק חדש שעולה לערוץ לתוך memesJson.json.
"""
import json
import re
from pathlib import Path

CHANNEL_URL = "https://www.youtube.com/@KAN11"
OUTPUT_JSON = Path("memesJson.json")
MAX_VIDEOS_TO_CHECK = 40

NEWS_FILTER_WORDS = ["מהדורת חדשות", "חדשות הערב", "חדשות הלילה", "מבזק חדשות"]


def format_mm_ss(sec: float) -> str:
    s = max(0, int(sec))
    return f"{s // 60:02d}:{s % 60:02d}"


def infer_series_and_episode(title: str):
    parts = [p.strip() for p in title.split("|")]
    if len(parts) >= 2:
        left = parts[0]
        right = " - ".join(parts[1:])
        m_season = re.search(r"(עונה\s*\d+)", left)
        if m_season:
            season = m_season.group(1)
            series = left.replace(season, "").strip(" -–|🛒🔥")
        else:
            series = left.strip(" -–|🛒🔥")
            season = "דיגיטל / ספיישל"
        return series or "כאן 11", season, right
    return "כאן 11 דיגיטל", "סדרות", title


def fetch_channel_videos():
    videos = []
    try:
        import scrapetube
        for v in scrapetube.get_channel(channel_url=CHANNEL_URL, limit=MAX_VIDEOS_TO_CHECK):
            vid_id = v.get("videoId")
            title_runs = v.get("title", {}).get("runs", [])
            title = title_runs[0].get("text", "") if title_runs else v.get("title", {}).get("simpleText", "")
            if vid_id and title:
                videos.append((vid_id, title))
    except Exception as e:
        print("scrapetube warning:", e)
    return videos


def fetch_transcript_cues(vid_id: str):
    cues = []
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
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
            for entry in entries:
                start_s = float(entry.get("start", 0) if isinstance(entry, dict) else getattr(entry, "start", 0))
                text = (entry.get("text", "") if isinstance(entry, dict) else getattr(entry, "text", "")).strip()
                text = re.sub(r"<[^>]+>", "", text).replace("\n", " ").strip()
                if len(text) >= 2:
                    cues.append((int(start_s), text))
    except Exception as e:
        print(f"Transcript fetch note for {vid_id}: {e}")
    return cues


def main():
    existing = []
    if OUTPUT_JSON.exists():
        try:
            existing = json.loads(OUTPUT_JSON.read_text(encoding="utf-8"))
        except Exception:
            existing = []

    indexed_video_ids = {item.get("videoId") for item in existing if item.get("videoId")}
    videos = fetch_channel_videos()
    print(f"Found {len(videos)} recent videos on @KAN11.")

    new_items = []
    for vid_id, title in videos:
        if vid_id in indexed_video_ids:
            continue
        if any(w in title for w in NEWS_FILTER_WORDS):
            continue

        cues = fetch_transcript_cues(vid_id)
        if not cues:
            continue

        series, season, episode = infer_series_and_episode(title)
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
        print(f"Indexed {len(cues)} lines from: {title} ({vid_id})")

    if new_items:
        combined = new_items + existing
        OUTPUT_JSON.write_text(json.dumps(combined, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Saved {len(new_items)} new subtitle lines (total: {len(combined)}).")
    else:
        print("No new unindexed episodes with transcripts found on this run.")


if __name__ == "__main__":
    main()

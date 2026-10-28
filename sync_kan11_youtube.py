#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
סורק אוטומטי לערוץ הראשי של כאן 11 ביוטיוב (@KAN11 - סדרות ודיגיטל ללא חדשות)
מושך כתוביות בעברית מכל פרק חדש שעולה לערוץ ומעדכן את memesJson.json אוטומטית.
"""
import json
import os
import re
import subprocess
from pathlib import Path

CHANNEL_URL = "https://www.youtube.com/@KAN11/videos"
OUTPUT_JSON = Path("memesJson.json")
MAX_NEW_VIDEOS_PER_RUN = 25

# מילות סינון כדי לוודא שרק סדרות ודיגיטל נכנסים (ללא משדרי חדשות אם השתרבבו)
NEWS_FILTER_WORDS = ["מהדורת חדשות", "חדשות הערב", "חדשות הלילה", "מבזק חדשות"]


def parse_srt_time(t_str: str) -> float:
    clean = t_str.strip().replace(",", ".")
    parts = clean.split(":")
    if len(parts) == 3:
        return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
    elif len(parts) == 2:
        return float(parts[0]) * 60 + float(parts[1])
    return 0.0


def format_mm_ss(sec: float) -> str:
    s = max(0, int(sec))
    return f"{s // 60:02d}:{s % 60:02d}"


def infer_series_and_episode(title: str):
    # דוגמה: "קופה ראשית עונה 5 | פרק 13 - הו הא מי זה בא?"
    parts = [p.strip() for p in title.split("|")]
    if len(parts) >= 2:
        left = parts[0]
        right = " - ".join(parts[1:])
        m_season = re.search(r"(עונה\s*\d+)", left)
        if m_season:
            season = m_season.group(1)
            series = left.replace(season, "").strip(" -–|")
        else:
            series = left
            season = "דיגיטל / ספיישל"
        return series or "כאן 11", season, right
    return "כאן 11 דיגיטל", "סדרות", title


def parse_srt_content(raw_text: str):
    normalized = raw_text.replace("\r\n", "\n").replace("\r", "\n")
    blocks = re.split(r"\n\s*\n", normalized)
    cues = []
    for block in blocks:
        lines = [l.strip() for l in block.split("\n") if l.strip()]
        if len(lines) < 2:
            continue
        time_idx = next((i for i, l in enumerate(lines) if "-->" in l), -1)
        if time_idx == -1:
            continue
        t_parts = lines[time_idx].split("-->")
        start_s = parse_srt_time(t_parts[0])
        end_s = parse_srt_time(t_parts[1] if len(t_parts) > 1 else t_parts[0])
        mid_s = round((start_s + end_s) / 2.0, 1)
        text = " ".join(lines[time_idx + 1:])
        text = re.sub(r"<[^>]+>", "", text).strip()
        if len(text) >= 2:
            cues.append((mid_s, text))
    return cues


def main():
    existing = []
    if OUTPUT_JSON.exists():
        try:
            existing = json.loads(OUTPUT_JSON.read_text(encoding="utf-8"))
        except Exception:
            existing = []

    indexed_video_ids = {
        item.get("videoId") for item in existing if item.get("videoId")
    }

    tmp_dir = Path("tmp_subs")
    tmp_dir.mkdir(exist_ok=True)

    cmd = [
        "yt-dlp",
        "--skip-download",
        "--write-sub",
        "--write-auto-sub",
        "--sub-lang", "he",
        "--convert-subs", "srt",
        "--playlist-end", str(MAX_NEW_VIDEOS_PER_RUN),
        "--print-to-file", "%(id)s\t%(title)s", str(tmp_dir / "videos_list.txt"),
        "-o", str(tmp_dir / "%(id)s.%(ext)s"),
        CHANNEL_URL,
    ]
    subprocess.run(cmd, check=False)

    list_file = tmp_dir / "videos_list.txt"
    if not list_file.exists():
        print("No new videos fetched.")
        return

    new_items = []
    for line in list_file.read_text(encoding="utf-8").splitlines():
        if "\t" not in line:
            continue
        vid_id, title = line.split("\t", 1)
        if vid_id in indexed_video_ids:
            continue
        if any(w in title for w in NEWS_FILTER_WORDS):
            continue

        srt_candidates = list(tmp_dir.glob(f"{vid_id}*.srt"))
        if not srt_candidates:
            continue

        series, season, episode = infer_series_and_episode(title)
        cues = parse_srt_content(srt_candidates[0].read_text(encoding="utf-8", errors="ignore"))
        for idx, (sec, text) in enumerate(cues):
            int_sec = int(sec)
            new_items.append({
                "id": f"yt-{vid_id}-{idx}",
                "videoId": vid_id,
                "series": series,
                "season": season,
                "episode": episode,
                "timestampSec": int_sec,
                "timestampFormatted": format_mm_ss(int_sec),
                "text": text,
                "image": f"https://i.ytimg.com/vi/{vid_id}/hqdefault.jpg",
                "sourceType": "DEMO",
                "youtubeUrl": f"https://www.youtube.com/watch?v={vid_id}&t={int_sec}s"
            })

    if new_items:
        combined = new_items + existing
        OUTPUT_JSON.write_text(json.dumps(combined, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Added {len(new_items)} new transcript lines from @KAN11!")


if __name__ == "__main__":
    main()

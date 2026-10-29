#!/bin/bash
cd "$(dirname "$0")"
echo "==================================================================="
echo "  סורק מלא של כל ערוץ כאן 11 ביוטיוב (UCDJ6HHS5wkNaSREumdJRYhg)"
echo "  סורק את כל הפלייליסטים, הסדרות, הפרקים והשורטס ללא הגבלה!"
echo "==================================================================="
python3 -m pip install -U youtube-transcript-api scrapetube yt-dlp
export MAX_RUNTIME_MINUTES=0
export SCAN_WORKERS=6
python3 sync_kan11_youtube.py
echo ""
echo "הסריקה הסתיימה! הקובץ memesJson.json עודכן עם כל התמלולים."
read -p "לחץ Enter לסגירה..."

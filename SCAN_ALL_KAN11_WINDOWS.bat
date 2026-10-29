@echo off
chcp 65001 >nul
echo ===================================================================
echo   סורק מלא של כל ערוץ כאן 11 ביוטיוב (UCDJ6HHS5wkNaSREumdJRYhg)
echo   סורק את כל הפלייליסטים, הסדרות, הפרקים והשורטס ללא הגבלה!
echo ===================================================================
echo.
python -m pip install -U youtube-transcript-api scrapetube yt-dlp
set MAX_RUNTIME_MINUTES=0
set SCAN_WORKERS=6
python sync_kan11_youtube.py
echo.
echo ===================================================================
echo   הסריקה הסתיימה! הקובץ memesJson.json עודכן עם כל התמלולים.
echo   כעת תוכל להעלות את memesJson.json ל-GitHub או לפתוח את index.html!
echo ===================================================================
pause

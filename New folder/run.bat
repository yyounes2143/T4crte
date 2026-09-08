@echo off
chcp 65001 >nul
title Smart AI Trading Bot - بوت التداول الذكي
echo.
echo ==========================================
echo   ⚡ Smart AI Spot Trading Bot
echo   بوت التداول الفوري الذكي
echo ==========================================
echo.

:: التحقق من وجود بيئة افتراضية
if not exist ".venv" (
    echo 🔧 إنشاء بيئة افتراضية جديدة...
    where uv >nul 2>&1
    if %errorlevel%==0 (
        uv venv .venv
    ) else (
        python -m venv .venv
    )
    echo ✅ تم إنشاء البيئة الافتراضية
)

:: تفعيل البيئة
call .venv\Scripts\activate.bat

:: تثبيت المتطلبات
echo 📦 التحقق من المتطلبات وتثبيتها...
where uv >nul 2>&1
if %errorlevel%==0 (
    uv pip install -r requirements.txt -q
) else (
    pip install -r requirements.txt -q
)

echo.
echo 🤖 تشغيل المحرك الخلفي (Background Worker)...
start /B pythonw background_worker.py
timeout /t 2 >nul
echo ✅ المحرك الخلفي يعمل في الخلفية

echo.
echo 🌐 تشغيل واجهة التداول...
echo    سيتم فتح المتصفح تلقائياً على http://localhost:8501
echo    اضغط Ctrl+C لإيقاف الواجهة (المحرك الخلفي سيستمر بالعمل)
echo.
streamlit run app.py --server.headless true

pause

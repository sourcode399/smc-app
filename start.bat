@echo off
cd /d "%~dp0"
title SMC + Wyckoff Analyzer
echo ============================================================
echo    SMC + Wyckoff Analyzer dang khoi dong...
echo    Cho vai giay, trinh duyet se tu mo o http://localhost:8501
echo.
echo    DE TAT APP: dong cua so nay
echo ============================================================
echo.
python -m streamlit run app.py
echo.
echo ------------------------------------------------------------
echo App da dung HOAC co loi o tren. Doc dong bao loi (neu co).
echo ------------------------------------------------------------
pause

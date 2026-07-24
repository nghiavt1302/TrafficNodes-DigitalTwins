@echo off
REM ============================================================
REM  Digital Twin L4 Pro - One-click runner (Windows)
REM  Chay backend (FastAPI) + frontend (Godot) chi bang 1 file.
REM ============================================================
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ============================================================
echo   DIGITAL TWIN L4 PRO - Khoi dong project
echo ============================================================

REM ---- 1. Kiem tra Python ----
where python >nul 2>&1
if errorlevel 1 (
    echo [LOI] Khong tim thay Python. Cai Python 3.9+ va them vao PATH.
    pause
    exit /b 1
)

REM ---- 2. Kiem tra Godot ----
where godot >nul 2>&1
if errorlevel 1 (
    echo [LOI] Khong tim thay 'godot' trong PATH.
    echo       Tai Godot 4.x, doi ten exe thanh godot.exe va them vao PATH.
    pause
    exit /b 1
)

REM ---- 3. Cai dependencies backend ----
echo.
echo [1/4] Cai dat Python dependencies... (lan dau co the mat vai phut, vui long doi)
python -m pip install -r backend\requirements.txt
if errorlevel 1 (
    echo [LOI] pip install that bai.
    pause
    exit /b 1
)
echo       Dependencies OK.

REM ---- 4. Chay backend trong cua so rieng (chi khi chua co) ----
REM Kiem tra port 8000 da co backend chay chua -> tranh mo trung (loi Errno 10048)
powershell -NoProfile -Command "try{(New-Object Net.Sockets.TcpClient).Connect('127.0.0.1',8000);exit 0}catch{exit 1}" >nul 2>&1
if not errorlevel 1 (
    echo [2/4] Backend da chay san o port 8000 - dung lai, khong mo trung.
    goto backend_ready
)

echo [2/4] Khoi dong backend (cua so moi)...
start "Digital Twin Backend" cmd /k "cd /d "%~dp0backend" && python main.py"

REM ---- 5. Cho backend san sang (port 8000) ----
echo [3/4] Cho backend san sang (port 8000)...
set /a tries=0
<nul set /p "=  Dang cho backend "
:waitloop
<nul set /p "=."
timeout /t 1 /nobreak >nul
set /a tries+=1
powershell -NoProfile -Command "try{(New-Object Net.Sockets.TcpClient).Connect('127.0.0.1',8000);exit 0}catch{exit 1}" >nul 2>&1
if errorlevel 1 (
    if !tries! lss 30 goto waitloop
    echo.
    echo [CANH BAO] Backend chua len sau 30s, van tiep tuc mo frontend...
) else (
    echo.
    echo   [OK] Backend san sang - http://localhost:8000
)

:backend_ready

REM ---- 6. Import assets + chay frontend ----
echo.
echo [4/4] Import assets Godot (co the mat 10-30s lan dau)...
godot --headless --import "%~dp0digital-twins" >nul 2>&1
echo       Assets OK. Dang mo frontend 3D...
godot --path "%~dp0digital-twins"

echo.
echo Frontend da dong. Dong cua so backend de tat server.
pause

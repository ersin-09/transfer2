@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul
title Dosya Transferi v6 - Konsolsuz Derleme
color 0A

REM --- Script klasörüne git ---
pushd "%~dp0"

echo === Go kontrolü ===
where go >nul 2>nul || (
  echo ❌ Go derleyicisi bulunamadı. https://go.dev/dl adresinden indirip kurun.
  pause & exit /b
)

echo === Python kontrolü ===
set "PYCMD=python"
where %PYCMD% >nul 2>nul || (
  set "PYCMD=py"
  where %PYCMD% >nul 2>nul || (
    echo ❌ Python/py bulunamadı. https://python.org adresinden kurun.
    pause & exit /b
  )
)

echo === PyInstaller kontrolü ===
%PYCMD% -c "import PyInstaller" 1>nul 2>nul || (
  echo 🔧 PyInstaller yukleniyor...
  %PYCMD% -m pip install --upgrade pip
  %PYCMD% -m pip install pyinstaller
)

if not exist dist mkdir dist

echo.
echo ==========================================
echo [A] Go SERVER derleniyor (konsolsuz)...
echo ==========================================
REM === Go cache'i kullanıcı klasörüne zorluyoruz ===
set "GOPATH=%USERPROFILE%\go"
set "GOMODCACHE=%GOPATH%\pkg\mod"
set "GOCACHE=%USERPROFILE%\go-build"
set "PATH=%PATH%;%GOPATH%\bin"
go env -w GOPATH=%GOPATH%
go env -w GOMODCACHE=%GOMODCACHE%
go env -w GOCACHE=%GOCACHE%

if not exist transfer_server_v6.go (
  echo ❌ transfer_server_v6.go bulunamadı!
  pause & exit /b
)

REM go mod hazirla (ilk kez ise)
if not exist go.mod (
  go mod init dtserver
)

REM Server kodu systray kullaniyorsa modulu getir
findstr /C:"github.com/getlantern/systray" transfer_server_v6.go >nul 2>nul && (
  go get github.com/getlantern/systray@v1.2.2
)

go mod tidy

go build -ldflags "-H=windowsgui" -o dist\transfer_server_v6.exe transfer_server_v6.go
if %errorlevel% neq 0 (
  echo ❌ Server derlenemedi.
  pause & exit /b
)
echo ✅ Server olusturuldu: dist\transfer_server_v6.exe

if not exist server_config.json (
  echo ⚠️  server_config.json bulunamadi. Calisirken ayni klasorde olmasi gerekir.
)

echo.
echo ==========================================
echo [A2] Update Helper derleniyor...
echo ==========================================
if exist update_helper.go (
  go build -o dist\update_helper.exe update_helper.go
  if %errorlevel% neq 0 (
    echo ❌ update_helper derlenemedi.
    pause & exit /b
  )
  echo ✅ Update helper olusturuldu: dist\update_helper.exe
) else (
  echo ⚠️  update_helper.go bulunamadi, atlanıyor.
)

echo.
echo ==========================================
echo [B] Go CLIENT derleniyor (konsolsuz)...
echo ==========================================
if not exist transfer_client_v6.go (
  echo ❌ transfer_client_v6.go bulunamadı!
  pause & exit /b
)
go build -ldflags "-H=windowsgui" -o dist\transfer_client_v6.exe transfer_client_v6.go
if %errorlevel% neq 0 (
  echo ❌ Client derlenemedi.
  pause & exit /b
)
echo ✅ Client olusturuldu: dist\transfer_client_v6.exe

echo.
echo ==========================================
echo [C] Birleşik GUI (unified_client_v7) derleniyor...
echo ==========================================
if not exist unified_client_v7.py (
  echo ❌ unified_client_v7.py bulunamadı!
  pause & exit /b
)
set "UNI_ARGS=--add-data ""client_config.json;."""
if exist alicilar.txt set "UNI_ARGS=!UNI_ARGS! --add-data ""alicilar.txt;."""
%PYCMD% -m PyInstaller --noconsole --onefile ^
  --name dosya_transferi_birlesik ^
  !UNI_ARGS! ^
  unified_client_v7.py

if %errorlevel% neq 0 (
  echo ❌ Birleşik GUI derlenemedi.
  pause & exit /b
)

if not exist "dist\dosya_transferi_birlesik.exe" (
  echo ❌ Birleşik GUI EXE'si bulunamadı: dist\dosya_transferi_birlesik.exe
  pause & exit /b
)

echo.
echo ==========================================
echo ✅ Tum EXE'ler basariyla olusturuldu!
echo ==========================================
echo.
echo dist klasorune kopyalandi:
echo   - transfer_server_v6.exe
echo   - transfer_client_v6.exe
if exist "dist\update_helper.exe" echo   - update_helper.exe
if exist "dist\dosya_transferi_birlesik.exe" echo   - dosya_transferi_birlesik.exe
echo.

:MENU
echo [1] Sunucuyu baslat
echo [2] Birlesik GUI'yi ac
echo [3] dist klasorunu ac
echo [4] Cikis
echo.
choice /c 1234 /n /m "Seciminiz [1-4]: "
if errorlevel 4 goto EXIT
if errorlevel 3 goto OPENDIST
if errorlevel 2 goto OPENGUI
if errorlevel 1 goto STARTSERVER

:STARTSERVER
start "" "%cd%\dist\transfer_server_v6.exe"
goto MENU

:OPENGUI
if exist "%cd%\dist\dosya_transferi_birlesik.exe" (
  start "" "%cd%\dist\dosya_transferi_birlesik.exe"
) else (
  echo ❌ dist klasorunde dosya_transferi_birlesik.exe bulunamadi.
)
goto MENU

:OPENDIST
start "" "%cd%\dist"
goto MENU

:EXIT
popd
exit /b

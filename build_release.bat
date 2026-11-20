@echo off
chcp 65001 >nul
cd /d "%~dp0"

set RELEASE=release

echo [1/5] 의존성 설치 및 Playwright 크로미움 준비...
python -m pip install -q pyinstaller "huggingface_hub>=0.28.0" "Pillow>=10.0.0" -r requirements.txt
python -m playwright install chromium
if errorlevel 1 (
    echo Playwright 크로미움 설치 실패
    exit /b 1
)

echo [2/5] PyInstaller로 실행 파일 빌드 중...
python -m PyInstaller --noconfirm "네이트뉴스AI블로그.spec"
if errorlevel 1 (
    echo 빌드 실패
    exit /b 1
)

echo [3/5] 배포 폴더 준비...
if exist "%RELEASE%" rmdir /s /q "%RELEASE%"
mkdir "%RELEASE%"
mkdir "%RELEASE%\data\scraped_news" 2>nul
mkdir "%RELEASE%\data\rewritten_news" 2>nul
mkdir "%RELEASE%\data\image_prompts" 2>nul
mkdir "%RELEASE%\data\images" 2>nul
mkdir "%RELEASE%\data\html_output" 2>nul

echo [4/5] 배포용 파일 복사...
copy /Y "dist\네이트뉴스AI블로그.exe" "%RELEASE%\" >nul
copy /Y "config_배포용.json" "%RELEASE%\config.json" >nul
copy /Y "배포_안내.txt" "%RELEASE%\" >nul
echo {}> "%RELEASE%\github_uploaded_log.json"

if exist "%LOCALAPPDATA%\ms-playwright" (
    echo       Playwright 크로미움 복사 중...
    xcopy /E /I /Y /Q "%LOCALAPPDATA%\ms-playwright" "%RELEASE%\ms-playwright\" >nul
) else (
    echo [경고] ms-playwright 폴더를 찾지 못했습니다. 구글 트렌드 기능이 동작하지 않을 수 있습니다.
)

echo [5/5] ZIP 압축...
powershell -NoProfile -Command "Compress-Archive -Path '%RELEASE%\*' -DestinationPath '네이트뉴스AI블로그_배포.zip' -Force"

echo.
echo ========================================
echo  배포 패키지 생성 완료
echo  폴더: %RELEASE%\
echo  ZIP:  네이트뉴스AI블로그_배포.zip
echo ========================================
echo  다른 사람에게 ZIP 또는 release 폴더를 전달하세요.
pause

@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo [1/3] PyInstaller로 실행 파일 빌드 중...
python -m pip install -q pyinstaller "huggingface_hub>=0.28.0" "Pillow>=10.0.0" -r requirements.txt
python -m PyInstaller --noconfirm "네이트뉴스AI블로그.spec"
if errorlevel 1 (
    echo 빌드 실패
    exit /b 1
)

echo [2/3] dist 폴더에 config.json 복사 (배포용 설정)...
if not exist dist mkdir dist
copy /Y "config_배포용.json" "dist\config.json" >nul

echo [3/3] data 폴더 구조 생성...
mkdir "dist\data\scraped_news" 2>nul
mkdir "dist\data\rewritten_news" 2>nul
mkdir "dist\data\image_prompts" 2>nul
mkdir "dist\data\images" 2>nul
mkdir "dist\data\html_output" 2>nul

echo.
echo 빌드 완료: dist\네이트뉴스AI블로그.exe
pause

# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files, copy_metadata

block_cipher = None

hiddenimports = [
    'huggingface_hub',
    'huggingface_hub.inference._client',
    'huggingface_hub.inference._providers',
    'huggingface_hub.errors',
    'huggingface_hub.utils',
    'huggingface_hub.utils._headers',
    'thumbnail_maker',
    'google_trends_scraper',
    'playwright',
    'playwright.sync_api',
    'playwright._impl',
    'trafilatura',
    'trafilatura.core',
    'trafilatura.metadata',
    'trafilatura.settings',
    'trafilatura.utils',
    'PIL',
    'PIL.Image',
    'PIL.ImageDraw',
    'PIL.ImageFont',
    'PIL.ImageFilter',
    'PIL._imaging',
    'certifi',
    'charset_normalizer',
    'idna',
    'urllib3',
    'lxml',
    'lxml.etree',
    'html5lib',
    'justext',
]

excludes = [
    'torch',
    'torchaudio',
    'tensorflow',
    'scipy',
    'numba',
    'llvmlite',
    'pandas',
    'matplotlib',
    'sklearn',
    'IPython',
    'notebook',
    'pytest',
]

a = Analysis(
    ['gui.py'],
    pathex=[],
    binaries=[],
    datas=(
        collect_data_files('certifi')
        + copy_metadata('Pillow')
        + copy_metadata('huggingface_hub')
        + collect_data_files('playwright')
        + collect_data_files('trafilatura')
    ),
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=['runtime_hook_playwright.py'],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='네이트뉴스AI블로그',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

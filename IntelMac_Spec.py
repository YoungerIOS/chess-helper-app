# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

# 配置相对路径
datas = [('app/images', 'app/images'), ('app/json', 'app/json'), ('app/models', 'app/models'), ('app/Pikafish', 'app/Pikafish'), ('app/ui', 'app/ui'), ('app/chess', 'app/chess'), ('app/tools', 'app/tools'), ('app/themes', 'app/themes'), ('LICENSE', '.'), ('README.md', '.')]
binaries = []
hiddenimports = []
tmp_ret = collect_all('mss')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('pyautogui')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('pynput')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['app/main.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['torch', 'torchvision', 'torchaudio', 'scipy'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='ChessHelper',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['app/icon-chinachess.icns'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='ChessHelper',
)
app = BUNDLE(
    coll,
    name='ChessHelper.app',
    icon='app/icon-chinachess.icns',
    bundle_identifier=None,
)

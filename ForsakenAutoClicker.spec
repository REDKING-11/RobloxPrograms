# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['Cheat.py'],
    pathex=[],
    binaries=[],
    datas=[('template1.png', '.'), ('template2.png', '.'), ('template3.png', '.'), ('template4.png', '.'), ('template5.png', '.'), ('template6.png', '.'), ('template7.png', '.'), ('template8.png', '.'), ('template9.png', '.'), ('template10.png', '.'), ('template11.png', '.'), ('template12.png', '.'), ('template13.png', '.'), ('template14.png', '.'), ('template15.png', '.')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='ForsakenAutoClicker',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['Forsaken.ico'],
)

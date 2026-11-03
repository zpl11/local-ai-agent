# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['ai_chat_client.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[
        'config',
        'ai_logger',
        'tools',
        'agent',
        'compress',
        'todo_manager',
        'gui',
    ],
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
    name='AI聊天客户端_混用版',
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

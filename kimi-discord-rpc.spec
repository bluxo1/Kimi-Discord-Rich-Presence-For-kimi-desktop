# PyInstaller spec: single-file build of kimi-discord-rpc.
#
#   pyinstaller kimi-discord-rpc.spec
#
# config.yaml is intentionally NOT bundled -- the executable reads it from the
# working directory so you can edit settings without rebuilding.

block_cipher = None

a = Analysis(
    ['src/kimi_discord_rpc/__main__.py'],
    pathex=['src'],
    binaries=[],
    datas=[],
    hiddenimports=['pypresence', 'pydantic_settings', 'yaml', 'psutil'],
    hookspath=[],
    runtime_hooks=[],
    excludes=['tkinter', 'unittest'],
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    name='kimi-discord-rpc',
    debug=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    icon=None,
)

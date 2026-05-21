# -*- mode: python ; coding: utf-8 -*-
# =============================================================================
#  CONFIGURACIÓN DE PYINSTALLER — Conversor de Extractos Bancarios
#  Uso: pyinstaller app.spec
# =============================================================================

import sys
sys.setrecursionlimit(5000)

block_cipher = None

a = Analysis(
    ['run.py'],
    pathex=['.'],
    binaries=[
        # Incluir todos los binarios de Poppler en la subcarpeta poppler/ del bundle
        ('poppler_bin/*', 'poppler'),
    ],
    datas=[
        # Archivos fuente que Streamlit necesita ver como archivos separados
        ('app.py', '.'),
        ('utils.py', '.'),
        ('excel.py', '.'),
        # Carpeta de parsers completa
        ('parsers', 'parsers'),
        # Logo de la UI
        ('sg.jpg', '.'),
    ],
    hiddenimports=[
        'streamlit',
        'openpyxl',
        'openpyxl.cell._writer',
        # Asegurar que los módulos de parsers se incluyan
        'parsers.macro',
        'parsers.galicia',
        'parsers.santander',
        'parsers.bancor',
        'parsers.bbva',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='ConversorExtractos',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,                   # Necesario para que Streamlit funcione correctamente
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='ConversorExtractos',
)

@echo off
chcp 65001 >nul 2>&1
title Conversor de Extractos Bancarios

echo.
echo  ========================================================
echo    Conversor de Extractos Bancarios
echo    Macro - Galicia - Santander - Bancor
echo  ========================================================
echo.

:: ── Verificar Python ──
echo  [1/4] Verificando Python...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo  [ERROR] Python no esta instalado o no esta en el PATH.
    echo.
    echo  Para instalar Python:
    echo    1. Ir a https://www.python.org/downloads/
    echo    2. Descargar e instalar Python 3.10 o superior
    echo    3. IMPORTANTE: tildar "Add Python to PATH" en la instalacion
    echo    4. Reiniciar la computadora
    echo    5. Ejecutar este archivo de nuevo
    echo.
    echo  Presiona una tecla para cerrar...
    pause >nul
    exit /b 1
)
python --version
echo  OK
echo.

:: ── Verificar pdftotext (Poppler) ──
echo  [2/4] Verificando Poppler (pdftotext)...
pdftotext -v >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo  [ERROR] Poppler (pdftotext) no esta instalado o no esta en el PATH.
    echo.
    echo  Para instalar Poppler en Windows:
    echo    1. Descargar desde:
    echo       https://github.com/oschwartz10612/poppler-windows/releases
    echo    2. Descomprimir en C:\poppler
    echo    3. Agregar al PATH del sistema:
    echo       - Buscar "Variables de entorno" en el menu inicio
    echo       - Clic en "Editar las variables de entorno del sistema"
    echo       - Clic en "Variables de entorno..."
    echo       - En "Variables del sistema", doble clic en "Path"
    echo       - Clic en "Nuevo" y agregar:  C:\poppler\Library\bin
    echo       - Aceptar todo
    echo    4. Cerrar TODAS las terminales abiertas
    echo    5. Ejecutar este archivo de nuevo
    echo.
    echo  Presiona una tecla para cerrar...
    pause >nul
    exit /b 1
)
echo  OK
echo.

:: ── Instalar dependencias Python ──
echo  [3/4] Verificando dependencias de Python...
pip show streamlit >nul 2>&1
if %errorlevel% neq 0 (
    echo  Instalando streamlit y openpyxl (solo la primera vez, puede tardar)...
    pip install streamlit openpyxl
    if %errorlevel% neq 0 (
        echo.
        echo  [ERROR] No se pudieron instalar las dependencias.
        echo  Intenta ejecutar manualmente en cmd:
        echo    pip install streamlit openpyxl
        echo.
        echo  Presiona una tecla para cerrar...
        pause >nul
        exit /b 1
    )
)
echo  OK
echo.

:: ── Verificar que app.py existe ──
echo  [4/4] Buscando app.py...
if not exist "%~dp0app.py" (
    echo.
    echo  [ERROR] No se encontro app.py
    echo  Asegurate de que INICIAR.bat y app.py esten en la MISMA carpeta.
    echo  Carpeta actual: %~dp0
    echo.
    echo  Presiona una tecla para cerrar...
    pause >nul
    exit /b 1
)
echo  Encontrado: %~dp0app.py
echo.

:: ── Ejecutar la aplicacion ──
echo  ========================================================
echo    Todo listo. Abriendo el conversor en el navegador...
echo    Para cerrar: presiona Ctrl+C o cierra esta ventana.
echo  ========================================================
echo.
cd /d "%~dp0"
streamlit run app.py 

echo.
echo  La aplicacion se cerro.
echo  Presiona una tecla para cerrar esta ventana...
pause >nul

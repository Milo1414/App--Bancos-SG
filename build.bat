@echo off
chcp 65001 >nul
echo ==========================================
echo  Build: Conversor de Extractos Bancarios
echo ==========================================
echo.

:: ---------------------------------------------------------------------------
:: 1. Verificar PyInstaller
:: ---------------------------------------------------------------------------
pyinstaller --version >nul 2>&1
if errorlevel 1 (
    echo PyInstaller no detectado. Instalando...
    pip install pyinstaller
    if errorlevel 1 (
        echo ERROR: No se pudo instalar PyInstaller. Verifique su conexion a internet.
        pause
        exit /b 1
    )
) else (
    echo [OK] PyInstaller detectado.
)

:: ---------------------------------------------------------------------------
:: 2. Verificar carpeta poppler_bin
:: ---------------------------------------------------------------------------
if not exist "poppler_bin" (
    echo ERROR: No se encontro la carpeta "poppler_bin\".
    echo.
    echo Instrucciones:
    echo   1. Descargar Poppler para Windows desde:
    echo      https://github.com/oschwartz10612/poppler-windows/releases
    echo   2. Extraer el contenido de la carpeta "Library\bin\" del ZIP.
    echo   3. Copiar todo ese contenido en una carpeta llamada "poppler_bin\" en la raiz del proyecto.
    echo.
    pause
    exit /b 1
)

:: Verificar que poppler_bin no este vacia
dir /b "poppler_bin\*.*" >nul 2>&1
if errorlevel 1 (
    echo ERROR: La carpeta "poppler_bin\" esta vacia.
    echo Copie los archivos .exe y .dll de Poppler dentro de "poppler_bin\".
    pause
    exit /b 1
)

echo [OK] Carpeta poppler_bin\ detectada con archivos.
echo.

:: ---------------------------------------------------------------------------
:: 3. Ejecutar PyInstaller
:: ---------------------------------------------------------------------------
echo Compilando ejecutable con PyInstaller...
pyinstaller app.spec
if errorlevel 1 (
    echo.
    echo ERROR: La compilacion con PyInstaller fallo.
    pause
    exit /b 1
)

:: ---------------------------------------------------------------------------
:: 4. Copiar archivos adicionales de seguridad (PyInstaller ya deberia incluirlos,
::    pero nos aseguramos por si alguno quedo fuera)
:: ---------------------------------------------------------------------------
if not exist "dist\ConversorExtractos\sg.jpg" (
    copy "sg.jpg" "dist\ConversorExtractos\" >nul 2>&1
)

:: ---------------------------------------------------------------------------
:: 5. Mensaje de exito
:: ---------------------------------------------------------------------------
echo.
echo ==========================================
echo  BUILD EXITOSO
echo ==========================================
echo.
echo El ejecutable se encuentra en:
echo   dist\ConversorExtractos\ConversorExtractos.exe
echo.
echo Para distribuir la app, copie toda la carpeta:
echo   dist\ConversorExtractos\
echo.
pause

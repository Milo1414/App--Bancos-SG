# Instrucciones de instalación — Conversor de Extractos Bancarios

## Qué hace este programa

Convierte extractos bancarios en PDF (Macro, Galicia, Santander, Bancor) a un archivo Excel con formato profesional. Se usa desde el navegador: subís los PDFs, elegís el banco, y descargás el Excel.

---

## Instalación (solo se hace una vez)

### Paso 1: Instalar Python

1. Ir a **https://www.python.org/downloads/**
2. Hacer clic en el botón amarillo **"Download Python 3.x.x"**
3. Ejecutar el instalador descargado
4. **MUY IMPORTANTE**: en la primera pantalla del instalador, tildar la casilla **"Add Python to PATH"** (abajo de todo)
5. Hacer clic en **"Install Now"**
6. Esperar a que termine y cerrar

**Para verificar:** abrir el programa **"Símbolo del sistema"** (buscar "cmd" en el menú inicio) y escribir:
```
python --version
```
Debería mostrar algo como `Python 3.12.x`. Si dice que no se reconoce el comando, reiniciar la computadora e intentar de nuevo.

---

### Paso 2: Instalar Poppler (lector de PDFs)

1. Ir a **https://github.com/oschwartz10612/poppler-windows/releases**
2. Descargar el archivo `.zip` más reciente (ej: `Release-24.08.0-0.zip`)
3. Descomprimir la carpeta en **C:\poppler** (que quede algo como `C:\poppler\Library\bin\pdftotext.exe`)
4. Agregar Poppler al PATH del sistema:
   - Buscar **"Variables de entorno"** en el menú inicio
   - Clic en **"Editar las variables de entorno del sistema"**
   - Clic en el botón **"Variables de entorno..."** (abajo)
   - En la sección **"Variables del sistema"**, buscar la variable **Path** y hacer doble clic
   - Clic en **"Nuevo"** y agregar: `C:\poppler\Library\bin`
   - Aceptar todo y cerrar

**Para verificar:** abrir una terminal **nueva** (cerrar la anterior y abrir otra) y escribir:
```
pdftotext -v
```
Debería mostrar la versión de pdftotext. Si no funciona, verificar que la ruta sea correcta (a veces la carpeta se llama `poppler-24.08.0\Library\bin` en vez de `poppler\Library\bin`).

---

### Paso 3: Instalar las librerías de Python

Abrir una terminal (cmd) y ejecutar:
```
pip install streamlit openpyxl
```
Esperar a que termine (puede tardar un minuto).

---

### Paso 4: Guardar el archivo del programa

Guardar el archivo **app.py** en una carpeta fácil de encontrar, por ejemplo:
```
C:\Extractos\app.py
```

---

## Uso diario

### Abrir el programa

1. Abrir una terminal (cmd)
2. Ir a la carpeta donde guardaste el archivo:
   ```
   cd C:\Extractos
   ```
3. Ejecutar:
   ```
   streamlit run app.py
   ```
4. Se abre el navegador automáticamente con la interfaz

### Usar la interfaz

1. **Elegir el banco** en el desplegable (Macro, Galicia, Santander, Bancor)
2. **Escribir un nombre para la hoja** (ej: "Arezzo - Galicia 176-6")
3. **Subir los PDFs** arrastrándolos o con el botón "Browse files"
4. Hacer clic en **"Agregar hoja"**
5. Repetir para cada cuenta/banco que quieras agregar
6. Hacer clic en **"Descargar Excel"**

### Cerrar el programa

Cerrar la terminal donde se ejecutó el comando `streamlit run app.py`, o presionar `Ctrl+C` en la terminal.

---

## Atajo para abrir más rápido

Si no querés escribir comandos cada vez, podés crear un acceso directo:

1. Hacer clic derecho en el escritorio → **Nuevo** → **Acceso directo**
2. En la ubicación, escribir:
   ```
   cmd /k "cd C:\Extractos && streamlit run app.py"
   ```
3. Ponerle de nombre: **Conversor de Extractos**
4. Doble clic en el acceso directo para abrir

---

## Problemas comunes

| Problema | Solución |
|----------|----------|
| "python no se reconoce como comando" | Reinstalar Python y asegurarse de tildar "Add Python to PATH" |
| "pdftotext no se reconoce como comando" | Verificar que la ruta de Poppler en el PATH sea correcta, y reiniciar la terminal |
| "No se encontraron movimientos" | Verificar que el PDF sea un extracto bancario válido con texto (no escaneado) |
| El navegador no se abre | Ir manualmente a **http://localhost:8501** |
| Streamlit muestra error rojo | Leer el mensaje de error. Generalmente indica qué PDF falló y por qué |

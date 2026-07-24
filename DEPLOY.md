# Publicar la app en internet (Streamlit Community Cloud)

Guía para poner el Conversor de Extractos online, **gratis** y **sin guardar los
archivos** de nadie. Los usuarios finales solo necesitan una **URL** — no
instalan nada.

> ⚠️ **La app no tiene contraseña.** Cualquiera con la URL puede usarla. Tratá
> el link como si fuera privado y no lo publiques.

> **Por qué Streamlit Cloud y no Vercel:** la app es Python/Streamlit (corre un
> servidor), y Vercel está pensado para otro tipo de webs. Streamlit Community
> Cloud está hecho exactamente para esto y es gratuito.

> **Nota técnica (ya resuelta):** la app necesita **dos** `pdftotext` distintos
> y no son intercambiables:
>
> - **Xpdf** para el modo `-table` (Galicia, Santander, Bancor, BBVA, Nación y
>   MacroV2). Poppler no tiene esa opción, por eso el binario de Xpdf para Linux
>   viene incluido en `bin/pdftotext`.
> - **Poppler** para el modo `-layout` (MacroV1). El `-layout` de Xpdf pierde la
>   columna de importes en buena parte de las filas de Macro, así que Macro no
>   reconciliaba. Poppler se instala en el servidor vía `packages.txt`
>   (`poppler-utils`).
>
> En Windows, Poppler sale del PATH y para Xpdf la app busca `bin/pdftotext.exe`
> y las rutas habituales de instalación; si no encuentra ninguno, avisa en
> pantalla con las instrucciones.

---

## Paso 1 — Subir el código a GitHub

Ya tenés el repo `Milo1414/App--Bancos-SG`. Desde la carpeta del proyecto:

```bash
git add -A
git commit -m "Deploy: Streamlit Cloud + login + binario Xpdf Linux"
git push origin v2
```

> Podés desplegar directo desde la rama `v2`, o mergear a `main` primero. En el
> Paso 2 se elige la rama.

## Paso 2 — Crear la app en Streamlit Cloud

1. Entrá a **https://share.streamlit.io** e iniciá sesión **con tu cuenta de
   GitHub** (botón "Continue with GitHub"). Es gratis.
2. Click en **"Create app"** → **"Deploy a public app from GitHub"**.
3. Completá:
   - **Repository:** `Milo1414/App--Bancos-SG`
   - **Branch:** `v2` (o `main` si mergeaste)
   - **Main file path:** `app.py`

## Paso 3 — Deploy

Click en **"Deploy"**. La primera vez tarda unos minutos (instala Python,
`streamlit`, `openpyxl` y la librería `libfontconfig1`). Cuando termina, te da
una URL tipo:

```
https://app-bancos-sg.streamlit.app
```

## Paso 4 — Compartir

Mandales a las personas **la URL**. Abren el link y usan la app igual que en tu
compu: eligen banco, suben PDFs, descargan el Excel.

---

## Volver a poner contraseña

El login por contraseña compartida vivía en `auth.py` y se sacó a pedido. Para
recuperarlo:

```bash
git show 501c17e:auth.py > auth.py
```

Después, en `app.py`, importar `requiere_login` y agregar al inicio de `main()`:

```python
if not requiere_login():
    st.stop()
```

Y cargar la contraseña en Streamlit Cloud → **⋮ / Settings → Secrets**:

```toml
app_password = "ELEGÍ-UNA-CONTRASEÑA-FUERTE"
```

## Actualizar la app (cuando cambies el código)

```bash
git add -A && git commit -m "cambios" && git push origin v2
```

Streamlit Cloud detecta el push y **redespliega solo**.

## Privacidad de los archivos

Los PDF se procesan en memoria y en un archivo temporal que se **borra al
instante** (`app.py`, función de "Agregar hoja"). No hay base de datos ni
almacenamiento: cuando el usuario cierra la pestaña, no queda nada.

---

## Si algo falla

- **"Error installing requirements" / falla al arrancar:** revisá que
  `requirements.txt` y `packages.txt` estén en la raíz del repo.
- **Un banco con `-table` sale vacío o mal alineado:** significa que no se está
  usando el binario incluido. Verificá que `bin/pdftotext` se haya subido al
  repo **sin corromperse** (por eso existe `.gitattributes`). En GitHub el
  archivo debe pesar ~1.6 MB.
- **Logs del servidor:** en la página de tu app en Streamlit Cloud, botón
  **"Manage app"** (abajo a la derecha) muestra la consola con los errores.

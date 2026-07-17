# Publicar la app en internet (Streamlit Community Cloud)

Guía para poner el Conversor de Extractos online, **gratis**, con **login por
contraseña** y **sin guardar los archivos** de nadie. Los usuarios finales solo
necesitan una **URL** y la **contraseña** — no instalan nada.

> **Por qué Streamlit Cloud y no Vercel:** la app es Python/Streamlit (corre un
> servidor), y Vercel está pensado para otro tipo de webs. Streamlit Community
> Cloud está hecho exactamente para esto y es gratuito.

> **Nota técnica (ya resuelta):** la app usa `pdftotext` de **Xpdf** (el modo
> `-table` no existe en Poppler). Por eso el binario de Xpdf para Linux viene
> incluido en `bin/pdftotext` y la app lo usa automáticamente en el servidor.
> En tu Windows sigue usando el `pdftotext` de tu PATH, como siempre.

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
4. **NO hagas deploy todavía** → abrí **"Advanced settings"**.

## Paso 3 — Poner la contraseña (Secrets)

En **Advanced settings → Secrets**, pegá esto (cambiá la contraseña):

```toml
app_password = "ELEGÍ-UNA-CONTRASEÑA-FUERTE"
```

Guardá. Esta contraseña **no queda en el repo**, solo acá.

## Paso 4 — Deploy

Click en **"Deploy"**. La primera vez tarda unos minutos (instala Python,
`streamlit`, `openpyxl` y la librería `libfontconfig1`). Cuando termina, te da
una URL tipo:

```
https://app-bancos-sg.streamlit.app
```

## Paso 5 — Compartir

Mandales a las personas **la URL + la contraseña**. Abren el link, escriben la
contraseña y usan la app igual que en tu compu: eligen banco, suben PDFs,
descargan el Excel.

---

## Cambiar la contraseña más adelante

Streamlit Cloud → tu app → **⋮ / Settings → Secrets** → editás `app_password` →
Save. Se reinicia sola.

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

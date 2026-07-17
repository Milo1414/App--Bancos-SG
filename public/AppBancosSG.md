# App Bancos SG — Estado y pendientes

> Convertidor de extractos bancarios (PDF → Excel).
> Extracción de texto con `pdftotext` (Xpdf 4.06).

## ✅ Hecho

- **Previsualización de bancos**: al elegir un banco se muestra su captura (`public/Captura bancos/`),
  para identificar formato. El banco Macro quedó como **MacroV1**.
- **Parser de Banco Nación** agregado.
- **Excel — columnas de control**:
  - La columna **Saldo** ahora tiene título y barra de color.
  - Se agregan por defecto **"Saldo calculado"** y **"Diferencia"** (verificador: objetivo `Diferencia ≈ 0`).
  - Fila **"Saldo Inicial"** con el saldo del informe más antiguo.
- **Fix de columnas desalineadas en Bancor / Nación / Santander** *(este trabajo)*:
  - Estos tres extractos venían mal porque `pdftotext -layout` corría verticalmente las
    columnas Débito/Crédito. Se cambiaron a **`pdftotext -table`**, que alinea todo.
  - El importe se lee **tal cual del PDF** (débito sin signo). Débito/Crédito:
    Nación y Santander por posición (encabezado por página); **Bancor** por el signo del
    cambio de saldo (no tiene encabezado y las columnas se corren entre páginas).
  - **Verificado** contra los PDF de `public/Bancos/`: `Diferencia = 0` en todas las filas
    (Bancor feb-2026 solo débitos, Bancor mar-2025 con débitos y créditos, Nación, Santander).
- **Fix Galicia y BBVA por `-table`** *(este trabajo)*:
  - **Galicia**: pasó a `-table`; ya no pega texto legal (corta en `Total`/`Consolidado`),
    saldo inicial tomado del encabezado "Saldos". Verificado: **14 movimientos, Diferencia 0**
    (antes 5 y no reconciliaba).
  - **BBVA**: pasó a `-table`; se arregló el filtro de la cuenta en dólares (ahora detecta la
    moneda `CC U$S` vs `CC $`) y se quitó `MOVIMIENTOS` de la lista de descarte (descartaba
    "COMISION POR MOVIMIENTOS"). Verificado: cuenta pesos **10 movimientos, Diferencia 0**,
    cuenta USD excluida.
- **Santander "Las flores" abril-25 verificado**: con `-table` da **288 movimientos,
  Diferencia 0**. Resuelto.

## 🔧 Pendiente

### App (UI)
- **Nombre del archivo al guardar** no se aplica (queda el predeterminado).
- **Nombre de la hoja** cargado desde la app no se aplica realmente.
  *(Requiere reproducir en la app corriendo; ver plan Fase B.)*

### Parsers / extracción (para después)
- **Más bancos / formatos** — agregar formatos como **Macro v2**, con su captura de inicio del PDF.
- **Identificador de cuentas** en resúmenes **Macro**.

---
*Nota: los ítems de Macro (v2, identificador de cuenta) quedaron explícitamente "para después".*

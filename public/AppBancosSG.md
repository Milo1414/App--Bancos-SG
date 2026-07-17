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

## 🔧 Pendiente

### Parsers / extracción
- **Santander abril-25 "Las flores"** — anotaba gastos al final sin sentido.
  *Probablemente resuelto* con el pasaje a `-table`; **falta re-testear** con ese PDF puntual
  (`public/Resumen Las flores abril 2025.pdf`).
- **Bug Galicia** — se pega texto legal como si fuera un movimiento (bloque de garantía de
  depósitos / canales de atención). Además Galicia **no reconcilia** (`Diferencia ≠ 0`) y no
  rotula saldo inicial (se deriva).
- **BBVA no agarra ciertos valores** — ej. `062024portofino.pdf`. No reconcilia por cuenta;
  además el filtro de la cuenta en dólares está roto (`cuenta.startswith("401")` chequea el
  string completo que arranca en `267-`, así que nunca la saltea).
- **Más bancos / formatos** — agregar formatos como **Macro v2**, con su captura de inicio del PDF.
- **Identificador de cuentas** en resúmenes **Macro**.

### App (UI)
- **Nombre del archivo al guardar** no se aplica (queda el predeterminado).
- **Nombre de la hoja** cargado desde la app no se aplica realmente.

---
*Nota: los ítems de Macro (v2, identificador de cuenta) quedaron explícitamente "para después".*

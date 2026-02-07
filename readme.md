# Módulo ARBA - Percepciones IIBB Buenos Aires

Módulo Odoo 17 para la gestión integral del padrón ARBA y la generación del archivo TXT de percepciones IIBB según el formato oficial de posición fija (RN 22/2025).

---

## Funcionalidades

### 1. Importación del Padrón ARBA (`arba.archivo_comprimido`)

- Carga de archivo ZIP con el padrón de contribuyentes de ARBA
- Extracción automática y procesamiento del TXT contenido
- Importación masiva vía `COPY` de PostgreSQL (alta performance)
- Creación automática de impuestos (`account.tax`) por cada alícuota distinta
- Generación de posiciones fiscales (`account.fiscal.position`) con mapeo de impuestos
- Asignación automática de posición fiscal a contactos de Buenos Aires según CUIT

### 2. Consulta del Padrón (`arba.padron`)

- Visualización del padrón importado con búsqueda por CUIT
- Campos: tipo, período, fechas, CUIT, tasa, código

### 3. Exportación de Percepciones (`arba.exportperc`)

- Generación del archivo TXT de percepciones en formato ARBA posición fija (81 chars)
- Filtrado por período (mes/año) y solo comprobantes de venta (`out_invoice`, `out_refund`)
- Descarga directa desde el formulario vía `ir.attachment`
- Validación de CUIT, formato de comprobante y mapeo de tipos

---

## Estructura del módulo

```
arba/
├── __init__.py
├── __manifest__.py
├── readme.md
├── models/
│   ├── __init__.py
│   └── arba.py              # 3 modelos: PadronArba, ArchivoComprimido, TaxExportCsv
├── views/
│   ├── view.xml              # Vista del procesador ZIP
│   ├── padron_arba_view.xml  # Vista del padrón
│   └── exportcsv.xml         # Vista del exportador de percepciones
├── security/
│   └── ir.model.access.csv   # Permisos de acceso
├── data/
│   └── padron.xml            # Acciones programadas (cron)
└── static/src/
    ├── js/main.js
    └── css/style.css
```

---

## Formato del archivo TXT de percepciones

### Especificación: RN 22/2025 - Actividad 7 (Percepciones Régimen General)

- **Formato**: TXT posición fija (sin separadores entre campos)
- **Longitud**: 81 caracteres por línea
- **Sin encabezado ni pie de archivo**
- **Extensión**: `.txt` (se comprime en `.zip` para presentar en ARBA)

### Diseño de registro (11 campos)

| # | Campo | Long | Posición | Formato | Ejemplo |
|---|-------|------|----------|---------|---------|
| 1 | CUIT Contribuyente | 13 | 1-13 | `XX-XXXXXXXX-X` | `20-12345678-9` |
| 2 | Fecha Percepción | 10 | 14-23 | `dd/mm/aaaa` | `06/05/2026` |
| 3 | Tipo Comprobante | 1 | 24 | `F`/`C`/`D`/`R` | `F` |
| 4 | Letra Comprobante | 1 | 25 | `A`/`B`/`C`/` ` | `A` |
| 5 | Nro Sucursal | 5 | 26-30 | Ceros izquierda | `00001` |
| 6 | Nro Emisión | 8 | 31-38 | Ceros izquierda | `00000020` |
| 7 | Monto Imponible | 14 | 39-52 | 11 ent + `.` + 2 dec | `00000001500.00` |
| 8 | Alícuota | 5 | 53-57 | 2 ent + `.` + 2 dec | `03.00` |
| 9 | Importe Percepción | 13 | 58-70 | 10 ent + `.` + 2 dec | `0000000045.00` |
| 10 | Fecha Emisión | 10 | 71-80 | `dd/mm/aaaa` | `06/05/2026` |
| 11 | Tipo Operación | 1 | 81 | `A`/`B`/`M` | `A` |

### Ejemplo de línea generada (81 chars)

```
20-12345678-906/05/2026FA0000100000020000000001500.0003.000000000045.0006/05/2026A
```

### Desglose

```
20-12345678-9        → CUIT contribuyente percibido (13 chars)
06/05/2026           → Fecha percepción (10 chars)
F                    → Tipo: Factura (1 char)
A                    → Letra: A (1 char)
00001                → Sucursal (5 chars)
00000020             → Nro emisión (8 chars)
00000001500.00       → Monto imponible (14 chars)
03.00                → Alícuota (5 chars)
0000000045.00        → Importe percepción (13 chars)
06/05/2026           → Fecha emisión (10 chars)
A                    → Tipo operación: Alta (1 char)
```

### Mapeo de tipos de comprobante Odoo → ARBA

| Prefijo Odoo | Tipo ARBA | Descripción |
|-------------|-----------|-------------|
| `FA-x` | `F` | Factura |
| `FCE-x` | `F` | Factura de Crédito Electrónica |
| `NC-x` | `C` | Nota de Crédito |
| `NCE-x` | `C` | NC de Crédito Electrónica |
| `ND-x` | `D` | Nota de Débito |
| `NDE-x` | `D` | ND de Crédito Electrónica |

La letra (`A`, `B`, `C`) se extrae del sufijo del prefijo Odoo (ej: `FA-A` → letra `A`).

---

## Métodos principales

### `action_generate_csv()` - Generación del TXT

1. Valida que el registro no esté procesado (`state != 'done'`)
2. Calcula rango de fechas del período seleccionado
3. Busca `account.move.line` con:
   - Cuenta contable: `Percepción IIBB ARBA aplicada`
   - Tipo: solo ventas (`out_invoice`, `out_refund`)
   - Estado: publicado (`posted`)
   - Fecha dentro del período
4. Para cada línea construye el registro de 81 chars:
   - Formatea CUIT con guiones (`_formatear_cuit_arba`)
   - Parsea `move_name` para extraer tipo, letra, sucursal y número
   - Mapea tipo comprobante a código ARBA (`_mapear_tipo_comprobante_arba`)
   - Obtiene alícuota del impuesto asociado (`tax_line_id.amount`)
   - Formatea importes con ceros a la izquierda (`_formatear_importe_arba`)
5. Genera `ir.attachment` con el contenido TXT
6. Almacena referencia al attachment para descarga via `download_link`

### `_formatear_importe_arba(importe, enteros)`

Formatea un importe a posición fija ARBA: parte entera con ceros a la izquierda + `.` + 2 decimales.

```python
_formatear_importe_arba(45.0, 10)   → '0000000045.00'  # 13 chars
_formatear_importe_arba(1500.0, 11) → '00000001500.00'  # 14 chars
_formatear_importe_arba(3.0, 2)     → '03.00'           # 5 chars
```

### `_formatear_cuit_arba(cuit)`

Normaliza CUIT a formato ARBA `XX-XXXXXXXX-X` (13 caracteres con guiones).

### `_mapear_tipo_comprobante_arba(tipo_odoo)`

Convierte prefijo Odoo (`FA`, `FCE`, `NC`, `NCE`, `ND`, `NDE`) a código ARBA de 1 carácter (`F`, `C`, `D`).

---

## Instalación

1. Copiar el módulo en el directorio de addons
2. Instalar o actualizar:
   ```bash
   ./odoo-bin -u arba
   ```

## Uso

1. **Importar padrón**: Menú ARBA > Archivos Comprimidos > Subir ZIP > Procesar
2. **Exportar percepciones**: Menú ARBA > Exportar CSV Impuestos > Seleccionar período > Generar CSV > Click en el nombre del archivo para descargar

## Dependencias

- `base`
- `web`
- `mail`

## Normativa

- RN N° 22/2025 ARBA - Diseño de registros vigente desde diciembre 2025
- [Nuevo Diseño de Registro ARWeb (PDF)](https://www.arba.gov.ar/archivos/Publicaciones/Nuevo%20Disenio%20de%20Registro%20ARWeb%20Prod..pdf)

## Licencia

LGPL-3

# Modulo ARBA - Percepciones y Retenciones IIBB (Odoo 17)

## 1. Introduccion

### Que hace Odoo nativamente
Odoo 17 con localizacion argentina maneja impuestos, posiciones fiscales y la estructura contable basica. Los modulos OCA (`account_withholding`, `account_withholding_automatic`, `l10n_ar_account_withholding`) proveen el motor de calculo automatico de retenciones en pagos a proveedores.

### Limitacion
Odoo no sabe que alicuota de percepcion o retencion IIBB aplicar a cada contribuyente de Buenos Aires. Esa informacion esta en el **padron de ARBA**, que se publica mensualmente como archivo ZIP con archivos TXT de percepciones y retenciones. Sin este modulo, la carga es manual.

### Que resuelve este modulo
- **Importa el padron ARBA** (ZIP con Per y Ret) via COPY masivo a PostgreSQL
- **Crea impuestos y posiciones fiscales** de percepcion automaticamente segun las tasas del padron
- **Alimenta `res.partner.perception`** con tasas de retencion del padron, habilitando el calculo automatico OCA
- **Exporta TXT de percepciones** en formato posicion fija 81 chars (RN 22/2025, Actividad 7)
- **Exporta TXT de retenciones** en formato A-122R de 67 chars (Actividad 6)

---

## 2. Funcionamiento para el usuario final

### Flujo completo paso a paso

#### Paso 1: Importar padron ARBA
1. Ir a **ARBA > Archivos Comprimidos**
2. Crear nuevo registro, subir el ZIP del padron mensual de ARBA
3. Al guardar, el sistema descomprime el ZIP automaticamente
4. En el chatter se muestra cuantas lineas tiene cada archivo extraido

#### Paso 2: Procesar ZIP
1. Click en boton **"Procesar ZIP"**
2. El sistema ejecuta:
   - TRUNCATE de la tabla padron (limpia datos anteriores)
   - Importacion de archivos `Per*.txt` (percepciones)
   - Importacion de archivos `Ret*.txt` (retenciones)
   - Creacion de impuestos de percepcion por cada tasa unica
   - Creacion de posiciones fiscales para cada impuesto nuevo
   - Asignacion de posicion fiscal a cada contacto de Buenos Aires segun su CUIT
   - Creacion/actualizacion de `res.partner.perception` con tasas de retencion

#### Paso 2b: Consultar padron importado
- **ARBA > Padron Percepciones** — muestra registros del padron con tipo `P` (percepciones)
- **ARBA > Padron Retenciones** — muestra registros del padron con tipo `R` (retenciones)

Ambas vistas permiten buscar por CUIT y ver la tasa asignada a cada contribuyente.

#### Paso 3: Percepciones en ventas (automatico)
Cuando se emite una factura a un cliente de Buenos Aires:
- La posicion fiscal asignada aplica el impuesto de percepcion correspondiente
- El importe de percepcion se calcula sobre la base imponible con la alicuota del padron

#### Paso 4: Retenciones en pagos a proveedores (automatico)
Cuando se confirma un Payment Group (pago a proveedor de Buenos Aires):
- El motor OCA detecta el impuesto "Ret IIBB ARBA" con `withholding_type=partner_tax`
- Lee la alicuota de `res.partner.perception` del proveedor
- Calcula el importe de retencion automaticamente
- Crea un `account.payment` de retencion dentro del Payment Group

#### Paso 5: Exportar TXT percepciones
1. Ir a **ARBA > Exportar CSV Impuestos**
2. Crear registro, seleccionar mes y anio
3. Click **"Generar CSV"**
4. Descargar el TXT (formato 81 chars, Actividad 7)

#### Paso 6: Exportar TXT retenciones
1. Ir a **ARBA > Exportar TXT Retenciones**
2. Crear registro, seleccionar mes y anio
3. Click **"Generar TXT"**
4. Descargar el TXT (formato A-122R 67 chars, Actividad 6)

### Formatos de archivo generados

#### Percepciones - 81 chars/linea (Actividad 7, RN 22/2025)

| # | Campo | Long | Formato |
|---|-------|------|---------|
| 1 | CUIT Contribuyente | 13 | `XX-XXXXXXXX-X` |
| 2 | Fecha Percepcion | 10 | `dd/mm/aaaa` |
| 3 | Tipo Comprobante | 1 | F/C/D |
| 4 | Letra Comprobante | 1 | A/B/C/E |
| 5 | Nro Sucursal | 5 | `00001` |
| 6 | Nro Emision | 8 | `00000001` |
| 7 | Monto Imponible | 14 | 11ent.2dec |
| 8 | Alicuota | 5 | 2ent.2dec |
| 9 | Importe Percepcion | 13 | 10ent.2dec |
| 10 | Fecha Emision | 10 | `dd/mm/aaaa` |
| 11 | Tipo Operacion | 1 | A=Alta |

#### Retenciones - 67 chars/linea (Actividad 6, formato A-122R)

| # | Campo | Long | Formato |
|---|-------|------|---------|
| 1 | Nro Transaccion | 20 | Secuencial zfill |
| 2 | CUIT Retenido | 11 | Sin guiones |
| 3 | Sucursal | 5 | `00001` |
| 4 | Fecha Operacion | 10 | `dd/mm/aaaa` |
| 5 | Alicuota | 5 | 2ent.2dec |
| 6 | Base Imponible | 16 | 13ent.2dec |

---

## 3. Parametrizacion

### Requisitos previos
- Odoo 17 con localizacion argentina (`l10n_ar`)
- Modulos OCA instalados: `account_withholding`, `account_withholding_automatic`, `l10n_ar_account_withholding`, `l10n_ar_percepciones`

### Paso 1: Instalar/actualizar el modulo
```
Aplicaciones > Buscar "arba" > Instalar o Actualizar
```
Al instalar se crean automaticamente:
- Grupo de impuestos **"Ret IIBB ARBA"**
- Impuesto **"Ret IIBB ARBA"** (supplier, `withholding_type=partner_tax`)
- Secuencia **"Retencion IIBB ARBA"** (`RET-ARBA-00000001`)

### Paso 2: Configurar cuenta contable del impuesto
1. Ir a **Contabilidad > Configuracion > Impuestos**
2. Buscar **"Ret IIBB ARBA"**
3. En la pestana "Definicion", agregar la linea de distribucion contable:
   - Cuenta: la cuenta de retenciones IIBB que use la empresa (ej: `2.1.06.01.002`)
4. Guardar

### Paso 3: Habilitar retenciones automaticas
1. Ir a **Ajustes > Compañias > [tu compañia]**
2. Pestaña **"Retenciones"**
3. Activar checkbox **"Retenciones automaticas"**

### Paso 4: Verificar grupo de impuestos de percepciones
El modulo asume que existe un grupo **"Perc IIBB ARBA"** con al menos un impuesto base de tipo venta. Si no existe, crearlo manualmente antes de procesar el padron.

### Paso 5: Importar padron mensual
1. Descargar ZIP del padron desde ARBA
2. Ir a **ARBA > Archivos Comprimidos > Crear**
3. Subir el ZIP, completar nombre (ej: "Padron Febrero 2026")
4. Guardar (descomprime automatico)
5. Click **"Procesar ZIP"** (crea impuestos, posiciones fiscales, retenciones en partners)

### Datos del padron
El ZIP de ARBA contiene:
- `Per*.txt` — percepciones (tipo empieza con `P`)
- `Ret*.txt` — retenciones (tipo empieza con `R`)

Ambos archivos usan formato CSV con separador `;` y 10 columnas:
```
tipo;periodo;inicio;fin;cuit;par_uno;par_dos;par_tres;tasa;codigo
```

---

## 4. Referencia tecnica

### Arquitectura

```
arba/
├── __manifest__.py
├── models/
│   ├── __init__.py
│   ├── arba.py                  # PadronArba + ArchivoComprimido + TaxExportCsv
│   └── arba_ret_export.py       # TaxExportRet (export TXT retenciones)
├── views/
│   ├── view.xml                 # Vistas ArchivoComprimido + menu raiz ARBA
│   ├── padron_arba_view.xml     # Vistas padron (percepciones + retenciones filtradas)
│   ├── exportcsv.xml            # Vistas export percepciones
│   ├── exportret.xml            # Vistas export retenciones
│   └── res_company_view.xml     # Checkbox retenciones automaticas en compañia
├── data/
│   ├── padron.xml               # Crons de padron
│   └── ret_tax_data.xml         # Tax group + tax + secuencia retenciones
├── security/
│   └── ir.model.access.csv
└── static/src/
    ├── js/main.js
    └── css/style.css
```

### Modelos

| Modelo | Descripcion | Tabla |
|--------|-------------|-------|
| `arba.padron` | Padron ARBA (percepciones + retenciones) | `arba_padron` |
| `arba.archivo_comprimido` | Carga y procesamiento de ZIP | `arba_archivo_comprimido` |
| `arba.exportperc` | Exportacion TXT percepciones 81 chars | `arba_exportperc` |
| `arba.exportret` | Exportacion TXT retenciones 67 chars | `arba_exportret` |

### Dependencias

```python
'depends': ['base', 'web', 'mail', 'account', 'l10n_ar_percepciones', 'account_withholding_automatic']
```

- `account` — modelos base de contabilidad
- `l10n_ar_percepciones` — modelo `res.partner.perception` (tax_id + percent por partner)
- `account_withholding_automatic` — motor de calculo automatico de retenciones (`withholding_type`, `get_partner_alicuot`)

### Metodos clave

#### `ArchivoComprimido._procesar_zip_comprimido(ruta_zip)`
Descomprime ZIP, ejecuta TRUNCATE una sola vez, luego procesa archivos `Per*.txt` y `Ret*.txt`.

```python
# Por que: TRUNCATE una sola vez antes de procesar Per y Ret
# para no borrar retenciones al cargar percepciones o viceversa
self.env.cr.execute("TRUNCATE TABLE arba_padron RESTART IDENTITY")

for archivo in archivos_extraidos:
    nombre = os.path.basename(archivo)
    if 'Per' in nombre:
        self._procesar_txt_en_perc(archivo)
    elif 'Ret' in nombre:
        self._procesar_txt_en_ret(archivo)
```

#### `ArchivoComprimido._procesar_txt_en_perc(archivo)` / `_procesar_txt_en_ret(archivo)`
Importacion masiva via `COPY` de PostgreSQL. Ambos metodos tienen la misma logica:
- Parsean CSV con `;` separador
- Convierten fechas `ddmmaaaa` → `aaaa-mm-dd`
- Reemplazan coma por punto en tasa
- Escriben en buffer y ejecutan `COPY arba_padron FROM STDIN`

#### `ArchivoComprimido._actualizar_retenciones_partners()`
Alimenta `res.partner.perception` con tasas de retencion del padron. Este es el nexo con el motor OCA:

```python
# Patron: data-driven — solo alimentamos datos, la logica la ejecuta OCA
# 1. Busca impuesto 'Ret IIBB ARBA' (supplier)
# 2. Itera partners de Buenos Aires (state_id=554)
# 3. Para cada CUIT en padron con tipo='R%':
#    - Crea/actualiza res.partner.perception con tax_id + percent
```

El motor OCA luego ejecuta:
```
Payment Group confirm
  → compute_withholdings()
    → account.tax.get_withholding_vals()
      → get_partner_alicuot() → lee perception_ids → percent/100
      → base_amount * alicuota = importe retencion
```

#### `TaxExportRet.action_generate_txt()`
Busca `account.payment` con `tax_withholding_id = Ret IIBB ARBA`, construye lineas de 67 chars formato A-122R y genera `ir.attachment` con link de descarga.

### Data XML — `ret_tax_data.xml`

```xml
<!-- Grupo de impuestos -->
<record id="tax_group_ret_iibb_arba" model="account.tax.group">
  <field name="name">Ret IIBB ARBA</field>
</record>

<!-- Impuesto de retencion -->
<record id="tax_ret_iibb_arba" model="account.tax">
  <field name="name">Ret IIBB ARBA</field>
  <field name="type_tax_use">supplier</field>
  <field name="withholding_type">partner_tax</field>
  <field name="withholding_amount_type">untaxed_amount</field>
</record>

<!-- Secuencia -->
<record id="seq_ret_iibb_arba" model="ir.sequence">
  <field name="name">Retencion IIBB ARBA</field>
  <field name="code">account.payment.ret.iibb.arba</field>
  <field name="prefix">RET-ARBA-</field>
  <field name="padding">8</field>
</record>
```

### Seguridad

| Modelo | Grupo | Read | Write | Create | Delete |
|--------|-------|------|-------|--------|--------|
| `arba.archivo_comprimido` | Todos | Si | Si | Si | Si |
| `arba.padron` | Todos | Si | Si | Si | Si |
| `arba.exportperc` | `base.group_user` | Si | Si | Si | Si |
| `arba.exportret` | `base.group_user` | Si | Si | Si | Si |

### Flujo de integracion completo

```
1. PADRON IMPORT:
   ZIP → _procesar_zip_comprimido()
     → TRUNCATE arba_padron (1 vez)
     → Per*.txt → _procesar_txt_en_perc()   (percepciones)
     → Ret*.txt → _procesar_txt_en_ret()    (retenciones)

   "Procesar ZIP" → actualiza_imp_pos_fiscal()
     → [percepciones: taxes + fiscal positions + partners] (existente)
     → _actualizar_retenciones_partners()  (NUEVO)
       → arba.padron WHERE tipo LIKE 'R%'
       → CREATE/UPDATE res.partner.perception (tax=Ret IIBB ARBA, percent=tasa)

2. CALCULO AUTOMATICO (motor OCA):
   Payment Group confirm → compute_withholdings()
     → account.tax(Ret IIBB ARBA).get_withholding_vals()
       → get_partner_alicuot() → lee perception_ids → percent/100
       → base_amount * alicuota = importe retencion
     → create_payment_withholdings() → crea account.payment automatico

3. CERTIFICADO (motor OCA):
   account.payment → btn_print_withholding() → QWeb PDF

4. EXPORT TXT:
   arba.exportret → action_generate_txt()
     → account.payment WHERE tax_withholding_id = Ret IIBB ARBA
     → 67 chars/linea formato A-122R
     → ir.attachment → download link
```

### Verificacion / Testing

1. **Instalar modulo**: Upgrade del modulo arba, verificar que crea tax group + tax + secuencia
2. **Configurar tax**: Asignar cuenta contable al impuesto Ret IIBB ARBA
3. **Habilitar retenciones automaticas**: Ajustes > Compañias > [compañia] > pestaña Retenciones > checkbox
4. **Importar padron**: Subir ZIP con Per y Ret → verificar que `arba.padron` tiene registros tipo R
5. **Procesar ZIP**: Click "Procesar ZIP" → verificar que `res.partner.perception` se creo para partners de BA con tax Ret IIBB ARBA
6. **Pago a proveedor**: Crear Payment Group → confirmar → verificar retencion automatica con alicuota del padron
7. **Certificado**: Imprimir retencion desde el pago → verificar PDF
8. **Export TXT**: Generar TXT retenciones → verificar formato 67 chars y descarga

### Fuentes
- ARBA nuevo diseno registro (vigente): https://www.arba.gov.ar/archivos/Publicaciones/Nuevo%20Disenio%20de%20Registro%20ARWeb%20Prod..pdf
- ARBA diseno viejo: https://www.arba.gov.ar/archivos/Publicaciones/dise%C3%B1o_de_registro_iibbddjjweb.pdf
- ARBA RN 22/2025: https://www.arba.gov.ar/archivos/Tramites/RN%2022-2025.pdf
- Motor OCA retenciones: https://github.com/OCA/l10n-argentina

# Modulo ARBA - Percepciones y Retenciones IIBB + Certificados (Odoo 17)

## 1. Introduccion

### Que hace Odoo nativamente
Odoo 17 con localizacion argentina maneja impuestos, posiciones fiscales y la estructura contable basica. Los modulos OCA (`account_withholding`, `account_withholding_automatic`, `l10n_ar_account_withholding`) proveen el motor de calculo automatico de retenciones en pagos a proveedores. El modulo OCA `l10n_ar_report_withholding` provee un boton para imprimir certificados de retencion.

### Limitaciones sin este modulo
1. **Padron ARBA**: Odoo no sabe que alicuota de percepcion o retencion IIBB aplicar a cada contribuyente de Buenos Aires. Esa informacion esta en el **padron de ARBA**, que se publica mensualmente como ZIP con TXT de percepciones y retenciones.
2. **Certificado de retencion roto**: El template OCA usa `o.reconciled_invoice_ids` y `o._get_invoice_payment_amount()` que **no existen** en `account.payment` de Odoo 17. El PDF sale incompleto o da error.

### Que resuelve este modulo
- **Importa el padron ARBA** (ZIP con Per y Ret) via COPY masivo a PostgreSQL
- **Percepciones automaticas**: Crea impuestos de venta + posiciones fiscales + asigna posicion fiscal al partner segun tasa del padron
- **Retenciones automaticas**: Alimenta `res.partner.perception` con tasas de retencion, habilitando el motor OCA
- **Exporta TXT percepciones** formato 81 chars (RN 22/2025, Actividad 7)
- **Exporta TXT retenciones** formato A-122R de 67 chars (Actividad 6)
- **Certificado de retencion**: Override del template OCA roto con certificado legal completo (IIBB y Ganancias)
- **Tracking de retenciones**: Diagnostico paso a paso en el chatter del Payment Group

---

## 2. Funcionamiento para el usuario final

### Conceptos clave: Percepciones vs Retenciones

| | Percepciones | Retenciones |
|--|-------------|-------------|
| **Que es** | Cobro anticipado de IIBB que hacemos a nuestros clientes al venderles | Descuento de IIBB que hacemos a nuestros proveedores al pagarles |
| **Cuando se aplica** | Al emitir factura de venta | Al confirmar un pago a proveedor |
| **Donde se configura** | Posicion fiscal del partner | `perception_ids` del partner (pestaña Alicuotas) |
| **Como se aplica** | Automatico por posicion fiscal en la factura | Motor OCA automatico en el Payment Group |
| **Archivo ARBA** | Per*.txt (tipo P en padron) | Ret*.txt (tipo R en padron) |
| **Actividad ARBA** | 7 (Percepciones Regimen General) | 6 (Retenciones Regimen General) |

### Flujo completo paso a paso

#### Paso 1: Importar padron ARBA
1. Ir a **ARBA > Archivos Comprimidos**
2. Crear nuevo registro, subir el ZIP del padron mensual de ARBA
3. Al guardar, el sistema descomprime el ZIP automaticamente
4. En el chatter se muestra cuantas lineas tiene cada archivo extraido

#### Paso 2: Procesar ZIP (boton "Procesar ZIP")
Este boton ejecuta todo el proceso automatico:

```
ZIP del padron
  |
  ├─ TRUNCATE arba_padron (limpia datos anteriores)
  ├─ Importa Per*.txt → registros tipo P (percepciones)
  └─ Importa Ret*.txt → registros tipo R (retenciones)
       |
       ├── PERCEPCIONES (ventas):
       │   ├─ Crea impuestos de venta por cada tasa unica (ej: "IIBB ARBA 3.00%")
       │   ├─ Crea posiciones fiscales (ej: "Ventas Iva IIBB ARBA 3.00")
       │   └─ Asigna posicion fiscal a cada contacto de Buenos Aires segun su CUIT
       │
       └── RETENCIONES (compras):
           └─ Crea/actualiza res.partner.perception (pestaña "Alicuotas" del partner)
              con impuesto "Ret IIBB ARBA" y el % del padron
```

#### Donde se cargan las percepciones (ventas)

Las percepciones **NO** van en la pestaña "Alicuotas" del partner. Van en la **posicion fiscal**:

1. **Contactos** → abrir partner → pestaña **Contabilidad**
2. Campo **Posicion Fiscal** → ej: `Ventas Iva IIBB ARBA 3.00`
3. Esa posicion fiscal tiene un mapeo de impuestos que agrega automaticamente el impuesto de percepcion IIBB en cada factura de venta

**Ejemplo**: Si SINTEPLAST tiene tasa de percepcion 3% en el padron ARBA:
- El sistema le asigna posicion fiscal "Ventas Iva IIBB ARBA 3.00"
- Al emitir una factura de venta a SINTEPLAST, se agrega automaticamente el impuesto "IIBB ARBA 3.00%"
- La factura incluye la linea de percepcion

| Paso | Que pasa | Donde se ve |
|------|----------|-------------|
| Padron dice tasa 3% tipo P | Se crea impuesto "IIBB ARBA 3.00%" tipo venta | Contabilidad > Impuestos |
| Se crea posicion fiscal | "Ventas Iva IIBB ARBA 3.00" con mapeo al impuesto | Contabilidad > Posiciones Fiscales |
| Se asigna al partner | Campo "Posicion Fiscal" del partner | Contactos > partner > Contabilidad |
| Se emite factura | La posicion fiscal agrega el impuesto de percepcion | Factura de venta > linea de impuesto |

#### Donde se cargan las retenciones (compras)

Las retenciones van en la pestaña **Alicuotas** del partner:

1. **Contactos** → abrir partner → pestaña **Contabilidad** (o **Alicuotas**)
2. Seccion **Percepciones Definidas** (`perception_ids`)
3. Tabla con columnas: **Impuesto | Porcentaje | Fecha Desde**

**Ejemplo**: Si SINTEPLAST tiene tasa de retencion 0.7% en el padron ARBA:

| Impuesto | Porcentaje | Fecha Desde |
|----------|-----------|-------------|
| Ret IIBB ARBA | 0.7 | (fecha del padron) |

Al confirmar un Payment Group (pago a proveedor):
- El motor OCA detecta el impuesto "Ret IIBB ARBA" con `withholding_type=partner_tax`
- Lee la alicuota de `perception_ids` del proveedor (0.7%)
- Calcula: base imponible x 0.007 = importe retencion
- Crea automaticamente un pago de retencion dentro del Payment Group

| Paso | Que pasa | Donde se ve |
|------|----------|-------------|
| Padron dice tasa 0.7% tipo R | Se crea registro en `perception_ids` del partner | Contactos > partner > Alicuotas |
| Se confirma Payment Group | Motor OCA lee alicuota y calcula retencion | Payment Group > pagos de retencion |
| Se crea pago de retencion | `account.payment` con tax_withholding_id = Ret IIBB ARBA | Payment Group > detalle |

#### Paso 2b: Consultar padron importado
- **ARBA > Padron Percepciones** — registros tipo P (percepciones). Buscar por CUIT para ver tasa
- **ARBA > Padron Retenciones** — registros tipo R (retenciones). Buscar por CUIT para ver tasa

#### Paso 3: Exportar TXT percepciones
1. Ir a **ARBA > Exportar CSV Impuestos**
2. Crear registro, seleccionar mes y anio
3. Click **"Generar CSV"**
4. Descargar el TXT (formato 81 chars, Actividad 7)

#### Paso 4: Exportar TXT retenciones
1. Ir a **ARBA > Exportar TXT Retenciones**
2. Crear registro, seleccionar mes y anio
3. Click **"Generar TXT"**
4. Descargar el TXT (formato A-122R 67 chars, Actividad 6)

#### Paso 5: Imprimir certificado de retencion
1. Abrir un **Payment Group confirmado**
2. Expandir el pago de retencion
3. Click boton **"Imprimir Retencion"**
4. Se genera PDF con certificado legal completo

El certificado incluye:
- **Agente de retencion**: razon social, CUIT, domicilio, condicion IVA, Nro IIBB (si aplica)
- **Sujeto retenido**: razon social, CUIT, domicilio, condicion IVA
- **Datos de la retencion**: nro certificado, fecha, impuesto, base imponible, alicuota, importe
- **Regimen**: "Regimen General IIBB Buenos Aires" o codigo de regimen Ganancias
- **Comprobantes asociados**: tabla con facturas del Payment Group
- **Espacio para firma y sello**

#### Tracking de retenciones (diagnostico)
Al hacer click en "Calcular" en un Payment Group, el chatter muestra un log paso a paso:
- Datos del pago (partner, CUIT, monto)
- Impuestos evaluados y sus tipos
- Alicuota encontrada (o no) en perception_ids
- Calculo detallado (base, minimo, retencion)
- Diario utilizado

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
- Para certificados: `l10n_ar_report_withholding`, `l10n_ar_report_payment_group`

### Paso 1: Instalar/actualizar el modulo
```
Aplicaciones > Buscar "arba" > Instalar o Actualizar
```
Al instalar se crean automaticamente:
- Grupo de impuestos **"Ret IIBB ARBA"**
- Impuesto **"Ret IIBB ARBA"** (supplier, `withholding_type=partner_tax`)
- Secuencia **"Retencion IIBB ARBA"** (`RET-ARBA-00000001`)

### Paso 2: Configurar cuenta contable del impuesto de retencion
1. Ir a **Contabilidad > Configuracion > Impuestos**
2. Buscar **"Ret IIBB ARBA"**
3. En la pestana "Definicion", agregar la linea de distribucion contable:
   - Cuenta: la cuenta de retenciones IIBB que use la empresa (ej: `2.1.06.01.002`)
4. Guardar

### Paso 3: Configurar diario de retenciones
El motor OCA necesita un diario tipo Efectivo con metodo de pago "Withholding" para crear los pagos de retencion.

1. Ir a **Contabilidad > Configuracion > Diarios**
2. Crear nuevo diario:
   - **Nombre:** `Retenciones IIBB ARBA`
   - **Tipo:** Efectivo
   - **Cuenta:** cuenta contable de retenciones IIBB
3. En **Pagos salientes**, agregar metodo de pago: **Withholding**
4. Guardar

**Importante:** verificar que **ningun otro diario** tenga el metodo Withholding configurado si no corresponde. El motor OCA toma el primer diario que encuentre con ese metodo. Si el diario se llama "Retenciones SUSS" o "Cheques Rechazados", ese nombre aparecera en el recibo.

### Paso 4: Habilitar retenciones automaticas
1. Ir a **Ajustes > Compañias > [tu compañia]**
2. Pestana **"Retenciones"**
3. Activar checkbox **"Retenciones automaticas"**

### Paso 5: Verificar grupo de impuestos de percepciones
El modulo asume que existe un grupo **"Perc IIBB ARBA"** con al menos un impuesto base de tipo venta. Si no existe, crearlo manualmente antes de procesar el padron:
1. **Contabilidad > Configuracion > Grupos de Impuestos** → crear "Perc IIBB ARBA"
2. **Contabilidad > Configuracion > Impuestos** → crear al menos un impuesto base:
   - Nombre: `IIBB ARBA 0.00%`
   - Tipo: Ventas
   - Grupo: Perc IIBB ARBA
   - Monto: 0
3. Crear una **posicion fiscal** base que use ese impuesto como destino en mapeo de impuestos

### Paso 6: Importar padron mensual
1. Descargar ZIP del padron desde ARBA
2. Ir a **ARBA > Archivos Comprimidos > Crear**
3. Subir el ZIP, completar nombre (ej: "Padron Febrero 2026")
4. Guardar (descomprime automatico)
5. Click **"Procesar ZIP"** → ejecuta todo:
   - Crea impuestos de percepcion por tasa
   - Crea posiciones fiscales
   - Asigna posicion fiscal a partners de Buenos Aires (percepciones)
   - Crea/actualiza `perception_ids` en partners de Buenos Aires (retenciones)

### Verificacion post-importacion

| Verificar | Donde | Que buscar |
|-----------|-------|------------|
| Padron importado | ARBA > Padron Percepciones/Retenciones | Registros con CUIT y tasa |
| Impuestos de percepcion | Contabilidad > Impuestos > filtrar por grupo "Perc IIBB ARBA" | Un impuesto por cada tasa unica |
| Posiciones fiscales | Contabilidad > Posiciones Fiscales | "Ventas Iva IIBB ARBA X.XX" |
| Posicion fiscal en partner | Contactos > partner de BA > Contabilidad | Campo "Posicion Fiscal" asignada |
| Alicuota retencion en partner | Contactos > partner de BA > Alicuotas | Linea "Ret IIBB ARBA" con % |

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
│   ├── arba.py                    # PadronArba + ArchivoComprimido + TaxExportCsv
│   ├── arba_ret_export.py         # TaxExportRet (export TXT retenciones)
│   ├── account_payment.py         # Helpers certificado retencion (QWeb)
│   └── account_payment_group.py   # Tracking retenciones en chatter
├── report/
│   └── report_withholding_certificate.xml  # Certificado retencion (override OCA)
├── views/
│   ├── view.xml                   # Vistas ArchivoComprimido + menu raiz ARBA
│   ├── padron_arba_view.xml       # Vistas padron (percepciones + retenciones filtradas)
│   ├── exportcsv.xml              # Vistas export percepciones
│   ├── exportret.xml              # Vistas export retenciones
│   └── res_company_view.xml       # Checkbox retenciones automaticas en compañia
├── data/
│   ├── padron.xml                 # Crons de padron
│   └── ret_tax_data.xml           # Tax group + tax + secuencia retenciones
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
| `account.payment` (inherit) | Helpers para certificado QWeb | — |
| `account.payment.group` (inherit) | Tracking retenciones en chatter | — |

### Dependencias

```python
'depends': [
    'base', 'web', 'mail', 'account',
    'l10n_ar_percepciones', 'account_withholding_automatic',
    'l10n_ar_report_withholding', 'l10n_ar_report_payment_group',
]
```

- `account` — modelos base de contabilidad
- `l10n_ar_percepciones` — modelo `res.partner.perception` (tax_id + percent por partner)
- `account_withholding_automatic` — motor de calculo automatico de retenciones (`withholding_type`, `get_partner_alicuot`)
- `l10n_ar_report_withholding` — template base del certificado de retencion (que este modulo overridea)
- `l10n_ar_report_payment_group` — recibo de pago del Payment Group (no se modifica)

### Metodos clave

#### `ArchivoComprimido.guardar_y_procesar_zip()`
Descomprime el ZIP subido al directorio `/tmp/arba` y delega el procesamiento.

#### `ArchivoComprimido._procesar_zip_comprimido(ruta_zip)`
Ejecuta TRUNCATE una sola vez, luego procesa archivos `Per*.txt` y `Ret*.txt`:

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
Importacion masiva via `COPY` de PostgreSQL:
- Parsean CSV con `;` separador
- Convierten fechas `ddmmaaaa` → `aaaa-mm-dd`
- Reemplazan coma por punto en tasa
- Ejecutan `COPY arba_padron FROM STDIN`

#### `ArchivoComprimido.actualiza_imp_pos_fiscal()`
Orquesta toda la logica post-importacion de percepciones y retenciones:

```python
# 1. Lee tasas unicas del padron
# 2. Crea impuestos de venta por cada tasa (grupo "Perc IIBB ARBA")
# 3. Llama a _posiciones_fiscales() → crea posiciones fiscales
# 4. Llama a _posicion_impositiva_contacto() → asigna pos fiscal a partners
# 5. Llama a _actualizar_retenciones_partners() → crea/actualiza perception_ids
```

#### `ArchivoComprimido._posiciones_fiscales()`
Crea posiciones fiscales para impuestos de percepcion que aun no tienen una:
- Toma una posicion fiscal existente como plantilla
- La copia cambiando nombre y mapeo de impuesto destino

#### `ArchivoComprimido._posicion_impositiva_contacto()`
Asigna posicion fiscal a cada contacto de Buenos Aires:

```python
# 1. Busca partners con state_id = 554 (Buenos Aires)
# 2. Para cada partner, busca su CUIT en arba_padron
# 3. Busca el impuesto de venta con esa tasa
# 4. Busca la posicion fiscal que mapea a ese impuesto
# 5. Escribe property_account_position_id en el partner
```

#### `ArchivoComprimido._actualizar_retenciones_partners()`
Alimenta `res.partner.perception` con tasas de retencion del padron:

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

#### `AccountPayment` — Helpers para certificado QWeb

| Metodo | Retorna | Uso en template |
|--------|---------|-----------------|
| `is_iibb_withholding()` | Bool | `t-if` para secciones IIBB |
| `is_ganancias_withholding()` | Bool | `t-if` para secciones Ganancias |
| `get_withholding_type_label()` | String | Titulo del certificado |
| `get_withholding_alicuota()` | Float | % alicuota (desde perception o regimen) |
| `get_withholding_invoices()` | Recordset | Facturas del payment group |
| `get_regimen_ganancias_label()` | String | Codigo + concepto regimen |

#### `AccountPaymentGroup.compute_withholdings()` — Override tracking
Antes de ejecutar el calculo real (`super()`), loguea en el chatter del Payment Group:
- Datos del pago (partner, CUIT, monto, automatic_withholdings)
- Impuestos evaluados y sus tipos
- Para cada impuesto: alicuota buscada, calculo de montos, resultado
- Diario de retenciones encontrado

### Override del certificado de retencion

El template OCA `report_payment_withholding_document` esta roto en Odoo 17:
- `o.reconciled_invoice_ids` no existe en `account.payment`
- `o._get_invoice_payment_amount(inv)` no existe

Este modulo crea un template nuevo (`arba.report_withholding_certificate_document`) y redirige el `ir.actions.report` existente:

```xml
<record id="l10n_ar_report_withholding.action_payment_withholdings" model="ir.actions.report">
    <field name="report_name">arba.report_withholding_certificate</field>
    <field name="print_report_name">
        'Certificado Retención - %s' % (object.withholding_number or object.name)
    </field>
</record>
```

Estructura del certificado:
```
┌──────────────────────────────────────┐
│    CERTIFICADO DE RETENCION          │
│    [IIBB Buenos Aires / Ganancias]   │
├──────────────────────────────────────┤
│ AGENTE DE RETENCION                  │
│ Razon Social - CUIT - Cond IVA       │
│ Domicilio - Nro IIBB (si IIBB)      │
│ Inicio Actividades                   │
├──────────────────────────────────────┤
│ SUJETO RETENIDO                      │
│ Razon Social - CUIT - Cond IVA       │
│ Domicilio                            │
├──────────────────────────────────────┤
│ DATOS DE LA RETENCION                │
│ Nro Certificado - Fecha - Impuesto   │
│ Base Imponible - Alicuota - Importe  │
│ Regimen (IIBB: Gral / Gan: codigo)  │
├──────────────────────────────────────┤
│ COMPROBANTES ASOCIADOS               │
│ Fecha | Comprobante | Monto | Saldo  │
├──────────────────────────────────────┤
│         Firma y Sello Agente         │
└──────────────────────────────────────┘
```

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
   ZIP → guardar_y_procesar_zip()
     → _procesar_zip_comprimido()
       → TRUNCATE arba_padron (1 vez)
       → Per*.txt → _procesar_txt_en_perc()   → COPY masivo
       → Ret*.txt → _procesar_txt_en_ret()    → COPY masivo

   "Procesar ZIP" → actualiza_imp_pos_fiscal()
     → PERCEPCIONES:
       → Crea impuestos venta por tasa (grupo "Perc IIBB ARBA")
       → _posiciones_fiscales() → crea posiciones fiscales
       → _posicion_impositiva_contacto() → asigna pos fiscal a partners BA
     → RETENCIONES:
       → _actualizar_retenciones_partners()
         → arba.padron WHERE tipo LIKE 'R%'
         → CREATE/UPDATE res.partner.perception (tax=Ret IIBB ARBA, percent=tasa)

2. PERCEPCIONES EN VENTAS (automatico):
   Factura de venta → posicion fiscal del partner
     → mapeo de impuestos agrega "IIBB ARBA X.XX%"
     → linea de percepcion en la factura

3. RETENCIONES EN COMPRAS (motor OCA):
   Payment Group confirm → compute_withholdings()
     → tracking en chatter (override de este modulo)
     → account.tax(Ret IIBB ARBA).get_withholding_vals()
       → get_partner_alicuot() → lee perception_ids → percent/100
       → base_amount * alicuota = importe retencion
     → create_payment_withholdings() → crea account.payment automatico

4. CERTIFICADO DE RETENCION:
   account.payment → btn_print_withholding()
     → action_payment_withholdings (override → arba.report_withholding_certificate)
       → helpers: get_withholding_alicuota(), get_withholding_invoices()
       → PDF con datos legales completos

5. EXPORT TXT PERCEPCIONES (Actividad 7):
   arba.exportperc → action_generate_csv()
     → account.move.line WHERE cuenta = "Percepcion IIBB ARBA aplicada"
     → 81 chars/linea formato RN 22/2025
     → ir.attachment → download link

6. EXPORT TXT RETENCIONES (Actividad 6):
   arba.exportret → action_generate_txt()
     → account.payment WHERE tax_withholding_id = Ret IIBB ARBA
     → 67 chars/linea formato A-122R
     → ir.attachment → download link
```

### Verificacion / Testing

1. **Instalar modulo**: Upgrade del modulo arba, verificar que crea tax group + tax + secuencia
2. **Configurar tax**: Asignar cuenta contable al impuesto Ret IIBB ARBA
3. **Configurar diario**: Crear diario "Retenciones IIBB ARBA" tipo Efectivo con metodo Withholding
4. **Habilitar retenciones automaticas**: Ajustes > Compañias > checkbox
5. **Importar padron**: Subir ZIP con Per y Ret → verificar `arba.padron` tiene registros
6. **Procesar ZIP**: Click boton → verificar impuestos, posiciones fiscales, perception_ids
7. **Percepcion en venta**: Emitir factura a cliente BA → verificar linea de percepcion
8. **Retencion en compra**: Crear Payment Group → confirmar → verificar retencion automatica
9. **Tracking**: Verificar log paso a paso en chatter del Payment Group
10. **Certificado**: Imprimir retencion → verificar PDF con datos legales
11. **Export percepciones**: Generar TXT → verificar formato 81 chars
12. **Export retenciones**: Generar TXT → verificar formato 67 chars

### Fuentes
- ARBA nuevo diseno registro (vigente): https://www.arba.gov.ar/archivos/Publicaciones/Nuevo%20Disenio%20de%20Registro%20ARWeb%20Prod..pdf
- ARBA diseno viejo: https://www.arba.gov.ar/archivos/Publicaciones/dise%C3%B1o_de_registro_iibbddjjweb.pdf
- ARBA RN 22/2025: https://www.arba.gov.ar/archivos/Tramites/RN%2022-2025.pdf
- Motor OCA retenciones: https://github.com/OCA/l10n-argentina

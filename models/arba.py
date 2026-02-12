from odoo import models, fields, api
from odoo.exceptions import ValidationError, UserError
from datetime import datetime, timedelta

import base64
import zipfile
import os
import logging
import shutil
import io
import csv
from markupsafe import Markup

class PadronArba(models.Model):
    _name = 'arba.padron'
    _description = 'Contiene la base de datos del padron de Arba'
    #_table_args = (('INDEX', 'cuit'),)


    
    tipo = fields.Char(string="Tipo")
    name = fields.Char(string="Periodo")
    inicio = fields.Date(string="Fecha Inicio")
    fin = fields.Date(string="Fecha Final")
    cuit = fields.Char(string="Cuit", index=True)
    par_uno = fields.Char(string="Uno")
    par_dos = fields.Char(string="Dos")
    par_tres = fields.Char(string="Tres")
    tasa = fields.Float(string="Tasa")
    codigo = fields.Char(string="Codigo")
    id_pos_imp = fields.Integer(string="Posición Impositiva")




_logger = logging.getLogger(__name__)

class ArchivoComprimido(models.Model):
    _name = 'arba.archivo_comprimido'
    _inherit = ['mail.thread'] # Habilito el campo de los mensajes.
    _description = 'Archivo Comprimido'

    name = fields.Char(string="Nombre")
    archivo = fields.Binary(string="Archivo Zip", required=True)


    @api.model
    def create(self, vals):
        rec = super().create(vals)
        rec.guardar_y_procesar_zip()
        return rec

    def convertir_fecha(self, texto):
        try:
            return datetime.strptime(texto, "%d%m%Y").strftime("%Y-%m-%d")
        except:
            return ""
  
    def guardar_y_procesar_zip(self):
        for rec in self:
            if not rec.archivo:
                continue

        destino = "/tmp/arba"
        try:
            # Limpiar /tmp/arba completamente
            if os.path.exists(destino):
                for entry in os.listdir(destino):
                    full_path = os.path.join(destino, entry)
                    if os.path.isdir(full_path):
                        shutil.rmtree(full_path)
                    else:
                        os.remove(full_path)
            else:
                os.makedirs(destino)

            os.chmod(destino, 0o777)

            # Guardar el archivo dentro de /tmp/arba
            nombre_archivo = (rec.name or 'archivo.zip').replace(' ', '_')
            ruta = os.path.join(destino, nombre_archivo)

            with open(ruta, 'wb') as f:
                f.write(base64.b64decode(rec.archivo))

            rec._procesar_zip_comprimido(ruta)

        except Exception as e:
            _logger.error(f"❌ Error preparando entorno ZIP: {e}")
            rec.message_post(body=f"❌ Error al preparar entorno ZIP: {e}")

    def _procesar_zip_comprimido(self, ruta_zip):
        """
        Descomprime un archivo ZIP dentro del directorio /tmp/arba,
        registra cuántas líneas tiene cada archivo descomprimido y lo muestra en el chatter.
        """
        destino = "/tmp/arba"

        try:
            os.makedirs(destino, exist_ok=True)
            os.chmod(destino, 0o777)  # Permisos amplios por si hay restricciones
        except Exception as e:
            _logger.error(f"❌ No se pudo crear el directorio {destino}: {e}")
            self.message_post(body=f"❌ Error creando directorio de extracción: {e}")
            return []

        archivos_extraidos = []
        resumen_lineas = []

        try:
            with zipfile.ZipFile(ruta_zip, 'r') as zip_ref:
                zip_ref.extractall(destino)
                archivos_extraidos = [os.path.join(destino, name) for name in zip_ref.namelist()]

            for archivo in archivos_extraidos:
                try:
                    with open(archivo, 'r', encoding='latin1') as f:
                        total_lineas = sum(1 for _ in f)
                    resumen_lineas.append(f"📄 {os.path.basename(archivo)}: {total_lineas} líneas")
                except Exception as e:
                    resumen_lineas.append(f"❌ Error leyendo {archivo}: {e}")

            mensaje = "\n".join(["✅ Archivos extraídos:"] + resumen_lineas)
            self.message_post(body=mensaje)
            _logger.info(mensaje)

            # Por qué: TRUNCATE una sola vez antes de procesar Per y Ret
            # para no borrar retenciones al cargar percepciones o viceversa
            self.env.cr.execute("TRUNCATE TABLE arba_padron RESTART IDENTITY")
            self.message_post(body="Se ejecutó TRUNCATE sobre la tabla `arba_padron`.")
            _logger.info("Se eliminó todo el contenido de arba_padron con TRUNCATE.")

            for archivo in archivos_extraidos:
                nombre = os.path.basename(archivo)
                if 'Per' in nombre:
                    self._procesar_txt_en_perc(archivo)
                elif 'Ret' in nombre:
                    self._procesar_txt_en_ret(archivo)
                                
        except Exception as e:
            error_msg = f"❌ Error al descomprimir archivo ZIP {ruta_zip}: {e}"
            self.message_post(body=error_msg)
            _logger.error(error_msg)

        
        return archivos_extraidos

    def _procesar_txt_en_perc(self, archivo):
        # Por qué: TRUNCATE se movió al caller _procesar_zip_comprimido
        # para ejecutarse una sola vez antes de Per + Ret
        ruta_completa = os.path.join("/tmp/arba", archivo)
        try:
            buffer = io.StringIO()
            validas = 0
            descartadas = 0

            with open(ruta_completa, 'r', encoding='latin1') as f:
                for linea in f:
                    columnas = linea.strip().split(';')
                    if len(columnas) >= 10:
                        # Procesar columnas necesarias
                        columnas[2] = self.convertir_fecha(columnas[2])  # inicio
                        columnas[3] = self.convertir_fecha(columnas[3])  # fin
                        columnas[8] = columnas[8].replace(',', '.')  # tasa
                        buffer.write(';'.join(columnas[:10]) + '\n')
                        validas += 1
                    else:
                        descartadas += 1

            buffer.seek(0)

            self.env.cr.copy_expert(
                sql="""
                COPY arba_padron(tipo, name, inicio, fin, cuit, par_uno, par_dos, par_tres, tasa, codigo)
                FROM STDIN WITH (FORMAT csv, DELIMITER ';', HEADER false, ENCODING 'LATIN1')
                """,
                file=buffer
            )

            mensaje = (
                f"📥 Registros importados con COPY desde {os.path.basename(ruta_completa)}\n"
                f"✔️ Líneas válidas: {validas}\n"
                f"⚠️ Líneas descartadas: {descartadas}"
            )
            self.message_post(body=mensaje)
            _logger.info(mensaje)

        except Exception as e:
            mensaje = f"❌ Error al importar con COPY desde {ruta_completa}: {e}"
            self.message_post(body=mensaje)
            _logger.error(mensaje)


    def _procesar_txt_en_ret(self, archivo):
        """Importa registros de retenciones del padrón ARBA.
        Por qué: misma lógica COPY que percepciones, sin TRUNCATE
        (ya se ejecutó en el caller). Los registros tienen tipo que empieza con 'R'.
        """
        ruta_completa = os.path.join("/tmp/arba", archivo)
        try:
            buffer = io.StringIO()
            validas = 0
            descartadas = 0

            with open(ruta_completa, 'r', encoding='latin1') as f:
                for linea in f:
                    columnas = linea.strip().split(';')
                    if len(columnas) >= 10:
                        columnas[2] = self.convertir_fecha(columnas[2])  # inicio
                        columnas[3] = self.convertir_fecha(columnas[3])  # fin
                        columnas[8] = columnas[8].replace(',', '.')      # tasa
                        buffer.write(';'.join(columnas[:10]) + '\n')
                        validas += 1
                    else:
                        descartadas += 1

            buffer.seek(0)

            self.env.cr.copy_expert(
                sql="""
                COPY arba_padron(tipo, name, inicio, fin, cuit, par_uno, par_dos, par_tres, tasa, codigo)
                FROM STDIN WITH (FORMAT csv, DELIMITER ';', HEADER false, ENCODING 'LATIN1')
                """,
                file=buffer
            )

            mensaje = (
                f"Registros RET importados desde {os.path.basename(ruta_completa)}\n"
                f"Líneas válidas: {validas}\n"
                f"Líneas descartadas: {descartadas}"
            )
            self.message_post(body=mensaje)
            _logger.info(mensaje)

        except Exception as e:
            mensaje = f"Error al importar RET desde {ruta_completa}: {e}"
            self.message_post(body=mensaje)
            _logger.error(mensaje)

    def actualiza_imp_pos_fiscal(self):
        self.env.cr.execute("SELECT DISTINCT tasa FROM arba_padron WHERE tasa IS NOT NULL")
        tasas = [row[0] for row in self.env.cr.fetchall()]
        mensaje_tasas = "📊 Tasas únicas importadas:\n" + "\n".join(f"• {t}" for t in tasas)
        self.message_post(body=mensaje_tasas)
        _logger.info(mensaje_tasas)
        # Buscar el grupo de impuestos deseado
        grupo_perc = self.env['account.tax.group'].search([('name', '=', 'Perc IIBB ARBA')], limit=1)
        if not grupo_perc:
            self.message_post(body="❌ No se encontró el grupo de impuestos 'Perc IIBB ARBA'.")
            return
        nuevos = []
        for t in tasas:
            try:
                valor = float(t)
                nombre = f"IIBB ARBA {valor:.2f}%"
                # Verificar si ya existe un impuesto con esa tasa en ese grupo
                existente = self.env['account.tax'].search([
                    ('tax_group_id', '=', grupo_perc.id),
                    ('amount', '=', valor)
                ], limit=1)
                if not existente:
                    # Buscar cualquier impuesto base del grupo para usar como plantilla
                    base = self.env['account.tax'].search([
                        ('tax_group_id', '=', grupo_perc.id)
                    ], limit=1)
                    if base:
                        nuevo = base.copy(default={
                            'amount': valor,
                            'name': nombre
                        })
                        nuevos.append(nuevo.name)
            except Exception as e:
                _logger.warning(f"⚠️ Error procesando tasa {t}: {e}")
        
        # Informar
        if nuevos:
           mensaje = "🆕 Impuestos creados:\n" + "\n".join(f"• {n}" for n in nuevos)
        else:
           mensaje = "ℹ️ Todas las tasas ya estaban creadas dentro del grupo 'Perc IIBB ARBA'."
        self.message_post(body=mensaje)
        _logger.info(mensaje)
        self._posiciones_fiscales()
        # Por qué: después de actualizar percepciones, alimentamos
        # res.partner.perception con tasas de retención del padrón
        self._actualizar_retenciones_partners()

    def _posiciones_fiscales(self):
        """Crea las posiciones fiscales nuevas, si no están creadas teniendo en cuenta la tasa del padrón de percepciones."""
        # Buscar el grupo de impuestos "Perc IIBB ARBA"
        grupo_perc = self.env['account.tax.group'].search([('name', '=', 'Perc IIBB ARBA')], limit=1)
        # Obtener todos los impuestos que pertenecen a ese grupo tipo ventas
        impuesto_ids = self.env['account.tax'].search([('tax_group_id', '=', grupo_perc.id),('type_tax_use', '=', 'sale')]).ids
        # Obtener los objetos de los impuestos que pertenecen a este grupo
        res_imp_ids =self.env['account.tax'].browse(impuesto_ids)
        # Buscar líneas de mapeo fiscal que ya usan esos impuestos como destino
        lineas_mapeo = self.env['account.fiscal.position.tax'].search([
            ('tax_dest_id', 'in', impuesto_ids)
        ])
        # Extraer los IDs de impuestos ya utilizados
        impuestos_usados = lineas_mapeo.mapped('tax_dest_id.id')
        # Extraer posiciones fiscales usadas
        #posiciones_usadas_ids = lineas_mapeo.mapped('position_id.id')[0] if lineas_mapeo else None
        #posicion_base = self.env['account.fiscal.position'].browse(posiciones_usadas_ids)
        # Corrección.
        posiciones_usadas_ids = lineas_mapeo.mapped('position_id.id')
        if not posiciones_usadas_ids:
            self.message_post(body="❌ No se encontraron posiciones fiscales base para copiar.")
            return
        posicion_base = self.env['account.fiscal.position'].browse(posiciones_usadas_ids[0])
        if not posicion_base or len(posicion_base) != 1:
            raise ValidationError("Se esperaba una sola posición fiscal base para copiar, pero se encontró más de una.")

        # Calcular los que todavía no están usados
        impuestos_no_usados = list(set(impuesto_ids) - set(impuestos_usados))
        # Obtener los objetos de impuestos no usados
        impuestos_faltantes = self.env['account.tax'].browse(impuestos_no_usados)
        for impuesto_faltante in impuestos_faltantes:
            id_nueva_posicion = posicion_base.copy({'name': f"Ventas Iva IIBB ARBA {impuesto_faltante.amount}"})
            self.env.cr.commit()
            lineas_mapeadas_ids = self.env['account.fiscal.position.tax'].search([('position_id', '=', id_nueva_posicion.id)]).ids
            res_line_map_ids = self.env['account.fiscal.position.tax'].browse(lineas_mapeadas_ids)
            for res_line_map_id in res_line_map_ids:
                if res_line_map_id.tax_dest_id.id  == impuestos_usados[0]:
                    res_line_map_id.write({'tax_dest_id': impuesto_faltante.id})
                    self.env.cr.commit()
        self._posicion_impositiva_contacto()
            #raise UserError(f"id nueva posición {id_nueva_posicion} \n Lineas a modificar {lineas_mapeadas_ids} \n El impuesto usado es :{impuestos_usados[0]} \n Esto no se que es {res_line_map_id.tax_dest_id}")
        if lineas_mapeo:
            msje = f"Impuesto en Pos Fiscal{impuestos_usados}.\n Imp que no tienen Pos Fiscal {impuestos_no_usados}.\n Posiciones fiscales usadas {posiciones_usadas_ids}"
        else:
            msje = f"No encontré las lineas de mapeo."
        self.message_post(body=msje)

    def _posicion_impositiva_contacto(self):
        """Asignamos la posiciones fiscales a los contactos que corresponden"""
        obj_contactos=self.env['res.partner'].search([('state_id','=',554)])
        for obj_contacto in obj_contactos:
            # Busco la tasa de perc para este cuit y busco la posición fiscal y la escribo en
            
            # el campo posición fiscal del contacto.
            var_cuit =  (obj_contacto.vat or '').replace('-', '')
            tasa_perc = self.env['arba.padron'].search([('cuit','=',var_cuit)], limit=1) #Busco por nro de cuit la tasa asignada en el padrón
            id_imp = self.env['account.tax'].search([('amount', '=', tasa_perc.tasa),('type_tax_use', '=', 'sale')], limit=1) # Busco el impuesto en función de la tasa
            line_perc = self.env['account.fiscal.position.tax'].search([('tax_dest_id', '=', id_imp.id)]) # Busco la posición fiscal que surge de la retención.
            if line_perc and line_perc.position_id:
                obj_contacto.write({'property_account_position_id': line_perc.position_id.id})
                obj_contacto.message_post(body=f"📌 Se actualizó la posición impositiva a: {line_perc.position_id.name}")
            else:
                obj_contacto.message_post(body="⚠️ No se pudo asignar posición impositiva. No se encontró una posición válida.")
            tasa = obj_contacto.name + str(var_cuit) + "Tasa:  " +  str(tasa_perc) +  str(tasa_perc.tasa) + " Id impuesto: " +  str(id_imp.id) + str(line_perc.position_id.id) +   "\n"

            _logger.info(tasa)
            #raise UserError(f"Listados de ids de contactos de Buenos Aires {contactos_ids}  \n {tasas}")


    def _actualizar_retenciones_partners(self):
        """Alimenta res.partner.perception con tasas de retención del padrón ARBA.
        Por qué: el motor OCA (get_partner_alicuot) lee de perception_ids
        para obtener la alícuota. Si creamos registros ahí con el tax 'Ret IIBB ARBA',
        el cálculo automático de retenciones funciona sin código adicional.
        Patrón: data-driven — solo alimentamos datos, la lógica la ejecuta OCA.
        """
        # Buscar el impuesto de retención IIBB ARBA (type_tax_use=supplier)
        tax_ret = self.env['account.tax'].search([
            ('name', '=', 'Ret IIBB ARBA'),
            ('type_tax_use', '=', 'supplier'),
        ], limit=1)
        if not tax_ret:
            self.message_post(body="No se encontró el impuesto 'Ret IIBB ARBA' (supplier). "
                                   "Verifique que el data XML se cargó correctamente.")
            return

        # Partners de Buenos Aires (state_id=554)
        partners_ba = self.env['res.partner'].search([('state_id', '=', 554)])
        creados = 0
        actualizados = 0

        for partner in partners_ba:
            cuit = (partner.vat or '').replace('-', '')
            if not cuit:
                continue

            # Buscar en padrón registros de retención (tipo empieza con 'R')
            padron_ret = self.env['arba.padron'].search([
                ('cuit', '=', cuit),
                ('tipo', '=like', 'R%'),
            ], limit=1)
            if not padron_ret:
                continue

            tasa = padron_ret.tasa or 0.0

            # Buscar si ya existe un perception para este partner + tax
            perception = self.env['res.partner.perception'].search([
                ('partner_id', '=', partner.id),
                ('tax_id', '=', tax_ret.id),
            ], limit=1)

            if perception:
                # Actualizar si la tasa cambió
                if perception.percent != tasa:
                    perception.write({'percent': tasa})
                    actualizados += 1
            else:
                # Crear nuevo registro
                self.env['res.partner.perception'].create({
                    'partner_id': partner.id,
                    'tax_id': tax_ret.id,
                    'percent': tasa,
                })
                creados += 1

        mensaje = (
            f"Retenciones IIBB ARBA actualizadas en partners:\n"
            f"Creados: {creados} | Actualizados: {actualizados}"
        )
        self.message_post(body=mensaje)
        _logger.info(mensaje)


class TaxExportCsv(models.Model):
    """Modelo que crea los arcivos csv de percepciones"""
    _name = 'arba.exportperc'
    _description = 'Exportar Impuestos'



    periodo_mes = fields.Selection(selection=[('01','Enero'),
                                               ('02','Febrero'),
                                               ('03','Marzo'),
                                               ('04','Abril'),
                                               ('05','Mayo'),
                                               ('06','Junio'),
                                               ('07','Julio'),
                                               ('08','Agosto'),
                                               ('09','Setiembre'),
                                               ('10','Octubre'),
                                               ('11','Noviembre'),
                                               ('12','Diciembre'),],
                                   string="✅ Mes: ",
                                   required=True)

    periodo_anio = fields.Selection(selection=[('2025','2025'),
                                                ('2026','2026'),
                                                ('2027','2027'),
                                                ('2028','2028'),
                                                ('2029','2029'),],
                                    string="✅ Año: ",
                                    required=True)
    name = fields.Char('Nombre del Archivo', required=True)
    file_name = fields.Char('Nombre del archivo CSV')
    attachment_id = fields.Many2one('ir.attachment', 'Archivo CSV', ondelete='set null')
    # Por qué: campo Html computed que genera un <a href> apuntando a
    # /web/content/<attachment_id> que es la URL estándar de descarga en Odoo 17
    download_link = fields.Html('Descargar', compute='_compute_download_link', sanitize=False)
    state = fields.Selection([
        ('draft', 'Borrador'),
        ('done', 'Hecho'),
    ], default='draft')

    @api.depends('attachment_id', 'file_name')
    def _compute_download_link(self):
        for rec in self:
            if rec.attachment_id and rec.file_name:
                url = '/web/content/%d?download=true' % rec.attachment_id.id
                rec.download_link = Markup('<a href="%s">📥 %s</a>') % (url, rec.file_name)
            else:
                rec.download_link = False

    def action_generate_csv(self):

        if self.state == 'done':
            raise ValidationError(f"Este Archivo ya fué procesado")
        # Convertir a fechas reales (asumiendo mes y año en formato 'MM' y 'YYYY')
        start_date = datetime.strptime(f"{self.periodo_anio}-{self.periodo_mes}-01", "%Y-%m-%d").date()

        # Obtener fin del mes
        if self.periodo_mes == '12':
            end_date = datetime.strptime(f"{int(self.periodo_anio)+1}-01-01", "%Y-%m-%d").date()
        else:
            end_date = datetime.strptime(f"{self.periodo_anio}-{int(self.periodo_mes)+1:02d}-01", "%Y-%m-%d").date()

        # Por qué: se filtra por move_type 'out_invoice' y 'out_refund' para
        # tomar solo comprobantes de venta, excluyendo facturas de proveedor
        res_imp_ids = self.env['account.move.line'].search([
            ('account_id.name', 'ilike', 'Percepción IIBB ARBA aplicada'),
            ('move_id.move_type', 'in', ['out_invoice', 'out_refund']),
            ('invoice_date', '>=', start_date),
            ('invoice_date', '<', end_date),
            ('parent_state', '=', 'posted')
        ])
            

        # Por qué: formato ARBA posición fija 81 chars (RN 22/2025, vigente desde dic 2025)
        # Campos: CUIT(13) + FechaPerc(10) + TipoComp(1) + Letra(1) + Suc(5) + Emision(8)
        #         + MontoImp(14) + Alicuota(5) + ImpPerc(13) + FechaEmision(10) + TipoOp(1)
        registros = []
        for registro in res_imp_ids:
            # Campo 1: CUIT (13 chars) - formato XX-XXXXXXXX-X
            partner = registro.partner_id
            if not partner or not partner.vat:
                raise UserError(
                    f"El partner '{partner.name or 'Sin partner'}' del comprobante "
                    f"'{registro.move_name}' no tiene CUIT cargado."
                )
            cuit = self._formatear_cuit_arba(partner.vat)

            # Parsear move_name: "FA-A 0001-00000020"
            partes = registro.move_name.split() if registro.move_name else []
            if len(partes) < 2 or '-' not in partes[0]:
                raise UserError(
                    f"El comprobante '{registro.move_name}' (ID: {registro.move_id.id}, "
                    f"Partner: {partner.name or 'Sin partner'}) "
                    f"no tiene el formato esperado 'TIPO-LETRA SUCURSAL-NUMERO'."
                )
            tipo_odoo = partes[0]   # ej: "FA-A"
            nro_comp = partes[1]    # ej: "0001-00000020"

            # Campo 3: Tipo comprobante (1 char) - F, C, D
            tipo_arba = self._mapear_tipo_comprobante_arba(tipo_odoo)
            # Campo 4: Letra comprobante (1 char) - A, B, C
            letra = tipo_odoo.split('-')[1] if '-' in tipo_odoo else ' '

            # Campos 5 y 6: Sucursal (5 chars) y Emisión (8 chars)
            partes_nro = nro_comp.split('-')
            if len(partes_nro) < 2:
                raise UserError(
                    f"El número de comprobante '{nro_comp}' del documento '{registro.move_name}' "
                    f"no tiene el formato esperado 'SUCURSAL-NUMERO'."
                )
            sucursal = partes_nro[0].zfill(5)
            emision = partes_nro[1].zfill(8)

            # Campo 2: Fecha percepción (10 chars) dd/mm/aaaa
            fecha_perc = registro.invoice_date.strftime("%d/%m/%Y")

            # Campo 7: Monto imponible (14 chars) - 11 enteros + . + 2 dec
            monto_imp = self._formatear_importe_arba(registro.tax_base_amount, 11)

            # Campo 8: Alícuota (5 chars) - 2 enteros + . + 2 dec
            # Por qué: se obtiene la alícuota del impuesto asociado a la línea
            tax = registro.tax_line_id
            alicuota = abs(tax.amount) if tax else 0.0
            alicuota_str = self._formatear_importe_arba(alicuota, 2)

            # Campo 9: Importe percepción (13 chars) - 10 enteros + . + 2 dec
            imp_perc = self._formatear_importe_arba(abs(registro.balance), 10)

            # Campo 10: Fecha emisión (10 chars) dd/mm/aaaa
            fecha_emi = registro.invoice_date.strftime("%d/%m/%Y")

            # Campo 11: Tipo operación (1 char) - A=Alta
            tipo_op = 'A'

            # Concatenar posición fija (81 chars)
            linea = (
                cuit +          # 13
                fecha_perc +    # 10
                tipo_arba +     # 1
                letra +         # 1
                sucursal +      # 5
                emision +       # 8
                monto_imp +     # 14
                alicuota_str +  # 5
                imp_perc +      # 13
                fecha_emi +     # 10
                tipo_op         # 1
            )
            registros.append(linea)

        texto = "\n".join(registros)
        nombre = f"percepciones_{self.periodo_mes}_{self.periodo_anio}.txt"
        # Por qué: ir.attachment es el mecanismo estándar de Odoo para archivos descargables
        # /web/content/<attachment_id> es la URL nativa que siempre funciona
        attachment = self.env['ir.attachment'].create({
            'name': nombre,
            'type': 'binary',
            'datas': base64.b64encode(texto.encode("utf-8")).decode("utf-8"),
            'res_model': self._name,
            'res_id': self.id,
            'mimetype': 'text/plain',
        })
        self.write({
            'file_name': nombre,
            'attachment_id': attachment.id,
            'state': 'done',
        })

    def _formatear_importe_arba(self, importe, enteros):
        """Formatea importe a posición fija ARBA: enteros + '.' + 2 decimales.
        Por qué: ARBA exige ceros a la izquierda y punto como separador decimal.
        Ej: _formatear_importe_arba(45.0, 10) → '0000000045.00' (13 chars)
        """
        valor = abs(float(importe))
        parte_entera = str(int(valor)).zfill(enteros)
        parte_decimal = "{:.2f}".format(valor).split(".")[1]
        return parte_entera + "." + parte_decimal

    def _formatear_cuit_arba(self, cuit):
        """Formatea CUIT a formato ARBA: XX-XXXXXXXX-X (13 chars).
        Por qué: ARBA exige guiones y exactamente 13 caracteres.
        """
        cuit = cuit.replace('-', '').strip()
        if len(cuit) != 11:
            raise UserError(f"El CUIT '{cuit}' no tiene 11 dígitos.")
        return f"{cuit[:2]}-{cuit[2:10]}-{cuit[10]}"

    def _mapear_tipo_comprobante_arba(self, tipo_odoo):
        """Mapea prefijo Odoo a tipo comprobante ARBA (1 char).
        Por qué: ARBA usa F=Factura, C=Nota Crédito, D=Nota Débito.
        """
        # tipo_odoo viene como "FA-A", "NC-B", "ND-A", etc.
        prefijo = tipo_odoo.split('-')[0]
        # Por qué: FCE/NCE/NDE son Facturas/NC/ND de Crédito Electrónica,
        # para ARBA se mapean igual que las convencionales
        mapa = {
            'FA': 'F',
            'FCE': 'F',
            'NC': 'C',
            'NCE': 'C',
            'ND': 'D',
            'NDE': 'D',
        }
        resultado = mapa.get(prefijo)
        if not resultado:
            raise UserError(
                f"Tipo de comprobante '{tipo_odoo}' no tiene mapeo ARBA. "
                f"Esperados: FA-x, NC-x, ND-x."
            )
        return resultado

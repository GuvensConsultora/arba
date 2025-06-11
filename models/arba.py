from odoo import models, fields, api
from odoo.exceptions import UserError
from datetime import datetime, timedelta

import base64
import zipfile
import os
import logging
import shutil
import io
import csv

class PadronArba(models.Model):
    _name = 'arba.padron'
    _description = 'Contiene la base de datos del padron de Arba'
    _table_args = (('INDEX', 'btree (cuit)', 'idx_cuit'),)


    
    tipo = fields.Char(string="Tipo")
    name = fields.Char(string="Periodo")
    inicio = fields.Date(string="Fecha Inicio")
    fin = fields.Date(string="Fecha Final")
    cuit = fields.Char(string="Cuit")
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

            # Buscar archivo que contenga 'Per' y ejecutar _procesar_txt_en_perc
            for archivo in archivos_extraidos:
                if 'Per' in os.path.basename(archivo):
                    self._procesar_txt_en_perc(archivo)
                                
        except Exception as e:
            error_msg = f"❌ Error al descomprimir archivo ZIP {ruta_zip}: {e}"
            self.message_post(body=error_msg)
            _logger.error(error_msg)

        
        return archivos_extraidos

    def _procesar_txt_en_perc(self, archivo):
        self.env.cr.execute("TRUNCATE TABLE arba_padron RESTART IDENTITY")
        self.message_post(body="🧹 Se ejecutó TRUNCATE sobre la tabla `arba_padron`.")
        _logger.info("🧹 Se eliminó todo el contenido de arba_padron con TRUNCATE.")
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

    def _posiciones_fiscales(self):
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
        posiciones_usadas_ids = lineas_mapeo.mapped('position_id.id')[0] if lineas_mapeo else None
        posicion_base = self.env['account.fiscal.position'].browse(posiciones_usadas_ids)
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
        contactos_ids=self.env['res.partner'].search([('state_id','=',554)])
        obj_contactos=self.env['res.partner'].browse(contactos_ids.ids)
        for obj_contacto in obj_contactos:
            # Busco la tasa de perc para este cuit y busco la posición fiscal y la escribo en
            # el campo posición fiscal del contacto.
            var_cuit =  (obj_contacto.vat or '').replace('-', '')
            tasa_perc = self.env['arba.padron'].search([('cuit','=',var_cuit)], limit=1)
            id_imp = self.env['account.tax'].search([('amount', '=', tasa_perc.tasa),('type_tax_use', '=', 'sale')], limit=1)
            line_perc = self.env['account.fiscal.position.tax'].search([('tax_dest_id', '=', id_imp.id)])
            obj_contacto.write({'property_account_position_id':line_perc.position_id.id})
            tasa = obj_contacto.name + str(var_cuit) + "Tasa:  " +  str(tasa_perc) +  str(tasa_perc.tasa) + " Id impuesto: " +  str(id_imp.id) + str(line_perc.position_id.id) +   "\n"
            self.env.cr.commit()

            _logger.info(tasa)
            #raise UserError(f"Listados de ids de conctactos de Buenos Aires {contactos_ids}  \n {tasas}")


class TaxExportCsv(models.Model):
    _name = 'arba.exportperc'
    _description = 'Exportar Impuestos'

    name = fields.Char('Nombre del Archivo', required=True)
    csv_file = fields.Binary('Archivo CSV', readonly=True)
    file_name = fields.Char('Nombre del archivo CSV', readonly=True)

    def action_generate_csv(self):
        pass

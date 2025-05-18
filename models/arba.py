from odoo import models, fields, api
from odoo.exceptions import UserError
from datetime import datetime
import base64
import zipfile
import tempfile
import os
import subprocess

class PadronArba(models.Model):
    _name = 'arba.padron'
    _description = 'Contiene la base de datos del padron de Arba'

    name = fields.Char(string="Periodo")
    inicio = fields.Date(string="Fecha Inicio")
    fin = fields.Date(string="Fecha Final")
    cuit = fields.Char(string="Cuit")
    par_uno = fields.Char(string="Uno")
    par_dos = fields.Char(string="Dos")
    par_tres = fields.Char(string="Tres")
    tasa = fields.Float(string="Tasa")
    codigo = fields.Char(string="Codigo")



class ArchivoComprimido(models.Model):
    _name = 'arba.archivo_comprimido'
    _inherit = ['mail.thread']
    _description = 'Archivo Comprimido'

    name = fields.Char(string="Nombre")
    archivo_zip = fields.Binary(string="Archivo Zip", required=True)
    archivo_zip_filename = fields.Char(string="Nombre del Archivo")
    


    @api.model
    def create(self, vals):
        record = super().create(vals)
        record._procesar_zip_en_directorio()
        return record


    def _procesar_zip_en_directorio(self):
        for rec in self:
            if not rec.archivo_zip:
                raise UserError("El archivo ZIP está vacío.")

            # Crear un directorio único basado en el ID del registro
            #base_dir = f"/tmp/arba_padron/{rec.id}"
            # Definir y Crear un directorio solamente si es que no existe.
            base_dir = f"/tmp/arba_padron/"
            if not os.path.exists(base_dir):
                os.makedirs(base_dir)
            # Limpiar el directorio completo
            comando = f'rm -f {base_dir}*'
            subprocess.run(comando, shell=True, check=True)


            zip_path = os.path.join(base_dir, rec.archivo_zip_filename or 'archivo.zip')
            with open(zip_path, 'wb') as f:
                f.write(base64.b64decode(rec.archivo_zip))

            # Verificar ZIP y descomprimir
            if not zipfile.is_zipfile(zip_path):
                raise UserError("El archivo subido no es un ZIP válido.")

            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(base_dir)
                archivos = zip_ref.namelist()
                # Eliminar el archivo ZIP después de su procesamiento
                os.remove(zip_path)

                if not archivos:
                    raise UserError("El ZIP no contiene archivos.")

                for name in archivos:
                    ruta = os.path.join(base_dir, name)
                    if 'Per' in name:
                        if os.path.isfile(ruta):
                            #rec._procesar_txt_a_padron_perc(ruta)
                            self._log_chatter(f"Archivos zip descomprimido exitosamente. {archivos}")

        

    def _log_chatter(self, mensaje):
        self.message_post(body=mensaje)


    def _procesar_txt_a_padron_perc(self, path):
        self._log_chatter(f"📂 Iniciando procesamiento del archivo: {os.path.basename(path)}")
        if not os.path.exists(path):
            raise UserError(f"No se encontró el archivo: {path}")

        # Contar líneas no vacías
        with open(path, 'r', encoding='latin1') as contar:
            total_lineas = sum(1 for linea in contar if linea.strip())
            self._log_chatter(f"📄 El archivo contiene {total_lineas} líneas para procesar.")

        batch_data = []
        total_insertados = 0
        fields = ['cuit', 'par_uno', 'par_dos', 'par_tres', 'tasa', 'codigo', 'inicio', 'fin', 'name']

        try:
            with open(path, 'r', encoding='latin1') as f:
                for i, linea in enumerate(f, start=1):
                    cols = linea.strip().split(';')
                    if len(cols) < 10:
                        self._log_chatter(f"⚠️ Línea {i} ignorada: menos de 10 columnas.")
                        continue

                    try:
                        tasa_limpia = float(cols[8].replace(',', '.'))
                        registro = [
                            cols[4].strip(),
                            cols[5].strip(),
                            cols[6].strip(),
                            cols[7].strip(),
                            tasa_limpia,
                            str(cols[9]).strip(),
                            datetime.strptime(cols[2].strip(), '%d%m%Y').date().isoformat(),
                            datetime.strptime(cols[3].strip(), '%d%m%Y').date().isoformat(),
                            cols[1].strip(),
                        ]
                        batch_data.append(registro)
                    except Exception as e:
                        self._log_chatter(f"⚠️ Error en línea {i}: {str(e)} - {cols}")
                        continue

                    # Cargar cada 1000 registros
                    if len(batch_data) >= 1000:
                        self.env['arba.padron'].load(fields, batch_data)
                        total_insertados += len(batch_data)
                        batch_data = []

                    # Commit y log cada 100.000 registros
                    if total_insertados and total_insertados % 100000 == 0:
                        self.env.cr.commit()
                        self._log_chatter(f"✅ {total_insertados} registros insertados hasta ahora...")


            # Último lote
            if batch_data:
                self.env['arba.padron'].load(fields, batch_data)
                total_insertados += len(batch_data)
                self.env.cr.commit()
                self._log_chatter(f"✅ Último lote insertado: {len(batch_data)} registros.")

            self._log_chatter(f"🏁 Procesamiento finalizado. Total líneas leídas: {i}, total insertados: {total_insertados}")

        except Exception as e:
            self.env.cr.rollback()
            self._log_chatter(f"❌ Error crítico: {str(e)}")
            raise UserError(f"Ocurrió un error crítico durante la carga: {str(e)}")



    def action_procesar_zip(self):
        for rec in self:
            rec._procesar_txt_a_padron_perc()



    def action_eliminar_percepciones(self):
        modelo = self.env['arba.padron']
        lote = 20000
        total = 0

        while True:
            registros = modelo.search([], limit=lote)
            if not registros:
                break
            total += len(registros)
            registros.unlink()
            self.env.cr.commit()  # liberar memoria entre lotes

        self._log_chatter(f"🗑️ Se eliminaron {total} registros del modelo 'arba.padron'.")

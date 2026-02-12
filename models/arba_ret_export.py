from odoo import models, fields, api
from odoo.exceptions import ValidationError, UserError
from datetime import datetime
from markupsafe import Markup

import base64
import logging

_logger = logging.getLogger(__name__)


class TaxExportRet(models.Model):
    """Exporta TXT de retenciones IIBB ARBA formato A-122R (67 chars/línea).
    Por qué: ARBA requiere archivo TXT con formato posición fija para
    la presentación de retenciones practicadas (Actividad 6).
    Patrón: mismo patrón que arba.exportperc pero con formato distinto.
    """
    _name = 'arba.exportret'
    _description = 'Exportar TXT Retenciones IIBB ARBA'

    periodo_mes = fields.Selection(
        selection=[
            ('01', 'Enero'), ('02', 'Febrero'), ('03', 'Marzo'),
            ('04', 'Abril'), ('05', 'Mayo'), ('06', 'Junio'),
            ('07', 'Julio'), ('08', 'Agosto'), ('09', 'Setiembre'),
            ('10', 'Octubre'), ('11', 'Noviembre'), ('12', 'Diciembre'),
        ],
        string="Mes",
        required=True,
    )
    periodo_anio = fields.Selection(
        selection=[
            ('2025', '2025'), ('2026', '2026'), ('2027', '2027'),
            ('2028', '2028'), ('2029', '2029'),
        ],
        string="Año",
        required=True,
    )
    name = fields.Char('Nombre', required=True)
    file_name = fields.Char('Nombre del archivo TXT')
    attachment_id = fields.Many2one('ir.attachment', 'Archivo TXT', ondelete='set null')
    # Por qué: campo Html computed que genera <a href> con URL estándar /web/content/
    download_link = fields.Html(
        'Descargar', compute='_compute_download_link', sanitize=False,
    )
    state = fields.Selection([
        ('draft', 'Borrador'),
        ('done', 'Hecho'),
    ], default='draft')

    @api.depends('attachment_id', 'file_name')
    def _compute_download_link(self):
        for rec in self:
            if rec.attachment_id and rec.file_name:
                url = '/web/content/%d?download=true' % rec.attachment_id.id
                rec.download_link = Markup('<a href="%s">%s</a>') % (url, rec.file_name)
            else:
                rec.download_link = False

    def action_generate_txt(self):
        """Genera TXT retenciones formato A-122R (67 chars/línea).
        Formato:
        | # | Campo             | Long | Pos   | Formato          |
        | 1 | Nro Transacción   | 20   | 1-20  | Secuencial zfill |
        | 2 | CUIT Retenido     | 11   | 21-31 | Sin guiones      |
        | 3 | Sucursal          | 5    | 32-36 | zfill(5), >0     |
        | 4 | Fecha Operación   | 10   | 37-46 | dd/mm/aaaa       |
        | 5 | Alícuota          | 5    | 47-51 | 2ent.2dec        |
        | 6 | Base Imponible    | 16   | 52-67 | 13ent.2dec       |
        """
        if self.state == 'done':
            raise ValidationError("Este archivo ya fue procesado.")

        # Rango de fechas del período
        start_date = datetime.strptime(
            f"{self.periodo_anio}-{self.periodo_mes}-01", "%Y-%m-%d"
        ).date()
        if self.periodo_mes == '12':
            end_date = datetime.strptime(
                f"{int(self.periodo_anio)+1}-01-01", "%Y-%m-%d"
            ).date()
        else:
            end_date = datetime.strptime(
                f"{self.periodo_anio}-{int(self.periodo_mes)+1:02d}-01", "%Y-%m-%d"
            ).date()

        # Buscar el impuesto de retención IIBB ARBA
        tax_ret = self.env['account.tax'].search([
            ('name', '=', 'Ret IIBB ARBA'),
            ('type_tax_use', '=', 'supplier'),
        ], limit=1)
        if not tax_ret:
            raise UserError("No se encontró el impuesto 'Ret IIBB ARBA'.")

        # Por qué: los pagos de retención se crean automáticamente por el motor OCA
        # con tax_withholding_id apuntando al impuesto de retención
        payments = self.env['account.payment'].search([
            ('tax_withholding_id', '=', tax_ret.id),
            ('state', '=', 'posted'),
            ('date', '>=', start_date),
            ('date', '<', end_date),
        ])

        if not payments:
            raise UserError(
                f"No se encontraron retenciones IIBB ARBA "
                f"para {self.periodo_mes}/{self.periodo_anio}."
            )

        registros = []
        secuencia = 0

        for payment in payments:
            secuencia += 1
            partner = payment.partner_id

            if not partner or not partner.vat:
                raise UserError(
                    f"El partner '{partner.name or 'Sin partner'}' del pago "
                    f"'{payment.name}' no tiene CUIT cargado."
                )

            # Campo 1: Nro Transacción (20 chars) - secuencial
            nro_transaccion = str(secuencia).zfill(20)

            # Campo 2: CUIT Retenido (11 chars) - sin guiones
            cuit = (partner.vat or '').replace('-', '').strip()
            if len(cuit) != 11:
                raise UserError(
                    f"El CUIT '{partner.vat}' del partner '{partner.name}' "
                    f"no tiene 11 dígitos."
                )

            # Campo 3: Sucursal (5 chars) - al menos 00001
            # Por qué: ARBA exige sucursal > 0, usamos 00001 como default
            sucursal = '00001'

            # Campo 4: Fecha Operación (10 chars) - dd/mm/aaaa
            fecha_op = payment.date.strftime("%d/%m/%Y")

            # Campo 5: Alícuota (5 chars) - 2 enteros + . + 2 decimales
            # Por qué: obtenemos la alícuota de res.partner.perception
            # que es la misma que usó el motor OCA para calcular
            perception = self.env['res.partner.perception'].search([
                ('partner_id', '=', partner.commercial_partner_id.id),
                ('tax_id', '=', tax_ret.id),
            ], limit=1)
            alicuota = perception.percent if perception else 0.0
            alicuota_str = self._formatear_importe(alicuota, 2)

            # Campo 6: Base Imponible (16 chars) - 13 enteros + . + 2 decimales
            base = payment.withholding_base_amount or 0.0
            base_str = self._formatear_importe(abs(base), 13)

            # Concatenar posición fija (67 chars)
            linea = (
                nro_transaccion +   # 20
                cuit +              # 11
                sucursal +          # 5
                fecha_op +          # 10
                alicuota_str +      # 5
                base_str            # 16
            )
            registros.append(linea)

        texto = "\n".join(registros)
        nombre = f"retenciones_{self.periodo_mes}_{self.periodo_anio}.txt"

        # Por qué: ir.attachment es el mecanismo estándar de Odoo para archivos descargables
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

    def _formatear_importe(self, importe, enteros):
        """Formatea importe a posición fija ARBA: enteros + '.' + 2 decimales.
        Por qué: ARBA exige ceros a la izquierda y punto como separador decimal.
        Tip: reutiliza la misma lógica que percepciones.
        Ej: _formatear_importe(45.0, 10) → '0000000045.00'
        """
        valor = abs(float(importe))
        parte_entera = str(int(valor)).zfill(enteros)
        parte_decimal = "{:.2f}".format(valor).split(".")[1]
        return parte_entera + "." + parte_decimal

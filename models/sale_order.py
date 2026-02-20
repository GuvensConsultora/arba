from odoo import models, api


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    @api.depends('product_id', 'company_id', 'order_id.fiscal_position_id', 'order_id.partner_id')
    def _compute_tax_id(self):
        """Override: filtro defensivo multi-company después del mapeo de posición fiscal.
        Por qué: si la posición fiscal del contacto pertenece a otra empresa,
        map_tax() puede devolver taxes de esa empresa → error 'Empresas incompatibles'.
        Patrón: dejamos que el standard compute haga su trabajo y luego filtramos
        los taxes que no pertenecen a la empresa del pedido."""
        super()._compute_tax_id()
        for line in self:
            if line.tax_id and line.company_id:
                # Descartar taxes de otra empresa que hayan llegado por posición fiscal cruzada
                taxes_ok = line.tax_id.filtered(lambda t: t.company_id == line.company_id)
                if taxes_ok != line.tax_id:
                    line.tax_id = taxes_ok

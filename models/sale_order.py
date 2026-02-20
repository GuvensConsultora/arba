from odoo import models, api


class AccountFiscalPosition(models.Model):
    _inherit = 'account.fiscal.position'

    def map_tax(self, taxes):
        """Override: validar empresa de taxes destino en el mapeo fiscal.
        Por qué: el map_tax() estándar no verifica company_id de los taxes destino.
        Si la posición fiscal fue creada para empresa A y se aplica en empresa B,
        los taxes destino (de empresa A) generan error 'Empresas incompatibles'.
        Patrón: si el destino es de otra empresa, mantener el tax original sin mapear."""
        if not self or not taxes:
            # Sin posición fiscal → devolver taxes sin cambios
            # Sin taxes de entrada → llamar a super normalmente
            return taxes if not self else super().map_tax(taxes)

        # Pre-check: si todos los destinos son de la misma empresa que los orígenes, mapeo normal
        source_company_ids = set(taxes.mapped('company_id').ids)
        dest_company_ids = set(self.tax_ids.mapped('tax_dest_id.company_id').ids)
        if not dest_company_ids - source_company_ids:
            # Todos los destinos son compatibles → flujo estándar
            return super().map_tax(taxes)

        # Hay destinos de otra empresa → mapear manualmente con validación por tax
        # Por qué: super().map_tax() pierde los taxes originales al reemplazarlos,
        # y no podemos recuperarlos después. Necesitamos evaluar cada mapeo individual.
        result = self.env['account.tax']
        for tax in taxes:
            correspondance = self.tax_ids.filtered(lambda t: t.tax_src_id == tax)
            if correspondance:
                dest_taxes = correspondance.mapped('tax_dest_id')
                # Solo usar destinos de la misma empresa que el tax origen
                valid = dest_taxes.filtered(
                    lambda t: t.company_id == tax.company_id or not t.company_id
                )
                # Si hay destinos válidos usarlos, sino mantener el tax original
                result |= valid if valid else tax
            else:
                # Sin mapeo → mantener tax original
                result |= tax
        return result


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    def _compute_tax_id(self):
        """Override: filtro defensivo multi-company después del compute estándar.
        Por qué: capa de seguridad adicional — si por alguna vía (automated action,
        onchange, otro módulo) llegan taxes de otra empresa, los descartamos.
        Tip: no re-declaramos @api.depends porque los triggers están en la definición
        del campo en el módulo sale. Re-declarar puede causar doble registro."""
        super()._compute_tax_id()
        for line in self:
            if line.tax_id and line.company_id:
                taxes_ok = line.tax_id.filtered(lambda t: t.company_id == line.company_id)
                if taxes_ok != line.tax_id:
                    line.tax_id = taxes_ok

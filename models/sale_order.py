import logging
from odoo import models, api

_logger = logging.getLogger(__name__)


class AccountFiscalPosition(models.Model):
    _inherit = 'account.fiscal.position'

    def map_tax(self, taxes):
        """Override: validar empresa de taxes destino en el mapeo fiscal.
        Por qué: el map_tax() estándar no verifica company_id de los taxes destino.
        Si la posición fiscal fue creada para empresa A y se aplica en empresa B,
        los taxes destino (de empresa A) generan error 'Empresas incompatibles'.
        Patrón: si el destino es de otra empresa, mantener el tax original sin mapear."""
        if not self or not taxes:
            return taxes if not self else super().map_tax(taxes)

        # Pre-check: si todos los destinos son de la misma empresa que los orígenes, mapeo normal
        source_company_ids = set(taxes.mapped('company_id').ids)
        dest_company_ids = set(self.tax_ids.mapped('tax_dest_id.company_id').ids)
        if not dest_company_ids - source_company_ids:
            return super().map_tax(taxes)

        # Hay destinos de otra empresa → mapear manualmente con validación por tax
        # Por qué: super().map_tax() pierde los taxes originales al reemplazarlos
        result = self.env['account.tax']
        for tax in taxes:
            correspondance = self.tax_ids.filtered(lambda t: t.tax_src_id == tax)
            if correspondance:
                dest_taxes = correspondance.mapped('tax_dest_id')
                valid = dest_taxes.filtered(
                    lambda t: t.company_id == tax.company_id or not t.company_id
                )
                result |= valid if valid else tax
            else:
                result |= tax
        return result


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    # --- Capa 1: interceptar write/create ANTES de _check_company ---
    # Por qué: _check_company se ejecuta dentro de super().write/create.
    # Si una acción automatizada, onchange o cualquier mecanismo pone taxes
    # de otra empresa, _check_company rechaza ANTES de que podamos limpiar.
    # Interceptando los vals ANTES del super, limpiamos los tax_id commands.

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.context.get('_arba_no_reentry'):
            for vals in vals_list:
                self._limpiar_tax_commands(vals)
        return super(SaleOrderLine, self.with_context(_arba_no_reentry=True)).create(vals_list)

    def write(self, vals):
        if 'tax_id' in vals and not self.env.context.get('_arba_no_reentry'):
            vals = dict(vals)  # Copia para no mutar el original
            self._limpiar_tax_commands(vals)
        return super(SaleOrderLine, self.with_context(_arba_no_reentry=True)).write(vals)

    def _limpiar_tax_commands(self, vals):
        """Filtra comandos Many2many de tax_id para descartar taxes de otra empresa.
        Por qué: tax_id llega como lista de comandos [(6,0,[ids])], [(4,id)], etc.
        Debemos limpiar ANTES de que _check_company los valide."""
        if 'tax_id' not in vals:
            return
        # Determinar empresa: del vals, del record, o del contexto
        company_id = vals.get('company_id')
        if not company_id and len(self) == 1:
            company_id = self.company_id.id
        if not company_id:
            # Intentar desde el order_id
            order_id = vals.get('order_id')
            if order_id:
                order = self.env['sale.order'].browse(order_id)
                company_id = order.company_id.id
        if not company_id:
            company_id = self.env.company.id
        if not company_id:
            return

        cleaned = []
        for cmd in (vals['tax_id'] or []):
            if cmd[0] == 6:  # (6, 0, [ids]) → reemplazar todos
                if cmd[2]:
                    taxes = self.env['account.tax'].browse(cmd[2])
                    ok = taxes.filtered(
                        lambda t: t.company_id.id == company_id or not t.company_id
                    )
                    if ok != taxes:
                        _logger.info(
                            "ARBA multi-company: descartados taxes %s (empresa %s)",
                            (taxes - ok).mapped('name'), company_id
                        )
                    cleaned.append((6, 0, ok.ids))
                else:
                    cleaned.append(cmd)
            elif cmd[0] == 4:  # (4, id) → agregar uno
                tax = self.env['account.tax'].browse(cmd[1])
                if tax.company_id.id == company_id or not tax.company_id:
                    cleaned.append(cmd)
                else:
                    _logger.info(
                        "ARBA multi-company: descartado tax %s (empresa %s)",
                        tax.name, company_id
                    )
            else:
                cleaned.append(cmd)
        vals['tax_id'] = cleaned

    # --- Capa 2: filtro en _compute_tax_id ---
    # Por qué: seguridad adicional para taxes que llegan por compute

    def _compute_tax_id(self):
        # Por qué: _arba_no_reentry corta el ciclo compute→write→compute
        # que genera loop infinito al filtrar taxes de otra empresa
        super(SaleOrderLine, self.with_context(_arba_no_reentry=True))._compute_tax_id()
        for line in self:
            if line.tax_id and line.company_id:
                taxes_ok = line.tax_id.filtered(lambda t: t.company_id == line.company_id)
                if taxes_ok != line.tax_id:
                    line.tax_id = taxes_ok

    # --- Capa 3: filtro en _prepare_invoice_line ---
    # Por qué: al crear factura desde pedido, _prepare_invoice_line pasa los
    # tax_ids del SO line al account.move.line. Si hay taxes de otra empresa
    # que sobrevivieron (ej: cargados manualmente), se filtran acá antes de
    # que _check_company de account.move.line los rechace.

    def _prepare_invoice_line(self, **optional_values):
        vals = super()._prepare_invoice_line(**optional_values)
        if vals.get('tax_ids') and self.company_id:
            # tax_ids viene como [(6, 0, [ids])]
            for i, cmd in enumerate(vals['tax_ids']):
                if cmd[0] == 6 and cmd[2]:
                    taxes = self.env['account.tax'].browse(cmd[2])
                    ok = taxes.filtered(lambda t: t.company_id == self.company_id)
                    if ok != taxes:
                        _logger.info(
                            "ARBA multi-company _prepare_invoice_line: descartados taxes %s",
                            (taxes - ok).mapped('name'),
                        )
                        vals['tax_ids'][i] = (6, 0, ok.ids)
        return vals

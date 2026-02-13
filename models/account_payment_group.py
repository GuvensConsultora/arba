from odoo import models, fields
from markupsafe import Markup


class AccountPaymentGroup(models.Model):
    """Override para agregar logging detallado en el cálculo de retenciones.
    Por qué: el motor OCA calcula en silencio y cuando no retiene
    no hay forma de saber por qué. Este override loguea cada paso
    en el chatter del Payment Group para facilitar el diagnóstico.
    """
    _inherit = 'account.payment.group'

    def compute_withholdings(self):
        for rec in self:
            if rec.partner_type != 'supplier':
                continue

            partner = rec.commercial_partner_id
            cuit = (partner.vat or '').replace('-', '')

            # --- PASO 1: Identificar partner y datos básicos ---
            msg = Markup('<div style="background:#f0f4ff;padding:12px;border-radius:8px;border:1px solid #ccc;">')
            msg += Markup('<h4 style="margin:0 0 8px 0;color:#333;">Cálculo de Retenciones — Diagnóstico</h4>')
            msg += Markup('<table style="width:100%%;border-collapse:collapse;">')
            msg += Markup('<tr><td style="padding:4px;font-weight:bold;">Partner:</td>'
                          '<td style="padding:4px;">%s</td></tr>') % partner.name
            msg += Markup('<tr><td style="padding:4px;font-weight:bold;">CUIT:</td>'
                          '<td style="padding:4px;">%s</td></tr>') % (partner.vat or 'SIN CUIT')
            msg += Markup('<tr><td style="padding:4px;font-weight:bold;">Provincia:</td>'
                          '<td style="padding:4px;">%s (ID: %s)</td></tr>') % (
                              partner.state_id.name or 'Sin provincia',
                              partner.state_id.id or '-')
            msg += Markup('</table>')

            # --- PASO 2: Buscar impuestos de retención ---
            all_taxes = self.env['account.tax'].with_context(type=None).search([
                ('type_tax_use', '=', rec.partner_type),
                ('company_id', '=', rec.company_id.id),
            ])
            withholding_taxes = all_taxes.filtered(lambda t: t.withholding_type != 'none')

            msg += Markup('<hr style="margin:8px 0;border-color:#ddd;"/>')
            msg += Markup('<b>Impuestos supplier encontrados:</b> %s total, '
                          '<b>%s con retención activa</b>') % (len(all_taxes), len(withholding_taxes))

            # --- PASO 3: Detalle por cada impuesto de retención ---
            for tax in withholding_taxes:
                msg += Markup('<div style="background:#fff;margin:8px 0;padding:8px;'
                              'border-left:3px solid #4a90d9;border-radius:4px;">')
                msg += Markup('<b>%s</b> (withholding_type=%s)') % (tax.name, tax.withholding_type)

                if tax.withholding_type == 'partner_tax':
                    # Buscar perception_ids del partner para este tax
                    perceptions = self.env['res.partner.perception'].search([
                        ('partner_id', '=', partner.id),
                        ('tax_id', '=', tax.id),
                    ])
                    if perceptions:
                        for perc in perceptions:
                            msg += Markup('<br/>perception_ids: <span style="color:green;">'
                                          'tax=%s, percent=%s%%</span>') % (perc.tax_id.name, perc.percent)
                    else:
                        msg += Markup('<br/><span style="color:red;font-weight:bold;">'
                                      'SIN perception_ids para este tax → alícuota = 0 → NO RETIENE</span>')
                        # Verificar si existe en el padrón
                        padron_ret = self.env['arba.padron'].search([
                            ('cuit', '=', cuit),
                            ('tipo', '=like', 'R%'),
                        ], limit=1)
                        if padron_ret:
                            msg += Markup('<br/><span style="color:orange;">Padrón ARBA tiene tasa %s%% '
                                          'para este CUIT, pero no se cargó en perception_ids. '
                                          'Ejecute "Procesar ZIP".</span>') % padron_ret.tasa
                        else:
                            msg += Markup('<br/><span style="color:gray;">CUIT %s NO encontrado en '
                                          'padrón retenciones (tipo R%%).</span>') % cuit

                    # Alícuota que devuelve get_partner_alicuot
                    alicuota = tax.get_partner_alicuot(
                        partner, rec.payment_date or fields.Date.context_today(self))
                    msg += Markup('<br/>get_partner_alicuot() → <b>%s</b>') % alicuota

                    # Base imponible
                    try:
                        vals = tax.get_withholding_vals(rec)
                        base = vals.get('withholdable_base_amount', 0)
                        period_amount = vals.get('period_withholding_amount', 0)
                        prev_amount = vals.get('previous_withholding_amount', 0)
                        computed = max(0, period_amount - prev_amount)
                        msg += Markup('<br/>Base imponible: <b>%s</b>') % f"{base:,.2f}"
                        msg += Markup('<br/>Retención período: <b>%s</b>') % f"{period_amount:,.2f}"
                        msg += Markup('<br/>Retenciones previas: <b>%s</b>') % f"{prev_amount:,.2f}"
                        msg += Markup('<br/>Retención calculada: <b style="color:%s;">%s</b>') % (
                            'green' if computed > 0 else 'red',
                            f"{computed:,.2f}")
                    except Exception as e:
                        msg += Markup('<br/><span style="color:red;">Error en get_withholding_vals: %s</span>') % str(e)

                elif tax.withholding_type == 'tabla_ganancias':
                    msg += Markup('<br/>Régimen Ganancias: %s') % (
                        rec.retencion_ganancias or 'NO CONFIGURADO')
                    if rec.retencion_ganancias == 'nro_regimen':
                        msg += Markup(' → régimen: %s') % (
                            rec.regimen_ganancias_id.display_name or 'VACÍO')
                    msg += Markup('<br/>imp_ganancias_padron: %s') % (
                        partner.imp_ganancias_padron or 'NO CONFIGURADO')

                elif tax.withholding_type == 'based_on_rule':
                    rule = tax._get_rule(rec)
                    msg += Markup('<br/>Regla encontrada: %s') % (
                        f"percentage={rule.percentage}, fix={rule.fix_amount}" if rule else 'NINGUNA')

                msg += Markup('</div>')

            # --- PASO 4: Estado de automatic_withholdings ---
            msg += Markup('<hr style="margin:8px 0;border-color:#ddd;"/>')
            msg += Markup('<b>automatic_withholdings:</b> %s') % (
                Markup('<span style="color:green;">Activado</span>') if rec.company_id.automatic_withholdings
                else Markup('<span style="color:red;">Desactivado</span>'))

            msg += Markup('</div>')
            rec.message_post(body=msg)

        # Llamar al cálculo real del motor OCA
        return super().compute_withholdings()

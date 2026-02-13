from odoo import models, fields
from markupsafe import Markup


class AccountPaymentGroup(models.Model):
    """Override para trackear TODO el proceso de cálculo de retenciones en el chatter.
    Por qué: el motor OCA calcula en silencio. Este override reemplaza
    compute_withholdings() con una versión que loguea cada paso en el chatter
    del Payment Group, y luego ejecuta el cálculo real.
    """
    _inherit = 'account.payment.group'

    def compute_withholdings(self):
        for rec in self:
            if rec.partner_type != 'supplier':
                continue

            partner = rec.commercial_partner_id
            cuit = (partner.vat or '').replace('-', '')

            # =============================================
            # PASO 1: INICIO — Datos del pago
            # =============================================
            msg = Markup('<div style="background:#f0f4ff;padding:14px;border-radius:8px;'
                         'border:1px solid #b0c4de;font-size:13px;">')
            msg += Markup('<h3 style="margin:0 0 10px 0;color:#1a3e5c;">'
                         'Tracking Retenciones — Paso a paso</h3>')

            msg += Markup('<div style="background:#e8f0fe;padding:10px;border-radius:6px;margin-bottom:10px;">')
            msg += Markup('<b>PASO 1: Datos del pago</b><br/>')
            msg += Markup('Partner: <b>%s</b><br/>') % partner.name
            msg += Markup('CUIT: <b>%s</b><br/>') % (partner.vat or 'SIN CUIT')
            msg += Markup('Provincia: <b>%s</b> (ID: %s)<br/>') % (
                partner.state_id.name or 'Sin provincia', partner.state_id.id or '-')
            msg += Markup('Fecha de pago: <b>%s</b><br/>') % (rec.payment_date or '-')
            msg += Markup('Monto a pagar: <b>%s</b><br/>') % f"{rec.to_pay_amount:,.2f}"
            msg += Markup('automatic_withholdings: %s') % (
                Markup('<b style="color:green;">SI</b>') if rec.company_id.automatic_withholdings
                else Markup('<b style="color:red;">NO</b>'))
            msg += Markup('</div>')

            # =============================================
            # PASO 2: BÚSQUEDA — Impuestos de retención
            # =============================================
            all_taxes = self.env['account.tax'].with_context(type=None).search([
                ('type_tax_use', '=', rec.partner_type),
                ('company_id', '=', rec.company_id.id),
            ])
            withholding_taxes = all_taxes.filtered(lambda x: x.withholding_type != 'none')
            no_withholding_taxes = all_taxes.filtered(lambda x: x.withholding_type == 'none')

            msg += Markup('<div style="background:#e8f0fe;padding:10px;border-radius:6px;margin-bottom:10px;">')
            msg += Markup('<b>PASO 2: Búsqueda de impuestos supplier</b><br/>')
            msg += Markup('Total impuestos supplier: <b>%s</b><br/>') % len(all_taxes)
            msg += Markup('Con retención activa (withholding_type != none): <b>%s</b><br/>') % len(withholding_taxes)
            msg += Markup('Sin retención (se ignoran): <b>%s</b><br/>') % len(no_withholding_taxes)

            if withholding_taxes:
                msg += Markup('<br/><u>Impuestos que se van a evaluar:</u><br/>')
                for tax in withholding_taxes:
                    msg += Markup('&nbsp;&nbsp;- %s (tipo: %s, amount: %s)<br/>') % (
                        tax.name, tax.withholding_type, tax.amount)
            else:
                msg += Markup('<br/><span style="color:red;font-weight:bold;">'
                              'No hay impuestos con retención activa. El proceso termina acá.</span>')
            msg += Markup('</div>')

            # =============================================
            # PASO 3: EVALUACIÓN — Por cada impuesto
            # =============================================
            paso = 2
            for tax in withholding_taxes:
                paso += 1
                color_borde = '#4a90d9'

                msg += Markup('<div style="background:#fff;padding:10px;border-radius:6px;'
                              'margin-bottom:10px;border-left:4px solid %s;">') % color_borde
                msg += Markup('<b>PASO %s: Evaluar "%s"</b><br/>') % (paso, tax.name)
                msg += Markup('withholding_type: <b>%s</b><br/>') % tax.withholding_type
                msg += Markup('withholding_amount_type: <b>%s</b><br/>') % (
                    tax.withholding_amount_type or 'NO CONFIGURADO')
                msg += Markup('Mínimo no imponible: <b>%s</b><br/>') % f"{tax.withholding_non_taxable_minimum:,.2f}"
                msg += Markup('Monto no imponible: <b>%s</b><br/>') % f"{tax.withholding_non_taxable_amount:,.2f}"
                msg += Markup('Pagos acumulados: <b>%s</b><br/>') % (
                    tax.withholding_accumulated_payments or 'No acumula')

                # --- 3a: Verificar retención existente ---
                existing_payment = self.env['account.payment'].search([
                    ('payment_group_id', '=', rec.id),
                    ('tax_withholding_id', '=', tax.id),
                    ('automatic', '=', True),
                ], limit=1)
                if existing_payment:
                    msg += Markup('Retención existente: <b>SI</b> (pago %s por %s)<br/>') % (
                        existing_payment.name, f"{existing_payment.amount:,.2f}")
                else:
                    msg += Markup('Retención existente: <b>NO</b> (se creará si corresponde)<br/>')

                # --- 3b: Según tipo de retención ---
                if tax.withholding_type == 'partner_tax':
                    msg += Markup('<br/><u>Tipo: Alícuota en el Partner</u><br/>')

                    # Buscar perception_ids
                    perceptions = self.env['res.partner.perception'].search([
                        ('partner_id', '=', partner.id),
                        ('tax_id', '=', tax.id),
                    ])
                    all_partner_perceptions = self.env['res.partner.perception'].search([
                        ('partner_id', '=', partner.id),
                    ])

                    msg += Markup('Total perception_ids del partner: <b>%s</b><br/>') % len(all_partner_perceptions)
                    if all_partner_perceptions:
                        for p in all_partner_perceptions:
                            match = ' (MATCH)' if p.tax_id.id == tax.id else ''
                            color = 'green' if p.tax_id.id == tax.id else 'gray'
                            msg += Markup('&nbsp;&nbsp;- tax: %s, percent: %s%%%s<br/>') % (
                                p.tax_id.name,
                                p.percent,
                                Markup('<b style="color:%s;">%s</b>') % (color, match))

                    if perceptions:
                        perc = perceptions[0]
                        msg += Markup('<br/>Alícuota encontrada: <b style="color:green;">%s%%</b><br/>') % perc.percent
                    else:
                        msg += Markup('<br/><span style="color:red;font-weight:bold;">'
                                      'NO se encontró perception para tax "%s" en este partner</span><br/>') % tax.name
                        # Buscar en padrón
                        padron_ret = self.env['arba.padron'].search([
                            ('cuit', '=', cuit), ('tipo', '=like', 'R%'),
                        ], limit=1)
                        if padron_ret:
                            msg += Markup('<span style="color:orange;">'
                                          'El padrón ARBA tiene tasa %s%% para CUIT %s, '
                                          'pero no se cargó en perception_ids. '
                                          'Ejecute "Procesar ZIP" para cargarla.</span><br/>') % (
                                              padron_ret.tasa, cuit)
                        else:
                            msg += Markup('<span style="color:gray;">'
                                          'CUIT %s NO está en el padrón de retenciones.</span><br/>') % cuit

                    # Ejecutar get_partner_alicuot
                    alicuota = tax.get_partner_alicuot(
                        partner, rec.payment_date or fields.Date.context_today(self))
                    msg += Markup('get_partner_alicuot() devuelve: <b>%s</b><br/>') % alicuota

                elif tax.withholding_type == 'tabla_ganancias':
                    msg += Markup('<br/><u>Tipo: Tabla Ganancias</u><br/>')
                    msg += Markup('retencion_ganancias: <b>%s</b><br/>') % (
                        rec.retencion_ganancias or 'NO SELECCIONADO')
                    if rec.retencion_ganancias == 'nro_regimen':
                        msg += Markup('regimen_ganancias_id: <b>%s</b><br/>') % (
                            rec.regimen_ganancias_id.display_name or 'VACÍO')
                    msg += Markup('imp_ganancias_padron del partner: <b>%s</b><br/>') % (
                        partner.imp_ganancias_padron or 'NO CONFIGURADO')
                    if rec.retencion_ganancias != 'nro_regimen' or not rec.regimen_ganancias_id:
                        msg += Markup('<span style="color:orange;">'
                                      'Sin régimen seleccionado → retención Ganancias = 0</span><br/>')

                elif tax.withholding_type == 'based_on_rule':
                    msg += Markup('<br/><u>Tipo: Basado en Regla</u><br/>')
                    rule = tax._get_rule(rec)
                    if rule:
                        msg += Markup('Regla: percentage=%s, fix_amount=%s<br/>') % (
                            rule.percentage, rule.fix_amount)
                    else:
                        msg += Markup('<span style="color:red;">No se encontró regla aplicable</span><br/>')

                elif tax.withholding_type == 'code':
                    msg += Markup('<br/><u>Tipo: Python Code</u><br/>')
                    msg += Markup('Código configurado: <b>SI</b><br/>')

                # --- 3c: Calcular montos (get_withholding_vals) ---
                msg += Markup('<br/><u>Cálculo de montos:</u><br/>')
                try:
                    vals = tax.get_withholding_vals(rec)

                    withholdable_invoiced = vals.get('withholdable_invoiced_amount', 0)
                    withholdable_advanced = vals.get('withholdable_advanced_amount', 0)
                    accumulated = vals.get('accumulated_amount', 0)
                    total = vals.get('total_amount', 0)
                    non_taxable_min = vals.get('withholding_non_taxable_minimum', 0)
                    non_taxable_amt = vals.get('withholding_non_taxable_amount', 0)
                    base = vals.get('withholdable_base_amount', 0)
                    period_amount = vals.get('period_withholding_amount', 0)
                    prev_amount = vals.get('previous_withholding_amount', 0)
                    comment = vals.get('comment', '')

                    currency = rec.currency_id
                    period_rounded = currency.round(period_amount)
                    prev_rounded = currency.round(prev_amount)
                    computed = max(0, period_rounded - prev_rounded)

                    msg += Markup('Monto facturado retenible: <b>%s</b><br/>') % f"{withholdable_invoiced:,.2f}"
                    msg += Markup('Monto adelanto retenible: <b>%s</b><br/>') % f"{withholdable_advanced:,.2f}"
                    msg += Markup('Pagos acumulados período: <b>%s</b><br/>') % f"{accumulated:,.2f}"
                    msg += Markup('Total amount: <b>%s</b><br/>') % f"{total:,.2f}"
                    msg += Markup('Mínimo no imponible: <b>%s</b> (total > mínimo? %s)<br/>') % (
                        f"{non_taxable_min:,.2f}",
                        Markup('<b style="color:green;">SI</b>') if total > non_taxable_min
                        else Markup('<b style="color:red;">NO → base = 0</b>'))
                    msg += Markup('Monto no imponible a restar: <b>%s</b><br/>') % f"{non_taxable_amt:,.2f}"
                    msg += Markup('Base imponible (total - no imponible): <b>%s</b><br/>') % f"{base:,.2f}"

                    msg += Markup('<br/><div style="background:#f5f5f5;padding:8px;border-radius:4px;">')
                    msg += Markup('Retención del período: <b>%s</b><br/>') % f"{period_rounded:,.2f}"
                    msg += Markup('Retenciones previas: <b>%s</b><br/>') % f"{prev_rounded:,.2f}"
                    msg += Markup('Cálculo: %s<br/>') % (comment or '-')

                    if computed > 0:
                        msg += Markup('<b style="color:green;font-size:14px;">'
                                      'RETENCIÓN A CREAR: %s</b>') % f"{computed:,.2f}"
                    else:
                        msg += Markup('<b style="color:red;font-size:14px;">'
                                      'RETENCIÓN = 0 → No se crea pago</b>')
                    msg += Markup('</div>')

                except Exception as e:
                    msg += Markup('<span style="color:red;font-weight:bold;">'
                                  'ERROR en get_withholding_vals(): %s</span><br/>') % str(e)

                # --- 3d: Verificar diario de retenciones ---
                msg += Markup('<br/><u>Diario de retenciones:</u><br/>')
                try:
                    payment_method = self.env.ref(
                        'account_withholding.account_payment_method_out_withholding')
                    journals = self.env['account.journal'].search([
                        ('company_id', '=', tax.company_id.id),
                        ('type', '=', 'cash'),
                    ])
                    journal_found = None
                    for jour in journals:
                        for outbound in jour.outbound_payment_method_line_ids:
                            if outbound.payment_method_id.id == payment_method.id:
                                journal_found = jour
                                break
                    if journal_found:
                        msg += Markup('Diario: <b style="color:green;">%s</b><br/>') % journal_found.name
                    else:
                        msg += Markup('<span style="color:red;">No se encontró diario tipo cash '
                                      'con método de pago Withholding</span><br/>')
                except Exception as e:
                    msg += Markup('<span style="color:red;">Error buscando diario: %s</span><br/>') % str(e)

                msg += Markup('</div>')

            # =============================================
            # PASO FINAL: Resumen
            # =============================================
            paso += 1
            msg += Markup('<div style="background:#e8f0fe;padding:10px;border-radius:6px;">')
            msg += Markup('<b>PASO %s: Ejecutando cálculo real (super().compute_withholdings)</b><br/>') % paso
            msg += Markup('El motor OCA ahora ejecuta el cálculo y crea/actualiza los pagos de retención.')
            msg += Markup('</div>')

            msg += Markup('</div>')
            rec.message_post(body=msg)

        # Ejecutar el cálculo real del motor OCA
        return super().compute_withholdings()

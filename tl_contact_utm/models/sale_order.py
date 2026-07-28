from odoo import api, fields, models, tools

class SaleOrder(models.Model):
    _inherit = "sale.order"

    @api.onchange('partner_id')
    def _onchange_partner_id_for_utm(self):
        for rec in self:
            rec.source_id = rec.partner_id.customer_source_id.id

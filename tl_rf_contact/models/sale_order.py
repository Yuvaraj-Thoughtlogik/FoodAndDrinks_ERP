from odoo import api, models


class SaleOrder(models.Model):
    _inherit = "sale.order"

    @api.model_create_multi
    def create(self, vals_list):
        orders = super().create(vals_list)

        for order in orders:
            if order.partner_id and order.source_id:
                order.partner_id.with_context(
                    active_model=order._name,
                    active_id=order.id,
                ).write({
                    "customer_source_id": order.source_id.id,
                })

        return orders

    def write(self, vals):
        res = super().write(vals)

        if "source_id" in vals:
            for order in self:
                if order.partner_id:
                    order.partner_id.with_context(
                        active_model=order._name,
                        active_id=order.id,
                    ).write({
                        "customer_source_id": order.source_id.id,
                    })

        return res
# -*- coding: utf-8 -*-
from odoo import models, api, _


class SaleOrder(models.Model):
    _inherit = "sale.order"

    def action_confirm(self):
        res = super().action_confirm()
        for order in self:
            for line in order.order_line.filtered(lambda l: not l.display_type):
                line.confirmed_qty = line.product_uom_qty
        return res

    def bulk_confirm_orders(self):
        active_ids = self.env.context.get('active_ids', [])
        records = self if self else self.browse(active_ids)

        for rec in records:
            if rec.state == 'draft':
                rec.action_confirm()

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Success'),
                'type': 'success',
                'message': _('Orders confirmed successfully.'),
                'next': {
                    'type': 'ir.actions.client',
                    'tag': 'soft_reload',
                },
            },
        }
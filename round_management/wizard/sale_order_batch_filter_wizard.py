from odoo import api, fields, models


class SaleOrderBatchFilterWizard(models.TransientModel):
    _name = 'sale.order.batch.filter.wizard'
    _description = 'Sale Order Batch Filter'

    batch_ids = fields.Many2many(
        'round.management.batch',
        string='Round Batches',
    )

    def action_confirm(self):
        self.ensure_one()

        action = self.env["ir.actions.actions"]._for_xml_id(
            "sale.action_orders"
        )
        action["context"] = {
            **self.env.context,
            "search_default_batch_id": self.batch_ids.ids,
        }
        domain = []

        if self.batch_ids:
            domain.append(("batch_id", "in", self.batch_ids.ids))

        action["domain"] = domain

        return action
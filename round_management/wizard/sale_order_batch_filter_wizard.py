from odoo import api, fields, models


class SaleOrderBatchFilterWizard(models.TransientModel):
    _name = 'sale.order.batch.filter.wizard'
    _description = 'Sale Order Batch Filter'

    round_id = fields.Many2one(comodel_name='round.management.round', string='Round Code')
    batch_id = fields.Many2one(
        'round.management.batch',
        string='Round Batches',
        domain="[('round_id', '=?', round_id), ('state', 'in', ['act', 'pln'])]",
    )

    def action_confirm(self):
        self.ensure_one()

        action = self.env["ir.actions.actions"]._for_xml_id(
            "sale.action_orders"
        )
        action["context"] = {
            **self.env.context,
            "search_default_batch_id": self.batch_id.id,
        }
        domain = []

        # if self.batch_id:
        #     domain.append(("batch_id", "=", self.batch_id.id))
        #
        # action["domain"] = domain

        return action
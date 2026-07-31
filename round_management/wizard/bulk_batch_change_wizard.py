from odoo import models, fields, api
from odoo.exceptions import UserError


class BulkBatchChangeWizard(models.TransientModel):
    _name = 'bulk.batch.change.wizard'
    _description = 'Bulk Change Batch Wizard for Sale Orders'

    batch_id = fields.Many2one(
        'round.management.batch', 
        string='New Batch Code', 
        required=True,
        domain="[('id', 'in', available_batch_ids)]"
    )
    available_batch_ids = fields.Many2many(
        'round.management.batch',
        string='Available Batches',
        compute='_compute_available_batches'
    )
    order_count = fields.Integer(string='Selected Orders Count', compute='_compute_available_batches')
    delivery_date = fields.Date(string='Delivery Date', compute='_compute_available_batches')

    @api.depends()
    def _compute_available_batches(self):
        """Finds alternative batches matching the delivery date of selected orders."""
        active_ids = self.env.context.get('active_ids', [])
        orders = self.env['sale.order'].browse(active_ids)

        for wizard in self:
            if not orders:
                wizard.available_batch_ids = [(5, 0, 0)]
                wizard.order_count = 0
                wizard.delivery_date = False
                continue

            # Get distinct delivery dates from selected orders
            delivery_dates = {
                order.commitment_date.date() if order.commitment_date else False 
                for order in orders
            }

            # Validation: All selected orders must have the same delivery date set
            if len(delivery_dates) > 1 or False in delivery_dates:
                raise UserError(
                    "Selected sale orders must all have a valid Delivery Date set and belong to the same Delivery Date."
                )

            target_date = list(delivery_dates)[0]
            wizard.delivery_date = target_date
            wizard.order_count = len(orders)

            # Filter batches matching the target delivery date
            batches = self.env['round.management.batch'].search([
                ('delivery_date', '=', target_date)
            ])
            
            wizard.available_batch_ids = batches.ids

    def action_apply_batch_change(self):
        """Applies the selected batch to active sale orders and shows a popup message."""
        self.ensure_one()
        active_ids = self.env.context.get('active_ids', [])
        if active_ids and self.batch_id:
            orders = self.env['sale.order'].browse(active_ids)
            orders.write({'batch_id': self.batch_id.id})

            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Batch Change Successful',
                    'message': f"Updated {len(orders)} order(s) to Batch '{self.batch_id.display_name}'.",
                    'type': 'success',
                    'sticky': False,
                    'next': {'type': 'ir.actions.act_window_close'},
                }
            }
        return {'type': 'ir.actions.act_window_close'}

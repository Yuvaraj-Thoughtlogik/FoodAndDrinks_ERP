from odoo import models, fields, api


class BulkBatchChangeWizard(models.TransientModel):
    _name = 'bulk.batch.change.wizard'
    _description = 'Bulk Change Batch Wizard for Sale Orders'

    round_id = fields.Many2one(comodel_name='round.management.round', string='Round Code')
    delivery_date = fields.Date(string='Delivery Date',default=fields.Date.today)
    batch_id = fields.Many2one(
        'round.management.batch', 
        string='New Batch Code', 
        required=True,
        domain="[('id', 'in', available_batch_ids)]"
    )
    available_batch_ids = fields.Many2many(
        'round.management.batch',
        string='Available Batches',
        compute='_compute_wizard_details'
    )
    order_count = fields.Integer(string='Selected Orders Count', compute='_compute_wizard_details')
    delivery_dates_str = fields.Char(string='Delivery Dates', compute='_compute_wizard_details')
    current_batches_str = fields.Char(string='Current Batches', compute='_compute_wizard_details')

    @api.depends('round_id', 'delivery_date')
    def _compute_wizard_details(self):
        """Computes count, delivery dates, and current batches for the banner display."""
        active_ids = self.env.context.get('active_ids', [])
        orders = self.env['sale.order'].browse(active_ids) if active_ids else self.env['sale.order']

        # Collect distinct delivery dates
        delivery_dates = {
            order.commitment_date.strftime('%Y-%m-%d') 
            for order in orders if order.commitment_date
        }

        # Collect current batch names
        current_batches = {
            order.batch_id.display_name for order in orders if order.batch_id
        }
        BATCH = self.env['round.management.batch']

        for wizard in self:
            wizard.order_count = len(orders)
            wizard.delivery_dates_str = ", ".join(sorted(delivery_dates)) if delivery_dates else "None"
            wizard.current_batches_str = ", ".join(sorted(current_batches)) if current_batches else "Unassigned"

            # Filter matching batches by delivery date
            domain =[("state", "in", ["act", "prt"])]
            if wizard.round_id:
                domain.append(("round_id", "=", wizard.round_id.id))
            # if delivery_dates:
            #     domain.append(('delivery_date', '=', list(sorted(delivery_dates))))
            if wizard.delivery_date:
                domain.append(("delivery_date", "=", wizard.delivery_date))

            wizard.available_batch_ids = BATCH.search(domain)

    def action_apply_batch_change(self):
        """Applies batch to sale orders and opens summary popup."""
        self.ensure_one()
        active_ids = self.env.context.get('active_ids', [])
        
        if active_ids and self.batch_id:
            orders = self.env['sale.order'].browse(active_ids)
            count = len(orders)

            # Collect unique old batch names
            old_batches = [
                order.batch_id.display_name for order in orders if order.batch_id
            ]
            
            if old_batches:
                unique_old_batches = list(dict.fromkeys(old_batches))
                old_batch_str = ", ".join(unique_old_batches)
            else:
                old_batch_str = "No Previous Batch"

            new_batch_name = self.batch_id.display_name or 'New Batch'

            # Update batch on selected sale orders
            orders.write({'batch_id': self.batch_id.id})

            summary_msg = f"Successfully updated {count} order(s) to Batch: {new_batch_name}"

            summary = self.env['wizard.bulk.batch.summary'].sudo().create({
                'transferred_count': count,
                'old_batch_name': old_batch_str,
                'new_batch_name': new_batch_name,
                'message': summary_msg
            })

            return {
                'name': 'Batch Transfer Summary',
                'type': 'ir.actions.act_window',
                'res_model': 'wizard.bulk.batch.summary',
                'res_id': summary.id,
                'view_mode': 'form',
                'target': 'new',
            }

        return {'type': 'ir.actions.act_window_close'}


class WizardBulkBatchSummary(models.TransientModel):
    _name = 'wizard.bulk.batch.summary'
    _description = 'Bulk Batch Change Summary Popup'

    transferred_count = fields.Integer(string='Transferred Orders Count', readonly=True)
    old_batch_name = fields.Char(string='Previous Batch', readonly=True)
    new_batch_name = fields.Char(string='New Batch', readonly=True)
    message = fields.Text(string='Details', readonly=True)

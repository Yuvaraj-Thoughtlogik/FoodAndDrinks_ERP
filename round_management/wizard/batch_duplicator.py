from odoo import models, fields, api, _
from odoo.exceptions import UserError

class BatchDuplicatorWizard(models.TransientModel):
    _name = 'batch.duplicator.wizard'
    _description = 'Duplicate Batches Wizard'

    delivery_date = fields.Date(
        string='Target Delivery Date', 
        required=True, 
        default=fields.Date.context_today
    )
    reference = fields.Char(string='New Reference')

    @api.model
    def action_open_duplicator_wizard(self):
        """Called by Server Action in the Gear menu to open the prompt modal."""
        active_ids = self.env.context.get('active_ids', [])
        if not active_ids:
            raise UserError(_("Please select at least one batch row to duplicate."))
        
        return {
            'name': _('Duplicate Round Batches'),
            'type': 'ir.actions.act_window',
            'res_model': 'batch.duplicator.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': self.env.context,
        }

    def action_duplicate_batches(self):
        """Executes the duplication upon modal confirmation."""
        self.ensure_one()
        active_ids = self.env.context.get('active_ids', [])
        active_batches = self.env['round.management.batch'].browse(active_ids)
        
        if not active_batches:
            raise UserError(_("Please select at least one batch row to duplicate."))

        new_batches = self.env['round.management.batch']
        for batch in active_batches:
            iso_year, iso_week, _day = self.delivery_date.isocalendar()
            formatted_week = f"{iso_year}{str(iso_week).zfill(2)}"
            
            new_batch = batch.copy({
                'delivery_date': self.delivery_date,
                'reference': self.reference or batch.reference,
                'state': 'pln',
                'duplication_comments': f"Duplicated on {fields.Date.today()} for week {formatted_week}"
            })
            new_batches |= new_batch

        return {
            'name': _('Newly Scheduled Batches'),
            'type': 'ir.actions.act_window',
            'res_model': 'round.management.batch',
            'view_mode': 'list,form',
            'domain': [('id', 'in', new_batches.ids)],
            'target': 'current',
        }

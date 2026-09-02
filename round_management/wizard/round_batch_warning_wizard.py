from odoo import models, fields

class RoundBatchWarningWizard(models.TransientModel):
    _name = 'round.batch.warning.wizard'
    _description = 'Existing Active Batch Warning Wizard'

    message = fields.Text(string="Warning Message", readonly=True)
    batch_id = fields.Many2one('round.management.batch', string="Target Batch")

    def action_confirm(self):
        """User clicked OK/Continue to proceed."""
        self.ensure_one()
        
        if self.env.context.get('trigger_start_batch') and self.batch_id:
            return self.batch_id.with_context(skip_active_batch_check=True).action_start_batch()
        return {'type': 'ir.actions.act_window_close'}

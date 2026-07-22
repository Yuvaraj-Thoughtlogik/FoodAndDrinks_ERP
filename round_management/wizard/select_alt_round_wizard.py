from odoo import models, fields, api, _
from odoo.exceptions import UserError

class SelectAltRoundWizard(models.TransientModel):
    _name = 'select.alt.round.wizard'
    _description = 'Select Alternative Delivery Round Wizard'

    sale_order_id = fields.Many2one('sale.order', string='Sales Order', required=True)
    line_ids = fields.One2many('select.alt.round.line', 'wizard_id', string='Alternative Rounds')

    def action_apply_round(self):
        """Applies the checked round to the Sales Order."""
        self.ensure_one()
        selected_lines = self.line_ids.filtered(lambda l: l.selected)
        
        if not selected_lines:
            raise UserError(_("Please select a delivery round."))
        if len(selected_lines) > 1:
            raise UserError(_("Please select only ONE delivery round to apply."))

        # Assign selected round to Sale Order
        self.sale_order_id.write({'round_id': selected_lines.round_id.id})
        return {'type': 'ir.actions.act_window_close'}


class SelectAltRoundLine(models.TransientModel):
    _name = 'select.alt.round.line'
    _description = 'Select Alternative Delivery Round Line'

    wizard_id = fields.Many2one('select.alt.round.wizard', ondelete='cascade')
    selected = fields.Boolean(string='Select', default=False)
    round_id = fields.Many2one('round.management.round', string='Round', required=True)
    
    code = fields.Char(related='round_id.code', string='Round Code', readonly=True)
    name = fields.Char(related='round_id.name', string='Round Name', readonly=True)
    state = fields.Selection(related='round_id.state', string='Status', readonly=True)

import logging

from odoo import models, fields, api
from odoo.tools import _
from odoo.exceptions import UserError, ValidationError


_logger = logging.getLogger(__name__)

class SelectAltRoundWizard(models.TransientModel):
    _name = 'select.alt.round.wizard'
    _description = 'Select Alternative Delivery Round Wizard'

    sale_order_id = fields.Many2one('sale.order', string='Sales Order', required=True)
    line_ids = fields.One2many(
        comodel_name='select.alt.round.line',
        inverse_name='wizard_id',
        string='Alternative Rounds'
    )




    @api.model
    def default_get(self, fields_list):
        """Auto-populates the wizard lines with Round Batches when opened."""
        res = super(SelectAltRoundWizard, self).default_get(fields_list)
        batches = self.env['round.management.batch'].search([])
        
        lines = []
        for batch in batches:
            lines.append((0, 0, {
                'batch_id': batch.id,
                'selected': False,
            }))
        res['line_ids'] = lines
        return res

    def action_apply_round(self):
        """Updates the existing batch_id field on Sale Order."""
        self.ensure_one()

        selected_lines = self.line_ids.filtered(lambda l: l.selected)

        if not selected_lines:
            raise UserError(_("Please select a Round Batch before applying."))
        if len(selected_lines) > 1:
            raise UserError(_("You can only select one Round Batch at a time."))


        if selected_lines.batch_id.is_alt_limit_reached:
            raise ValidationError(_("Max Alternative Drops have been reached for this batch."))
        # Update the existing batch_id directly
        if self.sale_order_id:
            self.sale_order_id.write({
                'batch_id': selected_lines.batch_id.id,
            })

        return {'type': 'ir.actions.act_window_close'}

    @api.onchange('line_ids')
    def _onchange_line_ids(self):
        """Monitors child line toggles in real-time and blocks multi-selection instantly."""
        selected_lines = self.line_ids.filtered(lambda l: l.selected)

<<<<<<< HEAD
        if len(selected_lines) > 1:
           
            selected_lines[-1].selected = False
            return {
                'warning': {
                    'title': _("Invalid Selection"),
                    'message': _("You can only select one Round Batch at a time."),
                }
            }
            
=======


>>>>>>> 1b951b2b565cfe8dfde2b15a1a450d34b9195b8b
class SelectAltRoundLine(models.TransientModel):
    _name = 'select.alt.round.line'
    _description = 'Select Alternative Delivery Round Line'

    wizard_id = fields.Many2one('select.alt.round.wizard', ondelete='cascade')
    selected = fields.Boolean(
        string='Select',
        default=False,
        readonly=False,
    )
    
    batch_id = fields.Many2one('round.management.batch', string='Batch', required=True)
    is_alt_limit_reached = fields.Boolean(related='batch_id.is_alt_limit_reached',string="Max Alt Reached", store=True)
    code = fields.Char(related='batch_id.code', string='Batch Code', readonly=True)
    state = fields.Selection(related='batch_id.state', string='Status', readonly=True)
    round_id = fields.Many2one(related='batch_id.round_id', string='Round', readonly=True)
    reference = fields.Char(related='batch_id.reference', string='Reference', readonly=True)
    depot_id = fields.Many2one(related='batch_id.depot_id', string='Depot', readonly=True)
    delivery_date = fields.Date(related='batch_id.delivery_date', string='Delivery Date', readonly=True)

    @api.onchange('selected')
    def _onchange_selected(self):
        if self.selected and self.is_alt_limit_reached:
            self.selected = False
            raise ValidationError(_("Max Alternative Drops have been reached for this batch."))

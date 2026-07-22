from odoo import models, fields, api

class WizardBulkRoundChange(models.TransientModel):
    _name = 'wizard.bulk.round.change'
    _description = 'Bulk Move Customers to New Round'

    old_round_id = fields.Many2one('round.management.round', string='Old Round', required=True)
    new_round_id = fields.Many2one('round.management.round', string='New Round', required=True)
    
    partner_ids = fields.Many2many('res.partner', string='Customers to Move')
    
    

    @api.onchange('old_round_id')
    def _onchange_old_round_id(self):
        """Automatically load all active customers assigned to the selected old round"""
        if self.old_round_id:
            partners = self.env['res.partner'].search([('round_id', '=', self.old_round_id.id)])
            self.partner_ids = [(6, 0, partners.ids)]
        else:
            self.partner_ids = [(5, 0, 0)]

    def process_round_change(self):
        """Updates the selected customers to the new delivery round"""
        self.ensure_one()
        if self.partner_ids and self.new_round_id:
            self.partner_ids.write({'round_id': self.new_round_id.id})
        return {'type': 'ir.actions.act_window_close'}
        
        
        
        
class BulkRoundChangeWizard(models.TransientModel):
    _name = 'bulk.round.change.wizard'
    _description = 'Bulk Change Round Wizard for Sale Orders'

    round_id = fields.Many2one('round.management.round', string='New Round', required=True)

    def action_apply_round_change(self):
        """Applies the selected round to all checked Sale Orders."""
        active_ids = self.env.context.get('active_ids', [])
        if active_ids:
            orders = self.env['sale.order'].browse(active_ids)
            orders.write({'round_id': self.round_id.id})
        return {'type': 'ir.actions.act_window_close'}

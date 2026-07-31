from odoo import models, fields, api


class WizardBulkRoundChange(models.TransientModel):
    _name = 'wizard.bulk.round.change'
    _description = 'Bulk Move Customers to New Round'

    old_round_id = fields.Many2one('round.management.round', string='Old Round')
    new_round_id = fields.Many2one('round.management.round', string='New Round')

    line_ids = fields.One2many(
        'wizard.bulk.round.change.line',
        'wizard_id',
        string='Customers to Move'
    )

    @api.onchange('old_round_id')
    def _onchange_old_round_id(self):
        """Loads partners from old round with selected=False by default."""
        if self.old_round_id:
            partners = self.env['res.partner'].search([('round_id', '=', self.old_round_id.id)])
            lines = [(0, 0, {
                'selected': False,
                'partner_id': partner.id,
            }) for partner in partners]
            self.line_ids = [(5, 0, 0)] + lines
        else:
            self.line_ids = [(5, 0, 0)]

    def action_select_all(self):
        """Selects all target lines and keeps the wizard open with populated data."""
        self.ensure_one()
        for line in self.line_ids:
            line.selected = True
        
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_deselect_all(self):
        """Deselects all target lines and keeps the wizard open with populated data."""
        self.ensure_one()
        for line in self.line_ids:
            line.selected = False

        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def process_round_change(self):
        """Transfers selected customers and opens a summary popup dialog."""
        self.ensure_one()
        selected_partners = self.line_ids.filtered(lambda l: l.selected).mapped('partner_id')
        count = len(selected_partners)

        if count > 0 and self.new_round_id:
            old_name = self.old_round_id.display_name or 'Old Round'
            new_name = self.new_round_id.display_name or 'New Round'

            # Update round on selected customers
            selected_partners.write({'round_id': self.new_round_id.id})

            # Create summary dialog record using .sudo() to avoid Access Error
            summary = self.env['wizard.bulk.round.summary'].sudo().create({
                'transferred_count': count,
                'old_round_name': old_name,
                'new_round_name': new_name,
                'message': f"Successfully transferred {count} customer(s) from '{old_name}' to '{new_name}'."
            })

            # Open Summary Popup
            return {
                'name': 'Transfer Summary',
                'type': 'ir.actions.act_window',
                'res_model': 'wizard.bulk.round.summary',
                'res_id': summary.id,
                'view_mode': 'form',
                'target': 'new',
            }

        # Warning notification if no customers selected
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'No Customers Selected',
                'message': 'Please select at least one customer to transfer.',
                'type': 'warning',
                'sticky': False,
            }
        }


class WizardBulkRoundChangeLine(models.TransientModel):
    _name = 'wizard.bulk.round.change.line'
    _description = 'Wizard Bulk Round Change Line'

    wizard_id = fields.Many2one('wizard.bulk.round.change', ondelete='cascade')
    selected = fields.Boolean(string='Selected', default=False)
    partner_id = fields.Many2one('res.partner', string='Customer', required=True)
    
    phone = fields.Char(related='partner_id.phone', string='Phone', store=True, readonly=True)
    city = fields.Char(related='partner_id.city', string='City', store=True, readonly=True)


class WizardBulkRoundSummary(models.TransientModel):
    _name = 'wizard.bulk.round.summary'
    _description = 'Customer Transfer Summary Popup'

    transferred_count = fields.Integer(string='Transferred Customers Count', readonly=True)
    old_round_name = fields.Char(string='Old Round', readonly=True)
    new_round_name = fields.Char(string='New Round', readonly=True)
    message = fields.Text(string='Details', readonly=True)


class BulkRoundChangeWizard(models.TransientModel):
    _name = 'bulk.round.change.wizard'
    _description = 'Bulk Change Round Wizard for Sale Orders'

    round_id = fields.Many2one('round.management.round', string='New Round', required=True)

    def action_apply_round_change(self):
        active_ids = self.env.context.get('active_ids', [])
        if active_ids:
            orders = self.env['sale.order'].browse(active_ids)
            orders.write({'round_id': self.round_id.id})
        return {'type': 'ir.actions.act_window_close'}

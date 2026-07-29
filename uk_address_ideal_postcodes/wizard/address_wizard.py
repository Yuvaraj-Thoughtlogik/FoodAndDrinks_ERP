from odoo import api, fields, models, _
from odoo.exceptions import UserError


class UkAddressLookupWizard(models.TransientModel):
    _name = 'uk.address.lookup.wizard'
    _description = 'UK Address Lookup Wizard'

    partner_id = fields.Many2one('res.partner', string="Partner", required=True)
    postcode = fields.Char(string="Postcode")
    line_ids = fields.One2many('uk.address.lookup.line', 'wizard_id', string="Address Options")
    selected_line_id = fields.Many2one('uk.address.lookup.line', string="Select Address")

    def action_apply_address(self):
        self.ensure_one()
        if not self.selected_line_id:
            raise UserError(_("Please select an address from the options."))

        selected = self.selected_line_id
        uk_country = self.env['res.country'].search([('code', '=', 'GB')], limit=1)
        line2_parts = [p for p in [selected.line_2, selected.line_3] if p]

        self.partner_id.write({
            'street': selected.line_1,
            'street2': ", ".join(line2_parts),
            'city': selected.post_town.title() if selected.post_town else False,
            'zip': selected.postcode,
            'country_id': uk_country.id if uk_country else False,
        })
        return {'type': 'ir.actions.act_window_close'}


class UkAddressLookupLine(models.TransientModel):
    _name = 'uk.address.lookup.line'
    _description = 'UK Address Lookup Line'

    wizard_id = fields.Many2one('uk.address.lookup.wizard', ondelete='cascade')
    name = fields.Char(string="Display Name")
    line_1 = fields.Char(string="Street")
    line_2 = fields.Char(string="Street 2")
    line_3 = fields.Char(string="Street 3")
    post_town = fields.Char(string="City")
    postcode = fields.Char(string="ZIP")

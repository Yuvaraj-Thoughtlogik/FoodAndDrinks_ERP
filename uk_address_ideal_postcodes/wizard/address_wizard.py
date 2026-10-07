import re
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

        raw_line1 = (selected.line_1 or selected.line1 or '').strip()
        
        # Match door/building number at start of string (e.g., "1 Lower Meadows" -> "1" and "Lower Meadows")
        match = re.match(r'^(\d+[a-zA-Z]?)\s+(.*)$', raw_line1)
        
        if match:
            street_val = match.group(1)      # e.g., "1"
            street2_first = match.group(2)   # e.g., "Lower Meadows"
        else:
            street_val = raw_line1
            street2_first = False

        # Gather remaining lines (line2, line3)
        extra_lines = [p for p in [selected.line_2 or getattr(selected, 'line2', False), 
                                   selected.line_3 or getattr(selected, 'line3', False)] if p]
        
        if street2_first:
            extra_lines.insert(0, street2_first)

        self.partner_id.write({
            'street': street_val,
            'street2': ", ".join(extra_lines) if extra_lines else False,
            'city': selected.post_town.title() if hasattr(selected, 'post_town') and selected.post_town else (selected.city.title() if hasattr(selected, 'city') and selected.city else False),
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

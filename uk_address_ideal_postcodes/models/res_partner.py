import urllib.parse
import requests
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class ResPartner(models.Model):
    _inherit = "res.partner"

    lookup_postcode_input = fields.Char(string="Lookup Postcode")

    def action_lookup_uk_address(self):
        """Called when clicking the Lookup Address button."""
        self.ensure_one()
        postcode = (self.lookup_postcode_input or self.zip or "").strip().upper()

        if not postcode:
            raise UserError(_("Please enter a postcode first."))

        api_key = self.env['ir.config_parameter'].sudo().get_param('uk_address.ideal_postcodes_api_key') or \
                  self.env['ir.config_parameter'].sudo().get_param('ideal_postcodes_api_key')

        if not api_key:
            raise UserError(_("Ideal Postcodes API key is missing in System Parameters."))

        encoded_postcode = urllib.parse.quote(postcode)
        url = f"https://api.ideal-postcodes.co.uk/v1/postcodes/{encoded_postcode}"

        try:
            res = requests.get(url, params={'api_key': api_key.strip()}, timeout=5)
            data = res.json()
        except Exception as e:
            raise UserError(_("Failed to connect to Ideal Postcodes: %s") % str(e))

        if res.status_code != 200 or data.get('code') != 2000 or not data.get('result'):
            raise UserError(_("No addresses found for postcode: %s") % postcode)

        addresses = data.get('result', [])

        # Create wizard transient record
        wizard = self.env['uk.address.lookup.wizard'].create({
            'partner_id': self.id,
            'postcode': postcode,
        })

        line_model = self.env['uk.address.lookup.line']
        for addr in addresses:
            line1 = addr.get('line_1', '')
            line2 = addr.get('line_2', '') or ''
            line3 = addr.get('line_3', '') or ''
            city = addr.get('post_town', '')
            pcode = addr.get('postcode', '')

            full_display = f"{line1}, {line2} {city}".replace(', ,', ',').strip(', ')

            line_model.create({
                'wizard_id': wizard.id,
                'name': full_display or line1 or 'Address',
                'line_1': line1,
                'line_2': line2,
                'line_3': line3,
                'post_town': city,
                'postcode': pcode,
            })

        return {
            'name': _("Select Matching Address"),
            'type': 'ir.actions.act_window',
            'res_model': 'uk.address.lookup.wizard',
            'view_mode': 'form',
            'res_id': wizard.id,
            'target': 'new',
        }

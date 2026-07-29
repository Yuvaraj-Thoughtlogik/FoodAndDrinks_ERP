import requests
from odoo import fields, models, _
from odoo.exceptions import UserError

class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    ideal_postcodes_api_key = fields.Char(
        string="Ideal Postcodes API Key",
        config_parameter="uk_address.ideal_postcodes_api_key",
        help="Your API Key starting with ak_ from Ideal Postcodes dashboard."
    )

    def action_test_ideal_postcodes_key(self):
        """Validates API Key against Ideal Postcodes key check endpoint."""
        api_key = self.ideal_postcodes_api_key or self.env['ir.config_parameter'].sudo().get_param('uk_address.ideal_postcodes_api_key')
        if not api_key:
            raise UserError(_("Please provide an API Key before testing."))

        url = f"https://api.ideal-postcodes.co.uk/v1/keys/{api_key}"
        try:
            response = requests.get(url, timeout=5)
            data = response.json()
            if response.status_code == 200 and data.get('code') == 2000:
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': _("Success"),
                        'message': _("Ideal Postcodes API Key is valid! Available lookups check OK."),
                        'type': 'success',
                        'sticky': False,
                    }
                }
            else:
                raise UserError(_("API Key Validation Failed: %s") % data.get('message', 'Invalid Key'))
        except requests.RequestException as e:
            raise UserError(_("Connection Error: %s") % str(e))

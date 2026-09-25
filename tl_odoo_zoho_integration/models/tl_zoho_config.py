import requests, json
from datetime import timedelta
from datetime import date, datetime
from odoo import models, fields, _,api,SUPERUSER_ID
from odoo.exceptions import UserError,ValidationError

import logging
_logger = logging.getLogger(__name__)


def _safe_json(obj):
    """Convert non-serializable objects to serializable form."""
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    elif hasattr(obj, 'id') and hasattr(obj, 'name'):  # likely a recordset
        return {'id': obj.id, 'name': obj.name}
    return str(obj)  # fallback for anything else

class ZohoConfigScope(models.Model):
    _name = 'zoho.config.scope'
    _description = 'Zoho Configuration Scope'

    name = fields.Char(string="Scope",required=True)

class ZohoConfigRegion(models.Model):
    _name = 'zoho.config.region'
    _description = 'Zoho Configuration region'
    _rec_name = 'display_name'
    _rec_names_search = 'display_name'


    display_name = fields.Char(string="Name",compute="_compute_display_name")
    name = fields.Char(string="Region / Data Center",required=True)
    base_url = fields.Char(string='API Base URL',required=True)
    account_url = fields.Char(string="Auth url")

    @api.depends('name','base_url')
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = f"{rec.name} - {rec.base_url}"


class ZohoConfig(models.Model):
    _name = 'zoho.config'
    _description = 'Zoho Configuration'
    _rec_name='cr_name'

    cr_name = fields.Char(string="Configuration Name", required=True, default="Zoho OAuth",readonly=True)
    cr_client_id = fields.Char(string="Client ID")
    cr_client_secret = fields.Char(string="Client Secret")
    cr_redirect_uri = fields.Char(
        string="Redirect URI",
        required=True,
        default=lambda self: (
            (url + "/zoho/auth") if (url := self.env['ir.config_parameter'].sudo().get_param('web.base.url')) else ''
        )
    )
    cr_access_token = fields.Text(string="Access Token" )
    cr_refresh_token = fields.Text(string="Refresh Token")
    cr_token_expiry = fields.Datetime(string="Token Expiry" )

    scope_ids = fields.Many2many(
        comodel_name='zoho.config.scope',
    )
    config_region_id = fields.Many2one(comodel_name='zoho.config.region',string="Region / Data Center")

    api_domain = fields.Char(related='config_region_id.base_url',store=True)

    zoho_app_ids = fields.Many2many(comodel_name='zoho.config.application',string="Active Zoho Applications")

    regenerate_required = fields.Boolean(string="Regenerate Required")

    addon_ids = fields.Many2many(comodel_name='ir.module.module',name='Applications',compute='compute_addon_ids')

    def write(self, vals):
        if any(field in vals for field in ('scope_ids', 'config_region_id')):
            vals['regenerate_required'] = True
        return super().write(vals)

    @api.depends('scope_ids', 'regenerate_required', 'cr_name')
    def compute_addon_ids(self):
        sub_addons = self.env['ir.module.module'].search(
            [('dependencies_id.name', '=', 'tl_odoo_zoho_integration')])

        for rec in self:
            # Step 4: Ensure applications exist
            for addon in sub_addons:
                application = self.env['zoho.config.application'].search(
                    [('addon_id', '=', addon.id)], limit=1
                )
                if not application:
                    self.env['zoho.config.application'].create({
                        'name': str(addon.shortdesc).replace('Connector', '').strip(),
                        'addon_name': addon.name,
                        'addon_id': addon.id,
                    })

            # Step 5: Set addon_ids for this record
            rec.addon_ids = sub_addons

    @api.model
    def open_first_record(self):
        record = self.env['zoho.config'].search([], limit=1)
        if record:
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'zoho.config',
                'res_id': record.id,
                'view_mode': 'form',
                'target': 'current',
            }
        else:
            # If no record exists, return a new form view
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'zoho.config',
                'view_mode': 'form',
                'views': [(False, 'form')],
                'target': 'current',
            }

    def open_menu(self):
        self.generate_zoho_application()
        menu_id = self.env.ref("tl_odoo_zoho_integration.menu_zoho_application").id
        return {
            'type': 'ir.actions.act_url',
            'url': f'/web#menu_id={menu_id}',
            'target': 'self',
        }

    # def open_action(self,compute_need=True):
    #     self.generate_zoho_application()
    #     action_id = self.env.ref("tl_odoo_zoho_integration.action_zoho_config_application").id
    #     return {
    #         'type': 'ir.actions.act_url',
    #         'url': f'/web#action={action_id}',
    #         'target': 'self',
    #     }

    # def update_app_list(self,compute_need=True):
    #     self.generate_zoho_application()
    #     menu_id = self.env.ref("tl_odoo_zoho_integration.menu_zoho_application").id
    #     return {
    #         'type': 'ir.actions.act_url',
    #         'url': f'/web#menu_id={menu_id}',
    #         'target': 'self',
    #     }

    def generate_zoho_application(self):
        self.env['zoho.config.application'].generate_zoho_application()


    def action_open_after_install(self):
        menu_id = self.env.ref("tl_odoo_zoho_integration.menu_zoho_configuration").id
        return {
            'type': 'ir.actions.act_url',
            'url': f'/web#menu_id={menu_id}',
            'target': 'self',
        }

    def generate_auth_url(self):
        """Generate the authorization URL to get the grant token."""
        self.ensure_one()
        if not self.cr_client_id or not self.cr_client_secret or not self.config_region_id:
            raise ValidationError(
                "Please configure Zoho credentials properly. "
                "Client ID, Client Secret, and Region are required."
            )

        # auth_url = "https://accounts.zoho.eu/oauth/v2/auth"
        auth_url = f"{self.config_region_id.account_url}/oauth/v2/auth"
        scope = ','.join([scope.name for scope in self.scope_ids])
        params = {
            "scope": scope,
            "client_id": self.cr_client_id,
            "prompt": "consent",
            "response_type": "code",
            "access_type": "offline",
            "redirect_uri": self.cr_redirect_uri,
        }
        url= f"{auth_url}?{requests.compat.urlencode(params)}"
        return {
            "type": "ir.actions.act_url",
            "url": url,
            "target": "self",
        }

    def exchange_grant_token(self, grant_token):
        """Exchange grant token for access and refresh tokens."""
        # token_url = "https://accounts.zoho.eu/oauth/v2/token"
        token_url = f"{self.config_region_id.account_url}/oauth/v2/token"
        payload = {
            "grant_type": "authorization_code",
            "client_id": self.cr_client_id,
            "client_secret": self.cr_client_secret,
            "redirect_uri": self.cr_redirect_uri,
            "code": grant_token,
        }
        try:
            response = requests.post(token_url, data=payload)
            response.raise_for_status()
            tokens = response.json()
            # print(tokens)
            self.write({
                'cr_access_token': tokens.get('access_token'),
                'cr_refresh_token': tokens.get('refresh_token'),
                'cr_token_expiry': fields.Datetime.now() + timedelta(seconds=tokens.get('expires_in', 3600)),
            })
        except requests.RequestException as e:
            raise UserError(_("Error exchanging grant token: %s") % e)

    def refresh_access_token(self):
        """Refresh the access token using the refresh token."""
        self.ensure_one()
        # token_url = "https://accounts.zoho.eu/oauth/v2/token"
        token_url = f"{self.config_region_id.account_url}/oauth/v2/token"
        payload = {
            "grant_type": "refresh_token",
            "client_id": self.cr_client_id,
            "client_secret": self.cr_client_secret,
            "refresh_token": self.cr_refresh_token,
        }
        try:
            response = requests.post(token_url, data=payload)
            response.raise_for_status()
            tokens = response.json()
            # print(tokens)
            self.write({
                'cr_access_token': tokens.get('access_token'),
                'cr_token_expiry': fields.Datetime.now() + timedelta(seconds=tokens.get('expires_in', 3600)),
            })
        except requests.RequestException as e:
            raise UserError(_("Error refreshing access token: %s") % e)
    
    def fetch_zoho_fields(self,module):
        """
        Fetch available fields for the Contacts module from Zoho CRM.
        """
        # print('called')
        fields_url = "https://www.zohoapis.eu/crm/v7/settings/fields"
        params = {"module": module}
        headers = {"Authorization": f"Zoho-oauthtoken {self.cr_access_token}"}

        try:
            response = requests.get(fields_url, headers=headers, params=params)

            data = response.json()

            if 'fields' in data:
                field_names = [field['api_name'] for field in data['fields']]
                # print(f"Fetched fields: {field_names}")
                return field_names
            else:
                raise UserError(_("No fields data found in Zoho response."))

        except requests.RequestException as e:
            raise UserError(_("Error fetching Zoho fields: %s") % e)

    def _get_zoho_api_url(self, endpoint):
        """Helper method to build the Zoho API URL."""
        base_url = "https://www.zohoapis.eu/crm/v2"
        return f"{base_url}/{endpoint}"

    def _check_access_token(self):
        """Ensure the access token is valid, refreshing it if necessary."""
        if not self.cr_access_token or fields.Datetime.now() >= self.cr_token_expiry:
            self.refresh_access_token()

    def check_ready_to_sync(self):
        config = self.env['zoho.config'].search([], limit=1)
        if not config or not config.cr_access_token:
            raise UserError("Zoho OAuth configuration or access token is missing. Please generate your credentials.")
        if config.regenerate_required:
            raise UserError(
                "Region or scopes have changed. New authorization is required. Please regenerate your credentials.")

        return True

    def print_test(self):
        # Create settings with the group flag
        settings = self.env['res.config.settings'].sudo().create({'group_use_lead': True})
        # Apply changes: different methods across versions
        if hasattr(settings, 'execute'):
            settings.execute()
        elif hasattr(settings, 'set_values'):
            settings.set_values()
        # Optional: still store the parameter (not enough by itself)
        self.env['ir.config_parameter'].sudo().set_param('crm.use_leads', True)
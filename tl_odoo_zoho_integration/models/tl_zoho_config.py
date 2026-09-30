import logging
from datetime import timedelta
from urllib.parse import urlencode

import requests

from odoo import models, fields, _, api
from odoo.exceptions import UserError, ValidationError

from ..utils import ZOHO_TIMEOUT

_logger = logging.getLogger(__name__)


class ZohoConfigScope(models.Model):
    _name = 'zoho.config.scope'
    _description = 'Zoho Configuration Scope'

    name = fields.Char(string="Scope", required=True)


class ZohoConfigRegion(models.Model):
    _name = 'zoho.config.region'
    _description = 'Zoho Configuration region'
    _rec_names_search = ['name', 'base_url']

    name = fields.Char(string="Region / Data Center", required=True)
    base_url = fields.Char(string='API Base URL', required=True)
    account_url = fields.Char(string="Auth url")

    @api.depends('name', 'base_url')
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = f"{rec.name} - {rec.base_url}"


class ZohoConfig(models.Model):
    _name = 'zoho.config'
    _description = 'Zoho Configuration'
    _rec_name = 'cr_name'

    cr_name = fields.Char(string="Configuration Name", required=True, default="Zoho OAuth", readonly=True)
    cr_client_id = fields.Char(string="Client ID")
    cr_client_secret = fields.Char(string="Client Secret")
    cr_redirect_uri = fields.Char(
        string="Redirect URI",
        required=True,
        default=lambda self: (
            (url + "/zoho/auth") if (url := self.env['ir.config_parameter'].sudo().get_param('web.base.url')) else ''
        )
    )
    cr_access_token = fields.Text(string="Access Token")
    cr_refresh_token = fields.Text(string="Refresh Token")
    cr_token_expiry = fields.Datetime(string="Token Expiry")

    scope_ids = fields.Many2many(comodel_name='zoho.config.scope')
    config_region_id = fields.Many2one(comodel_name='zoho.config.region', string="Region / Data Center")
    api_domain = fields.Char(related='config_region_id.base_url', store=True)
    zoho_app_ids = fields.Many2many(comodel_name='zoho.config.application', string="Active Zoho Applications")
    regenerate_required = fields.Boolean(string="Regenerate Required")
    notify_base_url = fields.Char(
        string="Public URL (Notifications)",
        help="Public HTTPS address of this Odoo (e.g. https://erp.example.com), used by Zoho to send "
             "instant change notifications for 'Live' sync. Leave empty when Odoo is not reachable from "
             "the internet: Zoho is then checked for changes periodically instead.")
    addon_ids = fields.Many2many(comodel_name='ir.module.module', string='Applications', compute='compute_addon_ids')

    def write(self, vals):
        if any(field in vals for field in ('scope_ids', 'config_region_id')):
            vals['regenerate_required'] = True
        return super().write(vals)

    @api.depends('scope_ids', 'regenerate_required', 'cr_name')
    def compute_addon_ids(self):
        Application = self.env['zoho.config.application']
        # Opening the configuration also registers newly available connector addons.
        Application.generate_zoho_application()
        sub_addons = Application._get_zoho_sub_addons()
        for rec in self:
            rec.addon_ids = sub_addons

    @api.model
    def open_first_record(self):
        action = {
            'type': 'ir.actions.act_window',
            'res_model': 'zoho.config',
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'current',
        }
        if record := self.search([], limit=1):
            action['res_id'] = record.id
        return action

    def _action_open_menu(self, xmlid):
        menu_id = self.env.ref(xmlid).id
        return {
            'type': 'ir.actions.act_url',
            'url': f'/web#menu_id={menu_id}',
            'target': 'self',
        }

    def open_menu(self):
        self.generate_zoho_application()
        return self._action_open_menu("tl_odoo_zoho_integration.menu_zoho_application")

    def generate_zoho_application(self):
        self.env['zoho.config.application'].generate_zoho_application()

    def action_open_after_install(self):
        return self._action_open_menu("tl_odoo_zoho_integration.menu_zoho_configuration")

    # ------------------------------------------------------------------
    # OAuth
    # ------------------------------------------------------------------
    def generate_auth_url(self):
        """Generate the authorization URL to get the grant token."""
        self.ensure_one()
        if not self.cr_client_id or not self.cr_client_secret or not self.config_region_id:
            raise ValidationError(_(
                "Please configure Zoho credentials properly. "
                "Client ID, Client Secret, and Region are required."
            ))
        params = {
            "scope": ','.join(self.scope_ids.mapped('name')),
            "client_id": self.cr_client_id,
            "prompt": "consent",
            "response_type": "code",
            "access_type": "offline",
            "redirect_uri": self.cr_redirect_uri,
        }
        return {
            "type": "ir.actions.act_url",
            "url": f"{self.config_region_id.account_url}/oauth/v2/auth?{urlencode(params)}",
            "target": "self",
        }

    def _request_tokens(self, payload, error_label):
        """POST ``payload`` to the Zoho token endpoint and return the token dict."""
        self.ensure_one()
        payload = dict(payload, client_id=self.cr_client_id, client_secret=self.cr_client_secret)
        try:
            response = requests.post(
                f"{self.config_region_id.account_url}/oauth/v2/token", data=payload, timeout=ZOHO_TIMEOUT)
            response.raise_for_status()
            tokens = response.json()
        except (requests.RequestException, ValueError) as e:
            raise UserError(_("%(label)s: %(error)s", label=error_label, error=e)) from e
        # Zoho answers 200 with {"error": "..."} on invalid codes / refresh tokens.
        if not tokens.get('access_token'):
            raise UserError(_("%(label)s: %(error)s", label=error_label, error=tokens.get('error', tokens)))
        return tokens

    def exchange_grant_token(self, grant_token):
        """Exchange grant token for access and refresh tokens."""
        tokens = self._request_tokens({
            "grant_type": "authorization_code",
            "redirect_uri": self.cr_redirect_uri,
            "code": grant_token,
        }, _("Error exchanging grant token"))
        self.write({
            'cr_access_token': tokens['access_token'],
            'cr_refresh_token': tokens.get('refresh_token') or self.cr_refresh_token,
            'cr_token_expiry': fields.Datetime.now() + timedelta(seconds=tokens.get('expires_in', 3600)),
        })

    def refresh_access_token(self):
        """Refresh the access token using the refresh token."""
        tokens = self._request_tokens({
            "grant_type": "refresh_token",
            "refresh_token": self.cr_refresh_token,
        }, _("Error refreshing access token"))
        self.write({
            'cr_access_token': tokens['access_token'],
            'cr_token_expiry': fields.Datetime.now() + timedelta(seconds=tokens.get('expires_in', 3600)),
        })

    # ------------------------------------------------------------------
    # API helpers
    # ------------------------------------------------------------------
    @api.model
    def _get_ready_config(self):
        """Return the Zoho configuration, raising if it cannot be used to sync."""
        config = self.search([], limit=1)
        if not config or not config.cr_access_token:
            raise UserError(_("Zoho OAuth configuration or access token is missing. Please generate your credentials."))
        if config.regenerate_required:
            raise UserError(_(
                "Region or scopes have changed. New authorization is required. Please regenerate your credentials."))
        return config

    def _get_notify_url(self):
        """URL Zoho posts change notifications to, or False when notifications cannot be used."""
        self.ensure_one()
        base_url = (self.notify_base_url or '').strip().rstrip('/')
        return f"{base_url}/zoho/notify" if base_url.startswith('https://') else False

    @api.constrains('notify_base_url')
    def _check_notify_base_url(self):
        for rec in self:
            if rec.notify_base_url and not rec.notify_base_url.strip().startswith('https://'):
                raise ValidationError(_("The public URL for Zoho notifications must start with https://"))

    def check_ready_to_sync(self):
        self._get_ready_config()
        return True

    def zoho_request(self, method, path, retry=True, **kwargs):
        """Call the Zoho API (``path`` is relative to the region's API domain).

        Adds the OAuth header and a timeout, and refreshes the access token
        once when Zoho answers 401. Returns the ``requests.Response``.
        """
        self.ensure_one()
        if self.cr_token_expiry and fields.Datetime.now() >= self.cr_token_expiry and self.cr_refresh_token:
            self.refresh_access_token()
        headers = dict(kwargs.pop('headers', None) or {}, Authorization=f'Zoho-oauthtoken {self.cr_access_token}')
        kwargs.setdefault('timeout', ZOHO_TIMEOUT)
        response = requests.request(method, f"{self.api_domain}/{path.lstrip('/')}", headers=headers, **kwargs)
        if response.status_code == 401 and retry:
            self.refresh_access_token()
            return self.zoho_request(method, path, retry=False, headers=headers, **kwargs)
        return response

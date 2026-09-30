import json

from odoo import http
from odoo.http import request

class ZohoController(http.Controller):

    @http.route('/zoho/auth', type='http', auth='user', csrf=False)
    def zoho_auth(self, **kwargs):
        grant_token = kwargs.get('code')
        if not grant_token:
            return "Authorization failed: Grant token not found."

        zoho_config = request.env['zoho.config'].sudo().search([], limit=1)
        if not zoho_config:
            return "Zoho Configuration not found."

        menu_id = request.env.ref("tl_odoo_zoho_integration.menu_zoho_application").id
        redirect_url = f"/web#menu_id={menu_id}"

        try:
            zoho_config.exchange_grant_token(grant_token)
            zoho_config.regenerate_required = False
            return request.render(
                'tl_odoo_zoho_integration.success_redirect_template',
                {'redirect_url': redirect_url}
            )
        except Exception as e:
            return f"Authorization failed: {str(e)}"

    @http.route('/zoho/notify', type='http', auth='public', methods=['POST'], csrf=False, save_session=False)
    def zoho_notify(self, **kwargs):
        """Zoho CRM notification endpoint: queue the changed records and answer at once,
        the records themselves are fetched from Zoho by the live sync cron."""
        try:
            payload = json.loads(request.httprequest.get_data() or b'{}')
        except ValueError:
            return request.make_response('Invalid payload', status=400)
        if not isinstance(payload, dict) or not request.env['zoho.live.queue'].sudo()._receive_notification(payload):
            return request.make_response('Unknown channel', status=403)
        return request.make_response('OK')

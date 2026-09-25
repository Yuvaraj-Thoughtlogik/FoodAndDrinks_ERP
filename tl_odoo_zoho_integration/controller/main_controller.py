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

from odoo import models, api

# Scopes needed by the CRM connector on top of the ones chosen at install (see data/base_data.xml).
REQUIRED_SCOPE_XMLIDS = [
    'tl_zoho_crm_integration.zoho_scope_zohocrm_notifications_all',  # Live sync: Zoho -> Odoo notifications
]
NOTIFICATIONS_SCOPE = 'ZohoCRM.notifications.ALL'


class ZohoConfig(models.Model):
    _inherit = 'zoho.config'

    @api.model
    def _ensure_crm_scopes(self):
        """Add missing required scopes; ``write`` then flags the credentials for regeneration."""
        scopes = self.env['zoho.config.scope'].browse(
            [scope.id for xmlid in REQUIRED_SCOPE_XMLIDS if (scope := self.env.ref(xmlid, raise_if_not_found=False))])
        for config in self.search([]):
            if missing := scopes - config.scope_ids:
                config.scope_ids = [(4, scope.id) for scope in missing]

import json

from odoo import models

from odoo.addons.tl_odoo_zoho_integration.utils import safe_json, slugify


class SyncTestCase(models.TransientModel):
    _inherit = "zoho.config.testcase.wizard"

    def action_confirm(self):
        self.ensure_one()
        module = self.config_module_id
        if module.zoho_config_app_id.addon_name == 'tl_zoho_crm_integration':
            def dump(result, key):
                return json.dumps({
                    'odoo_module': module.odoo_model_name,
                    'zoho_module': module.name,
                    'data': result.get(key, {}),
                }, indent=2, default=safe_json)

            if self.one_way:
                result = module.sync_zoho_to_odoo(for_test=self.zoho_record)
                self.one_way_request = dump(result, 'request')
                self.one_way_response = dump(result, 'response')
            if self.two_way:
                # Dynamic many2one created on this wizard by zoho.config.module.create()
                test_field = module.test_case_field_id.name or (
                    f"x_{slugify(module.zoho_config_app_id.name)}_testcase_"
                    f"{module.odoo_model.model.strip().replace('.', '_').lower()}_id")
                # The field is required in the view; never fall back to syncing every record.
                result = module.sync_odoo_to_zoho(for_test=self[test_field].id or -1)
                self.two_way_request = dump(result, 'request')
                self.two_way_response = dump(result, 'response')
        return super().action_confirm()

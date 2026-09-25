from odoo import models, fields, api, _
import json
from datetime import date, datetime
import logging

_logger = logging.getLogger(__name__)


def _safe_json(obj):
    """Convert non-serializable objects to serializable form."""
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    elif hasattr(obj, 'id') and hasattr(obj, 'name'):  # likely a recordset
        return {'id': obj.id, 'name': obj.name}
    return str(obj)  # fallback for anything else


class SyncTestCase(models.TransientModel):
    _inherit = "zoho.config.testcase.wizard"


    def _format_sync_summary(self, result, model=None):
        lines = [f"🔁 Zoho ↔ Odoo Sync Summary for model '{model}':"]

        created = result.get("created", [])
        updated = result.get("updated", [])
        errors = result.get("errors", [])

        if created:
            lines.append(f"\nCreated {len(created)} record(s):\n")
            for i, entry in enumerate(created, 1):
                lines.append(f"  {i}- Odoo ID: {entry.get('record_id')} ← Zoho ID: {entry.get('zoho_id')}")

        if updated:
            lines.append(f"\n♻Updated {len(updated)} record(s):\n")
            for i, entry in enumerate(updated, 1):
                lines.append(f"  {i}- Zoho ID: {entry.get('zoho_id')}")

        if errors:
            lines.append(f"\n Errors ({len(errors)}):\n")
            for entry in errors:
                lines.append(f"Error: {entry}")

        return "\n".join(lines)

    def action_confirm(self):
        self.ensure_one()
        addon_name = self.config_module_id.zoho_config_app_id.addon_name
        if addon_name and addon_name == 'tl_zoho_crm_integration':
            if self.one_way:
                result_zoho_to_odoo = self.config_module_id.sync_zoho_to_odoo(for_test=self.zoho_record)
                _one_way_request = {'odoo_module':self.config_module_id.odoo_model_name,'zoho_module':self.config_module_id.name,'data':result_zoho_to_odoo.get("request", {})}
                self.one_way_request = json.dumps(_one_way_request, indent=2, default=_safe_json)
                _one_way_response = {'odoo_module':self.config_module_id.odoo_model_name,'zoho_module':self.config_module_id.name,'data':result_zoho_to_odoo.get("response", {})}
                self.one_way_response = json.dumps(_one_way_response, indent=2, default=_safe_json)
            if self.two_way:
                model_name_safe = self.config_module_id.odoo_model.model.strip().replace('.', '_').lower()
                zoho_app_name = self.config_module_id.zoho_config_app_id.name.strip().replace(' ', '_').lower()
                field_name = f'x_{zoho_app_name}_testcase_{model_name_safe}_id'
                print(field_name,self[field_name].id)

                result_odoo_to_zoho = self.config_module_id.sync_odoo_to_zoho(for_test= self[field_name].id)

                _two_way_request = {'odoo_module':self.config_module_id.odoo_model_name,'zoho_module':self.config_module_id.name,'data':result_odoo_to_zoho.get("request", {})}
                self.two_way_request = json.dumps(_two_way_request, indent=2, default=_safe_json)
                _two_way_response = {'odoo_module':self.config_module_id.odoo_model_name,'zoho_module':self.config_module_id.name,'data':result_odoo_to_zoho.get("response", {})}
                self.two_way_response = json.dumps(_two_way_response, indent=2, default=_safe_json)
        return super().action_confirm()


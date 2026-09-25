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
    _name = "zoho.config.testcase.wizard"
    _description = "Config Test Cases for Zoho to Odoo sync"

    test_type = fields.Selection([
        ('one_way', "One Way Sync"),
        ('two_way', 'Two Way Sync')
    ], string="Test Type", required=True, default='one_way')
    one_way = fields.Boolean(string='One way',default=True)
    two_way = fields.Boolean(string='Two way')
    config_module_id = fields.Many2one(
        string="Module", comodel_name="zoho.config.module"
    )
    zoho_app_name = fields.Char(string="Zoho App Name",related='config_module_id.zoho_config_app_id.name')
    zoho_record = fields.Char(string="Zoho Record ID")
    odoo_model = fields.Char(related="config_module_id.odoo_model_name", string="Odoo Model")
    odoo_record_test = fields.Integer(string="Odoo Record ID")

    one_way_request = fields.Text(string="Request")
    one_way_response = fields.Text(string="Response")
    two_way_request = fields.Text(string="Request")
    two_way_response = fields.Text(string="Response")

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
        return {
            'name': 'Zoho Sync Response',
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',

        }


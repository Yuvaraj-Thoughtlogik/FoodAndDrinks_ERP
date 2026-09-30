import json
import logging

from odoo import models, fields, api
from odoo.exceptions import ValidationError, UserError

from odoo.addons.tl_odoo_zoho_integration.utils import safe_json

_logger = logging.getLogger(__name__)

FREQUENCY_MAP = {
    '1_hour': {'interval_number': 1, 'interval_type': 'hours'},
    '2_hour': {'interval_number': 2, 'interval_type': 'hours'},
    'once_a_day': {'interval_number': 1, 'interval_type': 'days'},
}


class ZohoConfigSchedule(models.Model):
    _inherit = 'zoho.config.schedule'

    def sync_crm_from_cron(self):
        module = self.module_id
        module_name = module.name
        odoo_name = module.odoo_model_name
        request, response = {'one_way': {}, 'two_way': {}}, {'one_way': {}, 'two_way': {}}
        counts = {
            direction: {'created': 0, 'updated': 0, 'unchanged': 0, 'failed': 0}
            for direction in ('one_way', 'two_way')
        }
        message = {'success': [], 'error': []}
        statuses = []

        directions = []
        if self.zoho_to_odoo:
            directions.append(('one_way', 'one_way_last_sync', module.sync_zoho_to_odoo,
                               f"[Zoho {module_name} → Odoo {odoo_name}]"))
        if self.odoo_to_zoho:
            directions.append(('two_way', 'two_way_last_sync', module.sync_odoo_to_zoho,
                               f"[Odoo {odoo_name} -> Zoho {module_name}]"))

        for direction, last_sync_field, sync_method, label in directions:
            started_at = fields.Datetime.now()
            result = sync_method(last_sync=self[last_sync_field])
            self[last_sync_field] = started_at
            request[direction] = {'odoo_module': odoo_name, 'zoho_module': module_name,
                                  'data': result.get("request", {})}
            response[direction] = {'odoo_module': odoo_name, 'zoho_module': module_name,
                                   'data': result.get("response", {})}
            status = result.get("status", 'failed')
            statuses.append(status)
            if status == 'success':
                message['success'].append(f"{label} Synced successfully.")
                result_response = result.get('response', {})
                counts[direction].update({
                    'created': len(result_response.get('created', [])),
                    'updated': len(result_response.get('updated', [])),
                    'unchanged': len(result_response.get('unchanged', [])),
                    'failed': len(result_response.get('errors', [])),
                })
            else:
                message['error'].append(f"{label} Synced Failed.")

        failed = statuses.count('failed')
        status = 'failed' if statuses and failed == len(statuses) else 'partial' if failed else 'success'

        def dump(value):
            return json.dumps(value, indent=2, default=safe_json)

        self.create_log(
            modules=module_name,
            status=status,
            request={direction: dump(value) for direction, value in request.items()},
            response={direction: dump(value) for direction, value in response.items()},
            odoo_ids=dump(counts['one_way']),
            zoho_ids=dump(counts['two_way']),
            message=message
        )
        self.last_sync = fields.Datetime.now()

    @api.model
    def run_crm_sync_by_cron(self, schedule_id):
        schedule = self.browse(schedule_id)
        if not schedule.exists():
            _logger.warning("Zoho Config ID %s not found", schedule_id)
            return
        _logger.info("Running Zoho sync via scheduled action for %s", schedule.name)
        schedule.sync_crm_from_cron()

    def create_crm_scheduled_action(self):
        self.ensure_one()
        if self.sync_frequency not in FREQUENCY_MAP:
            raise ValidationError(f"Invalid sync frequency: {self.sync_frequency}")

        model = self.env['ir.model']._get('zoho.config.schedule')
        if not model:
            raise UserError("Model 'zoho.config.schedule' not found")

        cron_vals = {
            'name': self.name,
            'model_id': model.id,
            'state': 'code',
            'code': f'model.run_crm_sync_by_cron({self.id!r})',
            'active': True,
            **FREQUENCY_MAP[self.sync_frequency],
        }
        if self.cron_id:
            self.cron_id.sudo().write(cron_vals)
        else:
            self.cron_id = self.env['ir.cron'].sudo().create([cron_vals])

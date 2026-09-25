from odoo import models,fields,api
import json
from datetime import datetime ,date
from odoo.exceptions import ValidationError,UserError

import logging
_logger = logging.getLogger(__name__)


def _safe_json(obj):
    """Convert non-serializable objects to serializable form."""
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    elif hasattr(obj, 'id') and hasattr(obj, 'name'):  # likely a recordset
        return {'id': obj.id, 'name': obj.name}
    return str(obj)  # fallback for anything else


class ZohoConfigSchedule(models.Model):
    _inherit = 'zoho.config.schedule'

    def sync_crm_from_cron(self):
        request, response = {'one_way': {}, 'two_way': {}}, {'one_way': {}, 'two_way': {}}
        odoo_ids, zoho_ids = {'created': 0, 'updated': 0,'unchanged':0,'failed':0}, {'created': 0, 'updated': 0,'unchanged':0,'failed':0}
        message, modules_synced = {'success': [], 'error': []}, []
        one_way_status = []
        two_way_status = []
        module_name = self.module_id.name
        modules_synced.append(module_name)
        if self.zoho_to_odoo:
            result_zoho_to_odoo = self.module_id.sync_zoho_to_odoo(last_sync=self.one_way_last_sync)
            self.one_way_last_sync = datetime.now()
            # print("result,",result_zoho_to_odoo)
            request['one_way'] = {'odoo_module':self.module_id.odoo_model_name,'zoho_module':module_name,'data':result_zoho_to_odoo.get("request", {})}
            response['one_way'] = {'odoo_module':self.module_id.odoo_model_name,'zoho_module':module_name,'data':result_zoho_to_odoo.get("response", {})}

            one_way_status = result_zoho_to_odoo.get("status",'failed')
            if result_zoho_to_odoo.get("status",'failed') == 'success':
                message['success'].append(f"[Zoho {module_name} → Odoo {self.module_id.odoo_model_name}] Synced successfully.")
                odoo_ids['created'] = len(result_zoho_to_odoo['response'].get('created', []))

                odoo_ids['updated'] = len(result_zoho_to_odoo['response'].get('updated', []))

                odoo_ids['unchanged'] = len(result_zoho_to_odoo['response'].get('unchanged', []))

                odoo_ids['failed'] = len(result_zoho_to_odoo['response'].get('error', []))

            else:
                message['error'].append(f"[Zoho {module_name} → Odoo {self.module_id.odoo_model_name}] Synced Failed.")

            # === Odoo → Zoho Sync ===

        if self.odoo_to_zoho:
            result_odoo_to_zoho = self.module_id.sync_odoo_to_zoho(last_sync=self.one_way_last_sync)
            request['two_way'] = {'odoo_module':self.module_id.odoo_model_name,'zoho_module':module_name,'data': result_odoo_to_zoho.get("request", {})}
            response['two_way'] = {'odoo_module':self.module_id.odoo_model_name,'zoho_module':module_name,'data':result_odoo_to_zoho.get("response", {})}
            two_way_status = result_odoo_to_zoho.get("status", 'failed')
            if result_odoo_to_zoho.get("status", 'failed') == 'failed':
                zoho_ids['created'] = len(result_odoo_to_zoho['response'].get('created', []))

                zoho_ids['updated'] = len(result_odoo_to_zoho['response'].get('updated', []))

                zoho_ids['unchanged'] = len(result_odoo_to_zoho['response'].get('unchanged', []))

                zoho_ids['failed'] = len(result_odoo_to_zoho['response'].get('error', []))

                message['success'].append(
                    f"[Odoo {self.module_id.odoo_model_name} -> Zoho {module_name}] Synced successfully.")
            else:
                message['error'].append(
                    f"[Odoo {self.module_id.odoo_model_name} -> Zoho {module_name}] Synced Failed.")

        # === Final Log Creation ===
        _one_way_status = one_way_status == 'failed'
        _two_way_status = two_way_status == 'failed'
        status = (
            'failed' if _one_way_status and _two_way_status
            else 'partial' if _one_way_status or _two_way_status
            else 'success'
        )
        self.create_log(
            modules=', '.join(modules_synced),
            status = status,
            request={
                'one_way': json.dumps(request['one_way'], indent=2, default=_safe_json),
                'two_way': json.dumps(request['two_way'], indent=2, default=_safe_json),
            },
            response={
                'one_way': json.dumps(response['one_way'], indent=2, default=_safe_json),
                'two_way': json.dumps(response['two_way'], indent=2, default=_safe_json),
            },
            odoo_ids = json.dumps(odoo_ids, indent=2, default=_safe_json),
            #     'created': json.dumps(odoo_ids['created'], indent=2, default=_safe_json),
            #     'updated': json.dumps(odoo_ids['updated'], indent=2, default=_safe_json),
            #     'failed': json.dumps(odoo_ids['failed'], indent=2, default=_safe_json),
            # },
            zoho_ids = json.dumps(zoho_ids, indent=2, default=_safe_json),
            #     'created': json.dumps(zoho_ids['created'], indent=2, default=_safe_json),
            #     'updated': json.dumps(zoho_ids['updated'], indent=2, default=_safe_json),
            #     'failed': json.dumps(zoho_ids['failed'], indent=2, default=_safe_json),
            # },
            message=message
        )
        self.last_sync = datetime.now()


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

        model = self.env['ir.model'].search([('model', '=', 'zoho.config.schedule')], limit=1)
        if not model:
            raise UserError("Model 'zoho.config.schedule' not found")

        frequency_map = {
            '1_hour': {'interval_number': 1, 'interval_type': 'hours'},
            '2_hour': {'interval_number': 2, 'interval_type': 'hours'},
            'once_a_day': {'interval_number': 1, 'interval_type': 'days'},
        }

        if self.sync_frequency not in frequency_map:
            raise ValidationError(f"Invalid sync frequency: {self.sync_frequency}")

        freq = frequency_map[self.sync_frequency]
        cron_map = {
            'name': self.name,
            'model_id': model.id,
            'state': 'code',
            'code': f'model.run_crm_sync_by_cron({repr(self.id)})',
            'interval_number': freq['interval_number'],
            'interval_type': freq['interval_type'],
            'active': True,
        }
        if self.cron_id:
            cron = self.env['ir.cron'].sudo().write(cron_map)
        else:
            cron = self.env['ir.cron'].sudo().create([cron_map])
            self.cron_id = cron.id



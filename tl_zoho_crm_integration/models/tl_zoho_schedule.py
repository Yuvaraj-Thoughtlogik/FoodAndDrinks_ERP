import json
import logging
import secrets
from datetime import timedelta

from odoo import models, fields, api, Command
from odoo.exceptions import ValidationError, UserError

from odoo.addons.tl_odoo_zoho_integration.utils import safe_json

_logger = logging.getLogger(__name__)

FREQUENCY_MAP = {
    '1_hour': {'interval_number': 1, 'interval_type': 'hours'},
    '2_hour': {'interval_number': 2, 'interval_type': 'hours'},
    'once_a_day': {'interval_number': 1, 'interval_type': 'days'},
}
# Zoho notification channels last at most one week; they are renewed before they expire.
NOTIFY_CHANNEL_DAYS = 6
NOTIFY_RENEW_BEFORE = timedelta(days=2)


class ZohoConfigSchedule(models.Model):
    _inherit = 'zoho.config.schedule'

    automation_id = fields.Many2one(comodel_name='base.automation', string='Live Automation Rule')

    def unlink(self):
        automations = self.automation_id
        for schedule in self.filtered('notify_channel_id'):
            try:
                schedule._disable_live_notification()
            except Exception:
                _logger.warning("[ZOHO NOTIFY] Could not disable channel of %s", schedule.name, exc_info=True)
        res = super().unlink()
        automations.sudo().unlink()
        return res

    def sync_crm_from_cron(self, include_push=True):
        """:param include_push: also push Odoo -> Zoho (False for 'Live' schedules, whose pushes are queued)"""
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
        if self.odoo_to_zoho and include_push:
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
        schedule.sync_crm_from_cron(include_push=schedule.sync_frequency != 'live')

    def _live_push(self, record_ids):
        return self.module_id.sync_odoo_to_zoho(record_ids=record_ids)

    def _live_pull(self, zoho_ids):
        return self.module_id.sync_zoho_to_odoo(zoho_ids=zoho_ids)

    def create_crm_scheduled_action(self):
        self.ensure_one()
        live = self.sync_frequency == 'live'
        if live:
            # Periodic check of Zoho: the only Zoho -> Odoo path without notifications, a safety net with them.
            frequency = {'interval_number': int(self.zoho_config_app_id.live_pull_interval), 'interval_type': 'minutes'}
        elif self.sync_frequency in FREQUENCY_MAP:
            frequency = FREQUENCY_MAP[self.sync_frequency]
        else:
            raise ValidationError(f"Invalid sync frequency: {self.sync_frequency}")

        if live and self.odoo_to_zoho:
            self._setup_live_automation()
        elif self.automation_id:
            self.automation_id.sudo().active = False

        if live and self.zoho_to_odoo:
            self._setup_live_notification()
        elif self.sudo().notify_channel_id:
            self._disable_live_notification()

        model = self.env['ir.model']._get('zoho.config.schedule')
        if not model:
            raise UserError("Model 'zoho.config.schedule' not found")

        cron_vals = {
            'name': self.name,
            'model_id': model.id,
            'state': 'code',
            'code': f'model.run_crm_sync_by_cron({self.id!r})',
            # A live schedule only needs its cron to pull Zoho -> Odoo.
            'active': not live or self.zoho_to_odoo,
            **frequency,
        }
        if self.cron_id:
            self.cron_id.sudo().write(cron_vals)
        else:
            self.cron_id = self.env['ir.cron'].sudo().create([cron_vals])

    def _setup_live_automation(self):
        """Create or update the automation rule queuing this module's records for a live push
        whenever one of their mapped fields is created or changed."""
        self.ensure_one()
        module = self.module_id
        rule_vals = {
            'name': f"Zoho Live: {self.name}",
            'model_id': module.odoo_model.id,
            'trigger': 'on_create_or_write',
            'trigger_field_ids': [Command.set(module.fields_ids.odoo_field_id.ids)],
            'filter_domain': repr(module._get_default_domain()),
            'active': True,
        }
        action_vals = {
            'name': f"Queue for Zoho: {self.name}",
            'model_id': module.odoo_model.id,
            'usage': 'base_automation',
            'state': 'code',
            'code': f"env['zoho.live.queue'].enqueue_live_records({self.id!r}, records)",
        }
        automation = self.automation_id.sudo().with_context(active_test=False)
        if automation.exists():
            automation.write(rule_vals)
            if automation.action_server_ids:
                automation.action_server_ids.write(action_vals)
            else:
                automation.action_server_ids = [Command.create(action_vals)]
        else:
            automation = self.env['base.automation'].sudo().create([rule_vals])
            automation.action_server_ids = [Command.create(action_vals)]
            self.automation_id = automation

    # ------------------------------------------------------------------
    # Zoho notifications (Zoho -> Odoo live)
    # ------------------------------------------------------------------
    def _watch_request(self, method, **kwargs):
        response = self.module_id._crm_request(method, 'actions/watch', **kwargs)
        try:
            body = response.json()
        except ValueError:
            body = {}
        results = body.get('watch') or body.get('data') or []
        ok = response.status_code in (200, 201, 202) and all(r.get('status') == 'success' for r in results)
        return ok, body or response.text

    def _setup_live_notification(self):
        """Subscribe to (or renew) Zoho notifications for this module's created and edited
        records. Does nothing, and drops any existing channel, when no public URL is set.

        :return: whether notifications are active
        """
        self.ensure_one()
        schedule = self.sudo()
        notify_url = self.env['zoho.config']._get_ready_config()._get_notify_url()
        if not notify_url:
            if schedule.notify_channel_id:
                schedule._disable_live_notification()
            return False

        expiry = fields.Datetime.now() + timedelta(days=NOTIFY_CHANNEL_DAYS)
        channel_id = schedule.notify_channel_id or f"{schedule.id}{secrets.randbelow(10 ** 9):09d}"
        token = schedule.notify_token or secrets.token_urlsafe(24)
        module_name = schedule.module_id.name
        payload = {'watch': [{
            'channel_id': int(channel_id),
            'events': [f"{module_name}.create", f"{module_name}.edit"],
            'notify_url': notify_url,
            'token': token,
            'channel_expiry': expiry.strftime('%Y-%m-%dT%H:%M:%S+00:00'),
        }]}
        ok = False
        if schedule.notify_channel_id:
            ok, body = schedule._watch_request('PATCH', json=payload)
        if not ok:
            ok, body = schedule._watch_request('POST', json=payload)
        if not ok:
            raise UserError(
                f"Could not enable Zoho notifications for {self.name}: {body}\n\n"
                "Check that the 'ZohoCRM.notifications.ALL' scope is granted (then regenerate the "
                "credentials) and that the public URL is reachable from the internet.")
        schedule.write({'notify_channel_id': channel_id, 'notify_token': token, 'notify_expiry': expiry})
        _logger.info("[ZOHO NOTIFY] Channel %s active for %s until %s", channel_id, self.name, expiry)
        return True

    def _disable_live_notification(self):
        self.ensure_one()
        schedule = self.sudo()
        ok, body = schedule._watch_request('DELETE', params={'channel_ids': schedule.notify_channel_id})
        if not ok:
            _logger.warning("[ZOHO NOTIFY] Disabling channel %s: %s", schedule.notify_channel_id, body)
        schedule.write({'notify_channel_id': False, 'notify_token': False, 'notify_expiry': False})

    @api.model
    def _cron_renew_live_notifications(self):
        schedules = self.search([
            ('notify_channel_id', '!=', False),
            ('notify_expiry', '<', fields.Datetime.now() + NOTIFY_RENEW_BEFORE),
        ])
        for schedule in schedules:
            try:
                schedule._setup_live_notification()
            except Exception:
                _logger.exception("[ZOHO NOTIFY] Could not renew channel of %s", schedule.name)

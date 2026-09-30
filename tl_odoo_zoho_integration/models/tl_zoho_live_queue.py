import json
import logging
from collections import defaultdict
from datetime import timedelta

from odoo import models, fields, api
from odoo.tools import consteq

from ..utils import safe_json

_logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 3
DONE_RETENTION_DAYS = 7


class ZohoLiveQueue(models.Model):
    """Records waiting to be synced by a 'Live' schedule.

    - push (Odoo -> Zoho): added by the schedule's automation rule when an Odoo
      record is created or edited.
    - pull (Zoho -> Odoo): added by the ``/zoho/notify`` controller when Zoho
      notifies that a record was created or edited.

    Rows are processed by the 'Zoho Live Sync' cron, triggered right after the
    transaction commits, so neither a save in Odoo nor Zoho's notification call
    waits for the actual sync.
    """
    _name = 'zoho.live.queue'
    _description = "Zoho Live Sync Queue"
    _order = 'id'

    schedule_id = fields.Many2one(comodel_name='zoho.config.schedule', string="Schedule", required=True,
                                  ondelete='cascade', index=True)
    direction = fields.Selection([('push', 'Odoo → Zoho'), ('pull', 'Zoho → Odoo')], string="Direction",
                                 default='push', required=True)
    res_model = fields.Char(string="Model")
    res_id = fields.Integer(string="Record ID")
    zoho_id = fields.Char(string="Zoho ID")
    state = fields.Selection([('pending', 'Pending'), ('done', 'Done'), ('failed', 'Failed')],
                             string="State", default='pending', required=True, index=True)
    attempts = fields.Integer(string="Attempts")
    error = fields.Text(string="Error")

    # ------------------------------------------------------------------
    # Enqueue
    # ------------------------------------------------------------------
    @api.model
    def enqueue_live_records(self, schedule_id, records):
        """Queue Odoo ``records`` for a live push by schedule ``schedule_id``.

        Called from the schedule's automation rule; writes made by the integration
        itself carry ``zoho_live_skip`` and are ignored to avoid sync loops.
        """
        if not records or self.env.context.get('zoho_live_skip') or records.env.context.get('zoho_live_skip'):
            return
        self._enqueue(self.env['zoho.config.schedule'].browse(schedule_id), 'push', 'res_id', records.ids)

    @api.model
    def _enqueue(self, schedule, direction, key, values):
        Queue = self.sudo()
        waiting = set(Queue.search([
            ('schedule_id', '=', schedule.id),
            ('direction', '=', direction),
            (key, 'in', values),
            ('state', '=', 'pending'),
        ]).mapped(key))
        new_values = [value for value in dict.fromkeys(values) if value not in waiting]
        if new_values:
            Queue.create([{
                'schedule_id': schedule.id,
                'direction': direction,
                'res_model': schedule.odoo_model_name,
                key: value,
            } for value in new_values])
        # Runs as soon as the cron worker picks it up, i.e. after this transaction commits.
        self.env.ref('tl_odoo_zoho_integration.ir_cron_zoho_live_push').sudo()._trigger()

    @api.model
    def _receive_notification(self, payload):
        """Queue the records of a Zoho CRM notification (see ``/zoho/notify``).

        :return: False when the notification does not belong to a known channel
                 or its token does not match, True otherwise.
        """
        channel_id = str(payload.get('channel_id') or '')
        schedule = channel_id and self.env['zoho.config.schedule'].sudo().search(
            [('notify_channel_id', '=', channel_id)], limit=1)
        if not schedule or not consteq(str(payload.get('token') or ''), schedule.notify_token or ''):
            _logger.warning("[ZOHO NOTIFY] Rejected notification for unknown channel/token %s", channel_id)
            return False
        operation = payload.get('operation')
        zoho_ids = [str(zoho_id) for zoho_id in payload.get('ids') or [] if zoho_id]
        if operation in ('insert', 'update') and zoho_ids:
            _logger.info("[ZOHO NOTIFY] %s %s record(s) for %s", operation, len(zoho_ids), schedule.name)
            self._enqueue(schedule, 'pull', 'zoho_id', zoho_ids)
        return True

    # ------------------------------------------------------------------
    # Process
    # ------------------------------------------------------------------
    @api.model
    def _cron_process(self):
        self.search([
            ('state', '=', 'done'),
            ('write_date', '<', fields.Datetime.now() - timedelta(days=DONE_RETENTION_DAYS)),
        ]).unlink()

        rows = self.search(['|', ('state', '=', 'pending'),
                            '&', ('state', '=', 'failed'), ('attempts', '<', MAX_ATTEMPTS)])
        rows_by_batch = defaultdict(lambda: self.browse())
        for row in rows:
            rows_by_batch[row.schedule_id, row.direction] |= row

        for (schedule, direction), batch_rows in rows_by_batch.items():
            batch_rows._sync(schedule, direction)
            self.env['ir.cron']._commit_progress(len(batch_rows))

    def _sync(self, schedule, direction):
        """Sync the records of these rows (all of ``schedule`` and ``direction``) and log the run."""
        push = direction == 'push'
        key = 'res_id' if push else 'zoho_id'
        values = list(dict.fromkeys(self.mapped(key)))
        try:
            result = (schedule._live_push(values) if push else schedule._live_pull(values)) or {}
        except Exception as e:
            _logger.exception("[ZOHO LIVE] %s failed for %s", direction, schedule.name)
            self._mark_failed(str(e))
            return

        def row_key(entry):
            if not isinstance(entry, dict):
                return None
            return (entry.get('odoo_id') or entry.get('record_id')) if push else entry.get('zoho_id')

        response = result.get('response', {})
        errors = response.get('errors', [])
        errors_by_key = {row_key(error): json.dumps(error, default=safe_json) for error in errors if row_key(error)}
        # Errors not tied to a record (e.g. the whole batch was refused by Zoho) cannot
        # be told apart, so every row that was not synced is retried.
        global_errors = [error for error in errors if not row_key(error)]
        synced = {row_key(entry) for entry in response.get('created', []) + response.get('updated', [])}

        for row in self:
            if row[key] in errors_by_key:
                row._mark_failed(errors_by_key[row[key]])
            elif global_errors and row[key] not in synced:
                row._mark_failed(json.dumps(global_errors, default=safe_json))
            else:
                # Synced, unchanged, or no longer matching the module (deleted / filtered out).
                row.write({'state': 'done', 'error': False})

        counts = {
            'created': len(response.get('created', [])),
            'updated': len(response.get('updated', [])),
            'unchanged': len(response.get('unchanged', [])),
            'failed': len(self.filtered(lambda r: r.state == 'failed')),
        }
        failed = counts['failed']
        status = ('failed' if failed and not (counts['created'] or counts['updated'] or counts['unchanged'])
                  else 'partial' if failed else 'success')
        if push:
            label = f"[Live: Odoo {schedule.odoo_model_name} -> Zoho {schedule.module_id.name}]"
        else:
            label = f"[Live: Zoho {schedule.module_id.name} -> Odoo {schedule.odoo_model_name}]"
        log_direction = 'two_way' if push else 'one_way'
        dumps = {log_direction: (json.dumps(result.get('request', {}), indent=2, default=safe_json),
                                 json.dumps(response, indent=2, default=safe_json))}
        schedule.create_log(
            modules=schedule.module_id.name,
            status=status,
            request={d: dumps.get(d, ('{}', '{}'))[0] for d in ('one_way', 'two_way')},
            response={d: dumps.get(d, ('{}', '{}'))[1] for d in ('one_way', 'two_way')},
            odoo_ids='{}' if push else json.dumps(counts, indent=2),
            zoho_ids=json.dumps(counts, indent=2) if push else '{}',
            message={
                'success': [f"{label} Synced successfully."] if status != 'failed' else [],
                'error': [f"{label} {failed} record(s) failed."] if failed else [],
            },
        )
        schedule.last_sync = fields.Datetime.now()

    def _mark_failed(self, error):
        for row in self:
            row.write({'state': 'failed', 'attempts': row.attempts + 1, 'error': error})

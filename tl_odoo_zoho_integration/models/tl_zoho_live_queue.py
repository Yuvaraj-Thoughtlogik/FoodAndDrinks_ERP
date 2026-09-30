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
# A Zoho change not newer than our own last push of that record (plus clock skew) is the
# echo of that push, e.g. the notification Zoho sends after Odoo created the record there.
ECHO_MARGIN = timedelta(seconds=5)


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
    # Real time Zoho accepted the push (write_date is the transaction start, too early for long runs).
    pushed_at = fields.Datetime(string="Pushed At", readonly=True)

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
        # Runs inside the user's save: a sync problem must never block saving the record.
        try:
            with self.env.cr.savepoint():
                self._enqueue(self.env['zoho.config.schedule'].browse(schedule_id), 'push', 'res_id', records.ids)
        except Exception:
            _logger.exception("[ZOHO LIVE] Could not queue %s %s for Zoho", records._name, records.ids)

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
            if channel_id:  # an empty channel is the reachability test of the Live Status check
                _logger.warning("[ZOHO NOTIFY] Rejected notification for unknown channel/token %s", channel_id)
            return False
        schedule.notify_last_received = fields.Datetime.now()
        operation = payload.get('operation')
        zoho_ids = [str(zoho_id) for zoho_id in payload.get('ids') or [] if zoho_id]
        if operation in ('insert', 'update') and zoho_ids:
            _logger.info("[ZOHO NOTIFY] %s %s record(s) for %s", operation, len(zoho_ids), schedule.name)
            self._enqueue(schedule, 'pull', 'zoho_id', zoho_ids)
        return True

    # ------------------------------------------------------------------
    # Echo detection
    # ------------------------------------------------------------------
    @api.model
    def _remember_pushes(self, module, pushed):
        """Record pushes made outside the queue (Sync Now, periodic sync) as done push rows,
        so that their echo coming back from Zoho is recognised.

        :param pushed: ``[{'odoo_id': ..., 'zoho_id': ...}]`` as returned by ``sync_odoo_to_zoho``
        """
        schedule = self.env['zoho.config.schedule'].sudo().search([('module_id', '=', module.id)], limit=1)
        pushed = [entry for entry in pushed if entry.get('zoho_id')]
        pushed_at = fields.Datetime.now()
        if schedule and pushed:
            self.sudo().create([{
                'schedule_id': schedule.id,
                'direction': 'push',
                'state': 'done',
                'res_model': module.odoo_model_name,
                'res_id': entry.get('odoo_id'),
                'zoho_id': str(entry['zoho_id']),
                'pushed_at': pushed_at,
            } for entry in pushed])

    @api.model
    def _last_push_times(self, module, zoho_ids):
        """``{zoho_id: datetime}`` of the last push to Zoho of each of ``zoho_ids``."""
        if not zoho_ids:
            return {}
        groups = self.sudo()._read_group(
            [('schedule_id.module_id', '=', module.id), ('direction', '=', 'push'),
             ('state', '=', 'done'), ('zoho_id', 'in', list(zoho_ids)), ('pushed_at', '!=', False)],
            ['zoho_id'], ['pushed_at:max'])
        return {zoho_id: pushed_at for zoho_id, pushed_at in groups}

    @api.model
    def _is_echo(self, pushed_at, modified_time):
        return bool(pushed_at and modified_time and modified_time <= pushed_at + ECHO_MARGIN)

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

        busy = False
        for (schedule, direction), batch_rows in rows_by_batch.items():
            if not schedule._try_lock():
                # Being synced by Sync Now / its cron right now: keep the rows for the next run.
                busy = True
                continue
            batch_rows._sync(schedule, direction)
            self.env['ir.cron']._commit_progress(len(batch_rows))
        if busy:
            self.env.ref('tl_odoo_zoho_integration.ir_cron_zoho_live_push').sudo()._trigger(
                fields.Datetime.now() + timedelta(minutes=1))

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
        synced_at = fields.Datetime.now()

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

        if push:
            # Keep the Zoho id of each pushed record to recognise its echo (see _last_push_times).
            zoho_by_odoo_id = {entry.get('odoo_id'): entry.get('zoho_id')
                               for entry in response.get('created', []) + response.get('updated', [])}
        for row in self:
            if push and zoho_by_odoo_id.get(row.res_id):
                row.write({'zoho_id': str(zoho_by_odoo_id[row.res_id]), 'pushed_at': synced_at})
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
        if not push and not (failed or counts['created'] or counts['updated']):
            return  # only echoes of our own pushes / unchanged records: nothing worth a log entry
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

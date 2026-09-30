import logging

import requests
from markupsafe import Markup

from odoo import models, fields

from ..models.tl_config_module import CRM_API_VERSION
from ..models.tl_zoho_config import NOTIFICATIONS_SCOPE

_logger = logging.getLogger(__name__)

OK, WARN, ERROR, INFO = 'ok', 'warn', 'error', 'info'
BADGES = {
    OK: ('text-bg-success', 'OK'),
    WARN: ('text-bg-warning', 'Warning'),
    ERROR: ('text-bg-danger', 'Problem'),
    INFO: ('text-bg-secondary', 'Info'),
}
SELF_TEST_TIMEOUT = 15


class ZohoLiveStatus(models.TransientModel):
    """Read-only report of everything 'Live' sync depends on, for one Zoho application."""
    _name = 'zoho.live.status'
    _description = "Zoho Live Sync Status"

    zoho_config_app_id = fields.Many2one(comodel_name='zoho.config.application', string="Zoho Application",
                                         required=True, ondelete='cascade')
    report = fields.Html(string="Status", readonly=True, sanitize=False)

    def action_refresh(self):
        self.ensure_one()
        self.report = self._build_report()
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
            'name': "Live Sync Status",
        }

    # ------------------------------------------------------------------
    # Checks
    # ------------------------------------------------------------------
    def _build_report(self):
        app = self.zoho_config_app_id.sudo()
        general_rows, watch_channels = self._check_general(app)
        sections = [("General", general_rows)]
        for schedule in app.schedule_ids:
            sections.append((schedule.module_id.name or schedule.name,
                             self._check_schedule(app, schedule, watch_channels)))
        return self._render(sections)

    def _check_general(self, app):
        """:return: ``(rows, watch_channels)``, the latter None when Zoho's channels are unknown"""
        rows = []
        live = app.sync_frequency == 'live'
        freq_label = dict(app._fields['sync_frequency'].selection).get(app.sync_frequency)
        rows.append(("Sync frequency", OK if live else WARN,
                     f"{freq_label}" if live else f"{freq_label}: live sync is not selected"))
        if app.re_schedule:
            rows.append(("Schedule", WARN, "Settings changed since the last 'Schedule Sync': click it again"))

        config = self.env['zoho.config'].sudo().search([], limit=1)
        try:
            config = config._get_ready_config()
            rows.append(("Zoho credentials", OK, "Access token available"))
        except Exception as e:
            rows.append(("Zoho credentials", ERROR, str(e)))
            config = None

        watch_channels = None
        if config:
            notify_url = config._get_notify_url()
            if not app.zoho_to_odoo:
                rows.append(("Zoho → Odoo", INFO, "Disabled for this application"))
            elif not notify_url:
                rows.append(("Public URL", WARN,
                             "Not set: Zoho changes are only checked periodically, not received instantly"))
            else:
                rows.append(("Public URL", OK, notify_url))
                rows.append(self._check_reachable(notify_url))
                if NOTIFICATIONS_SCOPE in config.scope_ids.mapped('name'):
                    rows.append(("Notifications scope", OK, NOTIFICATIONS_SCOPE))
                else:
                    rows.append(("Notifications scope", ERROR,
                                 f"'{NOTIFICATIONS_SCOPE}' missing: add it and regenerate the credentials"))
                watch_channels, row = self._fetch_watch_channels(config)
                rows.append(row)

        cron = self.env.ref('tl_odoo_zoho_integration.ir_cron_zoho_live_push', raise_if_not_found=False)
        rows.append(("Live queue job", OK if cron and cron.active else ERROR,
                     "Active" if cron and cron.active else "Scheduled action 'Zoho: Live Sync Queue' is inactive"))
        return rows, watch_channels

    def _check_reachable(self, notify_url):
        """POST a notification for a channel that does not exist: this Odoo answers 403
        'Unknown channel', which proves Zoho can reach this very database."""
        try:
            response = requests.post(notify_url, json={'channel_id': 0, 'token': '', 'ids': []},
                                     timeout=SELF_TEST_TIMEOUT)
        except requests.RequestException as e:
            return ("Public URL reachable", ERROR, f"Could not reach {notify_url}: {e}")
        if response.status_code == 403 and 'Unknown channel' in response.text:
            return ("Public URL reachable", OK, "The notification endpoint answers from the internet")
        return ("Public URL reachable", ERROR,
                f"Unexpected answer {response.status_code}: the URL does not lead to this Odoo database "
                f"(wrong address, or another database is selected — check dbfilter)")

    def _fetch_watch_channels(self, config):
        """Channels Zoho has registered for this account, by channel id."""
        try:
            response = config.zoho_request('GET', f"crm/{CRM_API_VERSION}/actions/watch")
        except Exception as e:
            return None, ("Zoho notification channels", ERROR, f"Could not read them from Zoho: {e}")
        if response.status_code == 204:
            return {}, ("Zoho notification channels", INFO, "Zoho has no active channel for this account")
        try:
            body = response.json()
        except ValueError:
            body = {}
        if response.status_code != 200:
            return None, ("Zoho notification channels", ERROR,
                          f"Zoho refused the request ({response.status_code}): {body or response.text}")
        channels = {str(channel.get('channel_id')): channel for channel in body.get('watch') or []}
        return channels, ("Zoho notification channels", OK, f"{len(channels)} active channel(s) on Zoho")

    def _check_schedule(self, app, schedule, watch_channels):
        rows = []
        now = fields.Datetime.now()
        live = app.sync_frequency == 'live'

        if app.odoo_to_zoho:
            rule = schedule.automation_id.with_context(active_test=False)
            if rule and rule.active:
                rows.append(("Odoo → Zoho rule", OK, f"Automation rule '{rule.name}' active"))
            else:
                rows.append(("Odoo → Zoho rule", ERROR if live else INFO,
                             "No active automation rule: click 'Schedule Sync'" if live
                             else "Not live: pushed by the periodic sync"))

        if app.zoho_to_odoo:
            channel_id = schedule.notify_channel_id
            if channel_id:
                expired = schedule.notify_expiry and schedule.notify_expiry < now
                rows.append(("Notification channel", ERROR if expired else OK,
                             f"{channel_id}, {'expired' if expired else 'expires'} {schedule.notify_expiry}"))
                if watch_channels is not None:
                    zoho_channel = watch_channels.get(str(channel_id))
                    if zoho_channel:
                        rows.append(("Registered on Zoho", OK, f"Notifies {zoho_channel.get('notify_url')}"))
                    else:
                        rows.append(("Registered on Zoho", ERROR,
                                     "Zoho does not know this channel: click 'Schedule Sync' to subscribe again"))
                last = schedule.notify_last_received
                rows.append(("Last notification", OK if last else WARN,
                             f"Received {last}" if last else
                             "None received yet: edit a record in Zoho to test"))
            elif live:
                rows.append(("Notification channel", WARN, "None: Zoho changes are only checked periodically"))

            cron = schedule.cron_id
            if cron and cron.active:
                rows.append(("Periodic Zoho check", OK,
                             f"Every {cron.interval_number} {cron.interval_type}, next run {cron.nextcall}"))
            else:
                rows.append(("Periodic Zoho check", ERROR, "Scheduled action missing or inactive"))
            rows.append(("Last Zoho → Odoo sync", INFO, str(schedule.one_way_last_sync or "Never")))

        Queue = self.env['zoho.live.queue'].sudo()
        base_domain = [('schedule_id', '=', schedule.id)]
        pending = Queue.search_count(base_domain + [('state', '=', 'pending')])
        failed = Queue.search(base_domain + [('state', '=', 'failed')], order='id desc')
        rows.append(("Queue", OK if not pending else INFO, f"{pending} waiting"))
        if failed:
            rows.append(("Failed records", ERROR,
                         f"{len(failed)} failed, last error: {(failed[0].error or '')[:300]}"))
        return rows

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------
    def _render(self, sections):
        html = Markup()
        for title, rows in sections:
            body = Markup().join(
                Markup('<tr><td class="fw-bold text-nowrap pe-3">%s</td>'
                       '<td class="pe-3"><span class="badge %s">%s</span></td><td>%s</td></tr>') % (
                    label, BADGES[state][0], BADGES[state][1], detail)
                for label, state, detail in rows)
            html += Markup('<h4 class="mt-3">%s</h4><table class="table table-sm align-middle">%s</table>') % (
                title, body)
        return html

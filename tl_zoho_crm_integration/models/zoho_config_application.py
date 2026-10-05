from odoo import models, fields

FREQUENCY_LABELS = {
    '1_hour': "every hour",
    '2_hour': "every 2 hours",
    'once_a_day': "once a day",
    'live': "instantly whenever a record is created or edited",
}


class ZohoApplication(models.Model):
    _inherit = 'zoho.config.application'

    def action_import_crm_module(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Import Zoho CRM Standard Modules & Fields Map',
            'res_model': 'zoho.import.module',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_zoho_app_id': self.id,
            },
        }

    def action_check_live_status(self):
        self.ensure_one()
        return self.env['zoho.live.status'].create([{'zoho_config_app_id': self.id}]).action_refresh()

    def sync_crm_from_cron(self):
        self.ensure_one()
        self.env['zoho.config'].check_ready_to_sync()
        for schedule in self.schedule_ids:
            schedule.sync_crm_from_cron()

    def create_crm_scheduled_action(self):
        self.ensure_one()
        self.env['zoho.config'].check_ready_to_sync()
        for schedule in self.schedule_ids:
            schedule.create_crm_scheduled_action()

        lines = []
        for schedule in self.schedule_ids:
            if schedule.zoho_to_odoo and schedule.odoo_to_zoho:
                direction = "Zoho <-> Odoo"
            elif schedule.zoho_to_odoo:
                direction = "Zoho → Odoo"
            else:
                direction = "Odoo → Zoho"
            frequency = FREQUENCY_LABELS.get(schedule.sync_frequency, schedule.sync_frequency)
            lines.append(f"- {schedule.module_id.name}: {direction}, {frequency}")

        live_pull = self.schedule_ids.filtered(lambda s: s.sync_frequency == 'live' and s.zoho_to_odoo)
        if live_pull:
            interval_label = dict(self._fields['live_pull_interval'].selection)[self.live_pull_interval].lower()
            if all(live_pull.sudo().mapped('notify_channel_id')):
                lines.append(f"Live Zoho changes arrive instantly through Zoho notifications, "
                             f"and Zoho is also checked {interval_label}.")
            else:
                lines.append(f"Live Zoho changes are checked {interval_label} "
                             f"(set a public URL in the Zoho configuration to receive them instantly).")
        self.write({
            'cron_ids': [fields.Command.link(cron.id) for cron in self.schedule_ids.cron_id],
            're_schedule': False,
            'notify_msg': "Scheduled synchronization has been set up for the following modules:\n" + "\n".join(lines),
        })
        return {'type': 'ir.actions.client', 'tag': 'reload'}

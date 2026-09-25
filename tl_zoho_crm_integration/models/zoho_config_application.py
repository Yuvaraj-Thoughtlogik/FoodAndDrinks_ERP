from odoo import models,fields,api
from odoo.exceptions import UserError

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

    def sync_crm_from_cron(self):
        self.ensure_one()
        self.env['zoho.config'].check_ready_to_sync()
        for schedule in self.schedule_ids:
            schedule.sync_crm_from_cron()

    def create_crm_scheduled_action(self):
        self.ensure_one()
        self.env['zoho.config'].check_ready_to_sync()
        cron_links = []
        for schedule in self.schedule_ids:
            schedule.create_crm_scheduled_action()
            if schedule.cron_id:
                cron_links.append((4, schedule.cron_id.id))
        if cron_links:
            self.cron_ids = cron_links

        self.cron_ids = [(4, schedule.cron_id.id) for schedule in self.schedule_ids if schedule.cron_id]
        self.re_schedule = False
        HUMAN_READABLE = {
            '1_hour': "every hour",
            '2_hour': "every 2 hours",
            'once_a_day': "once a day",  # or "every day"
        }

        frequency_label = HUMAN_READABLE.get(self.sync_frequency, self.sync_frequency)
        self.notify_msg = (
            f"A scheduled synchronization has been set up to run {frequency_label}. "
            f"\nIt will synchronize the following modules: {', '.join([sh.module_id.name for sh in self.schedule_ids])}."
        )
        # return {
        #     'type': 'ir.actions.client',
        #     'tag': 'display_notification',
        #     'params': {
        #         'title': 'Scheduled Action Created',
        #         'message': f"Cron created for sync every {self.sync_frequency.replace('_', ' ')}.Modules: {','.join([sh.module_id.name for sh in self.schedule_ids])}",
        #         'type': 'success',
        #         'sticky': False,
        #     }
        # }
        self.env.cr.commit()  # optional, ensure DB is up to date
        return {
            'type': 'ir.actions.client',
            'tag': 'reload',

        }



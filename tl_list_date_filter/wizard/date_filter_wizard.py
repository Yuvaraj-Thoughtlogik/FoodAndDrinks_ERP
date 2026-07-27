from datetime import datetime, time

import pytz

from odoo import api, fields, models


class ListDateFilterWizard(models.TransientModel):
    _name = 'list.date.filter.wizard'
    _description = 'List Date Filter Wizard'

    config_id = fields.Many2one(
        'list.filter.configuration',
        required=True,
    )

    @api.model
    def _default_start_date(self):
        user_tz = pytz.timezone(self.env.user.tz or 'UTC')
        today = fields.Date.context_today(self)

        local_dt = user_tz.localize(datetime.combine(today, time(0, 0, 0)))
        return local_dt.astimezone(pytz.UTC).replace(tzinfo=None)

    @api.model
    def _default_end_date(self):
        user_tz = pytz.timezone(self.env.user.tz or 'UTC')
        today = fields.Date.context_today(self)

        local_dt = user_tz.localize(datetime.combine(today, time(23, 59, 59)))
        return local_dt.astimezone(pytz.UTC).replace(tzinfo=None)

    start_date = fields.Datetime(
        required=True,
        default=_default_start_date,
    )

    end_date = fields.Datetime(
        required=True,
        default=_default_end_date,
    )

    @api.onchange('start_date')
    def _onchange_start_date(self):
        if self.start_date:
            user_tz = pytz.timezone(self.env.user.tz or 'UTC')

            # Convert UTC -> local
            local_dt = pytz.UTC.localize(self.start_date).astimezone(user_tz)

            # Set local end of day
            local_dt = local_dt.replace(hour=23, minute=59, second=59, microsecond=0)

            # Convert back to UTC
            self.end_date = local_dt.astimezone(pytz.UTC).replace(tzinfo=None)

    def confirm(self):
        self.ensure_one()

        field_name = self.config_id.date_field_id.name

        return {
            'type': 'ir.actions.act_window',
            'name': 'Filtered Records',
            'res_model': self.config_id.model_id.model,
            'view_mode': 'list,form',
            'domain': [
                (field_name, '>=', self.start_date),
                (field_name, '<=', self.end_date),
            ],
            'target': 'current',
        }
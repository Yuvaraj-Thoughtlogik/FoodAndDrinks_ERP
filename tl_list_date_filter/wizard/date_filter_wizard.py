from odoo import api, fields, models
from datetime import datetime, time


class ListDateFilterWizard(models.TransientModel):
    _name = 'list.date.filter.wizard'
    _description = 'List Date Filter Wizard'

    config_id = fields.Many2one(
        'list.filter.configuration',
        required=True,
    )

    start_date = fields.Date(
        required=True,
        default=fields.Date.context_today,
    )

    end_date = fields.Date(
        required=True,
        default=fields.Date.context_today,
    )

    @api.onchange('start_date')
    def _onchange_start_date(self):
        if self.start_date:
            self.end_date = self.start_date


    def confirm(self):
        self.ensure_one()

        field_name = self.config_id.date_field_id.name

        start = datetime.combine(self.start_date, time.min)
        end = datetime.combine(self.end_date, time.max)

        return {
            'type': 'ir.actions.act_window',
            'name': 'Filtered Records',
            'res_model': self.config_id.model_id.model,
            'view_id':self.config_id.view_id.id,
            'view_mode': 'list,form',
            'domain': [
                (field_name, '>=', fields.Datetime.to_string(start)),
                (field_name, '<=', fields.Datetime.to_string(end)),
            ],
            'target': 'current',
        }
# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class ActiveBatchReportWizard(models.TransientModel):
    _name = 'active.batch.report.wizard'
    _description = 'Active Batch Report Wizard'

    weeks = fields.Integer(
        string='Within Weeks',
        required=True,
        default=8,
        help="Number of weeks before and after today to include in the report."
    )
    round_ids = fields.Many2many(
        'round.management.round',
        'active_batch_report_wizard_round_rel',
        'wizard_id',
        'round_id',
        string='Round',
        domain="[('state', '=', 'active')]",
        help="Select one or more Rounds. If left empty, all Rounds should be considered."
    )

    @api.constrains('weeks')
    def _check_weeks(self):
        for record in self:
            if record.weeks <= 0:
                raise ValidationError(_("Within Weeks must be greater than 0."))

    def action_print_report(self):
        """Generates the Active Batch Report."""
        self.ensure_one()
        return self.env.ref('tl_rf_reports.action_report_active_batch').report_action(self)

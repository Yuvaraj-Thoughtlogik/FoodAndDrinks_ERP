# -*- coding: utf-8 -*-
import base64

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


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
        """Generates the Active Batch Report.

        Built directly with ReportLab (generate_pdf() on the report model)
        instead of QWeb+wkhtmltopdf, same as the Delivery Note Round reports -
        native in-process PDF drawing, no subprocess, fully synchronous."""
        self.ensure_one()

        report_model = self.env['report.tl_rf_reports.report_active_batch']
        pdf_content = report_model.generate_pdf(self)
        if not pdf_content:
            raise UserError(_("There is nothing to print for the selected criteria."))

        attachment = self.env['ir.attachment'].create({
            'name': f"Active_Batch_Report_{fields.Date.context_today(self).strftime('%Y%m%d')}.pdf",
            'type': 'binary',
            'datas': base64.b64encode(pdf_content),
            'mimetype': 'application/pdf',
            'res_model': self._name,
            'res_id': self.id,
        })
        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{attachment.id}?download=true',
            'target': 'self',
        }

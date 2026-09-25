# -*- coding: utf-8 -*-
import base64
import io

from odoo import api, fields, models
from odoo.tools import _
from odoo.exceptions import UserError, ValidationError


class PredictionReportWizard(models.TransientModel):
    _name = 'prediction.report.wizard'
    _description = 'Prediction Report Wizard'



    delivery_channel = fields.Selection(
        selection=[
            ('regal_van', 'Regal Van Delivery'),
            ('courier', 'Courier Delivery'),
            ('both', 'Both'),
        ],
        string='Delivery Channel',
        required=True,
        default='regal_van',
        help="Select delivery channel for the report."
    )
    delivery_date_from = fields.Date(
        string='Delivery Date From',
        required=True,
        default=fields.Date.context_today,
    )
    delivery_date_to = fields.Date(
        string='Delivery Date To',
        required=True,
        default=fields.Date.context_today,
    )

    @api.onchange('delivery_date_from')
    def _onchange_delivery_date_from(self):
        if self.delivery_date_from:
            self.delivery_date_to = self.delivery_date_from

    @api.model
    def _default_depot_ids(self):
        return self.env['stock.warehouse'].search([])

    depot_ids = fields.Many2many(
        'stock.warehouse',
        'prediction_report_wizard_warehouse_rel',
        'wizard_id',
        'warehouse_id',
        string='Depot',
        default=_default_depot_ids,
    )

    categ_ids = fields.Many2many(
        'product.category',
        'prediction_report_wizard_category_rel',
        'wizard_id',
        'category_id',
        string='Product Category',
    )

    @api.constrains('delivery_date_from', 'delivery_date_to')
    def _check_dates(self):
        for record in self:
            if record.delivery_date_from and record.delivery_date_to and record.delivery_date_to < record.delivery_date_from:
                raise ValidationError(_("Delivery Date To cannot be earlier than Delivery Date From."))

    def _get_report_model(self):
        return self.env['report.tl_rf_reports.report_prediction']

    def _get_line_domain(self):
        """Same filtering rules as the printed report (delivery channel incl.
        'Both', depot, category) - delegated so the two never drift apart."""
        self.ensure_one()
        return self._get_report_model()._build_prediction_domain(self)

    def _download_action(self, pdf_content, filename):
        attachment = self.env['ir.attachment'].create({
            'name': filename,
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

    def _check_has_lines(self):
        self.ensure_one()
        if not self.env['sale.order.line'].search_count(self._get_line_domain()):
            if self.delivery_channel == 'both':
                channel_name = _("Regal Van or Courier")
            else:
                channel_name = dict(self._fields['delivery_channel'].selection).get(self.delivery_channel, '')
            raise UserError(_(
                "No confirmed %s order lines found with delivery dates between %s and %s."
            ) % (
                channel_name,
                self.delivery_date_from.strftime('%d/%m/%Y'),
                self.delivery_date_to.strftime('%d/%m/%Y'),
            ))

    def action_print_report(self):
        """Downloads the PDF, built directly with
        ReportLab (generate_pdf() on the report model).

        Courier uses the courier layout; Regal Van and 'Both' use the main
        layout. For 'Both' the lines of both channels are merged into that
        single report (courier lines appear under a 'Courier' depot row)
        instead of printing two separate reports."""
        self.ensure_one()
        self._check_has_lines()

        if self.delivery_channel == 'courier':
            report_model = self.env['report.tl_rf_reports.report_prediction_courier']
            filename_prefix = 'Courier_Prediction_Report_'
        else:
            report_model = self._get_report_model()
            filename_prefix = 'Prediction_Report_Combined_' if self.delivery_channel == 'both' else 'Prediction_Report_'

        pdf_content = report_model.generate_pdf(self)
        return self._download_action(
            pdf_content, f"{filename_prefix}{self.delivery_date_from.strftime('%Y%m%d')}.pdf"
        )

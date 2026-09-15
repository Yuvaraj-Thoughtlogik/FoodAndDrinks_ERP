# -*- coding: utf-8 -*-
import base64

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class DeliveryNoteRoundWizard(models.TransientModel):
    _name = 'delivery.note.round.wizard'
    _description = 'Delivery Note Round Report Wizard'

    delivery_channel = fields.Selection(
        selection=[
            ('regal_van', 'Regal Van Delivery'),
            ('courier', 'Courier Delivery'),
        ],
        string='Delivery Channel',
        required=True,
        default='courier',
        help="Select delivery channel for the delivery note report."
    )
    delivery_date_from = fields.Date(
        string='Deliver From',
        required=True,
        default=fields.Date.context_today,
        help="Starting delivery date for delivery note selection."
    )
    delivery_date_to = fields.Date(
        string='Deliver To',
        required=True,
        default=fields.Date.context_today,
        help="Ending delivery date for delivery note selection."
    )

    @api.onchange('delivery_date_from')
    def _onchange_delivery_date_from(self):
        """Keep 'Delivery Date To' in sync with 'Delivery Date From' whenever
        the start date changes, so a single-day selection (e.g. both = Sep 14)
        is the default without extra clicks. If the user later picks a later
        'To' date manually, that stays untouched until 'From' changes again."""
        if self.delivery_date_from:
            self.delivery_date_to = self.delivery_date_from

    @api.constrains('delivery_date_from', 'delivery_date_to')
    def _check_dates(self):
        for record in self:
            if record.delivery_date_from and record.delivery_date_to and record.delivery_date_to < record.delivery_date_from:
                raise ValidationError(_("Deliver To date cannot be earlier than Deliver From date."))

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

    def action_print_report(self):
        """Validates batches or orders for the selected delivery channel and
        triggers the Delivery Note Round Report, using lightweight
        search_count() checks before generating the PDF.

        Both channels are now built directly with ReportLab (generate_pdf() on
        each report model) instead of QWeb+wkhtmltopdf: wkhtmltopdf renders
        roughly one page per drop/order, so at a few thousand records that was
        10+ minutes and a request timeout. ReportLab draws the PDF natively in
        this process, so both stay fully synchronous - no background job
        needed."""
        self.ensure_one()

        if self.delivery_channel == 'courier':
            order_count = self.env['sale.order'].search_count([
                ('delivery_channel', '=', 'courier'),
                ('state', 'in', ['sale', 'done']),
                ('delivery_date', '>=', self.delivery_date_from),
                ('delivery_date', '<=', self.delivery_date_to),
            ])
            if not order_count:
                raise UserError(_(
                    "No confirmed Courier Delivery orders found between %s and %s."
                ) % (
                    self.delivery_date_from.strftime('%d/%m/%Y'),
                    self.delivery_date_to.strftime('%d/%m/%Y'),
                ))

            report_model = self.env['report.tl_rf_reports.report_delivery_note_round_courier']
            pdf_content = report_model.generate_pdf(self)
            if not pdf_content:
                raise UserError(_(
                    "No confirmed Courier Delivery orders with deliverable lines were found with "
                    "delivery dates between %s and %s."
                ) % (
                    self.delivery_date_from.strftime('%d/%m/%Y'),
                    self.delivery_date_to.strftime('%d/%m/%Y'),
                ))
            return self._download_action(
                pdf_content, f"Delivery_Note_Round_Courier_{self.delivery_date_from.strftime('%Y%m%d')}.pdf"
            )

        batch_count = self.env['round.management.batch'].search_count([
            ('delivery_date', '>=', self.delivery_date_from),
            ('delivery_date', '<=', self.delivery_date_to),
        ])
        if not batch_count:
            raise UserError(_(
                "No batches found with delivery dates between %s and %s."
            ) % (
                self.delivery_date_from.strftime('%d/%m/%Y'),
                self.delivery_date_to.strftime('%d/%m/%Y'),
            ))

        report_model = self.env['report.tl_rf_reports.report_delivery_note_round_van']
        pdf_content = report_model.generate_pdf(self)
        if not pdf_content:
            raise UserError(_(
                "Eligible batches were found, but they do not contain any deliverable Regal Van lines "
                "within the selected criteria."
            ))
        return self._download_action(
            pdf_content, f"Delivery_Note_Round_Van_{self.delivery_date_from.strftime('%Y%m%d')}.pdf"
        )

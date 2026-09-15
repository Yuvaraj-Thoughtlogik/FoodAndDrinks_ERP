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
        default='regal_van',
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

    @api.constrains('delivery_date_from', 'delivery_date_to')
    def _check_dates(self):
        for record in self:
            if record.delivery_date_from and record.delivery_date_to and record.delivery_date_to < record.delivery_date_from:
                raise ValidationError(_("Deliver To cannot be earlier than Deliver From."))

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
        triggers the Delivery Note Round Report.

        Both channels are now built directly with ReportLab (generate_pdf() on
        each report model) instead of QWeb+wkhtmltopdf: wkhtmltopdf renders
        roughly one page per drop/order, so at a few thousand records that was
        10+ minutes and a request timeout. ReportLab draws the PDF natively in
        this process, so both stay fully synchronous - no background job
        needed."""
        self.ensure_one()

        if self.delivery_channel == 'courier':
            order_domain = [
                ('delivery_channel', '=', 'courier'),
                ('state', 'in', ['sale', 'done']),
                ('delivery_date', '>=', self.delivery_date_from),
                ('delivery_date', '<=', self.delivery_date_to),
            ]
            if not self.env['sale.order'].search_count(order_domain):
                raise UserError(_(
                    "No confirmed Courier Delivery orders found with delivery dates between %s and %s."
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

        # Regal Van Delivery
        domain = [
            ('delivery_date', '>=', self.delivery_date_from),
            ('delivery_date', '<=', self.delivery_date_to),
        ]

        batches = self.env['round.management.batch'].search(domain)
        if not batches:
            raise UserError(_(
                "No batches found with delivery dates between %s and %s."
            ) % (
                self.delivery_date_from.strftime('%d/%m/%Y'),
                self.delivery_date_to.strftime('%d/%m/%Y'),
            ))

        # Check if batches contain matching Regal Van Delivery orders
        eligible_orders = batches.mapped('order_ids').filtered(
            lambda so: so.state in ('sale', 'done') and getattr(so, 'delivery_channel', False) in ('regal_van', False)
        )

        if not eligible_orders:
            raise UserError(_(
                "Eligible batches were found, but they do not contain any matching Regal Van Delivery sale orders within the selected criteria."
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
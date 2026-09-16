# -*- coding: utf-8 -*-
import base64
import io

from odoo import api, fields, models
from odoo.tools import _
from odoo.exceptions import UserError, ValidationError


class RequirementReportWizard(models.TransientModel):
    _name = 'requirement.report.wizard'
    _description = 'Requirement Report Wizard'

    delivery_channel = fields.Selection(
        selection=[
            ('regal_van', 'Regal Van Delivery'),
            ('courier', 'Courier Delivery'),
            ('both', 'Both'),
        ],
        string='Delivery Channel',
        required=True,
        default='regal_van',
        help="Select delivery channel for the report. 'Both' prints the "
             "existing Regal Van and Courier reports one after the other, "
             "combined into a single PDF."
    )
    delivery_date_from = fields.Date(
        string='Delivery Date From',
        required=True,
        default=fields.Date.context_today,
        help="Starting delivery date for requirement report."
    )
    delivery_date_to = fields.Date(
        string='Delivery Date To',
        required=True,
        default=fields.Date.context_today,
        help="Ending delivery date for requirement report."
    )

    @api.onchange('delivery_date_from')
    def _onchange_delivery_date_from(self):
        """Keep 'Delivery Date To' in sync with 'Delivery Date From' whenever
        the start date changes, so a single-day selection (e.g. both = Sep 14)
        is the default without extra clicks. If the user later picks a later
        'To' date manually, that stays untouched until 'From' changes again."""
        if self.delivery_date_from:
            self.delivery_date_to = self.delivery_date_from

    @api.model
    def _default_depot_ids(self):
        return self.env['stock.warehouse'].search([])

    depot_ids = fields.Many2many(
        'stock.warehouse',
        'requirement_report_wizard_warehouse_rel',
        'wizard_id',
        'warehouse_id',
        string='Depot',
        default=_default_depot_ids,
        help="Select one or more depots. Leave unselected to include all depots."
    )

    categ_ids = fields.Many2many(
        'product.category',
        'requirement_report_wizard_category_rel',
        'wizard_id',
        'category_id',
        string='Product Category',
        help="Select one or more product categories to filter. Leave empty to include all categories."
    )

    @api.constrains('delivery_date_from', 'delivery_date_to')
    def _check_dates(self):
        for record in self:
            if record.delivery_date_from and record.delivery_date_to and record.delivery_date_to < record.delivery_date_from:
                raise ValidationError(_("Delivery Date To cannot be earlier than Delivery Date From."))

    def _get_line_domain(self):
        """Helper method to construct search domain for sale order lines."""
        self.ensure_one()
        domain = [
            ('order_id.state', 'in', ['sale', 'done']),
            ('order_id.delivery_date', '>=', self.delivery_date_from),
            ('order_id.delivery_date', '<=', self.delivery_date_to),
            ('display_type', '=', False),
            ('product_id', '!=', False),
        ]
        if self.delivery_channel == 'courier':
            domain.append(('order_id.delivery_channel', '=', 'courier'))
        else:
            domain.append(('order_id.delivery_channel', 'in', ['regal_van', False]))
            if self.depot_ids:
                domain.append(('depot_id', 'in', self.depot_ids.ids))

        if self.categ_ids:
            domain.append(('categ_id', 'in', self.categ_ids.ids))

        return domain

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

    def _get_channel_wizard(self, channel):
        """Returns a throwaway requirement.report.wizard record - a copy of
        this wizard with delivery_channel forced to a single real channel
        ('regal_van' or 'courier') - so the existing, unmodified per-channel
        report logic (_get_line_domain(), _get_report_values(), templates)
        can be reused as-is for each half of the 'Both' combined report."""
        self.ensure_one()
        return self.create({
            'delivery_channel': channel,
            'delivery_date_from': self.delivery_date_from,
            'delivery_date_to': self.delivery_date_to,
            'depot_ids': [(6, 0, self.depot_ids.ids)],
            'categ_ids': [(6, 0, self.categ_ids.ids)],
        })

    def action_print_report(self):
        """Validates matching orders/lines and triggers the Requirement PDF Report.

        Built directly with ReportLab (generate_pdf() on the matching report
        model) instead of QWeb+wkhtmltopdf - see report/requirement_report.py.
        Which report model is used still depends on delivery_channel exactly
        as before (Courier -> report_requirement_courier, Regal Van ->
        report_requirement); only how the PDF gets produced/returned changed.

        'Both' is handled separately by _action_print_combined_report()."""
        self.ensure_one()

        if self.delivery_channel == 'both':
            return self._action_print_combined_report()

        domain = self._get_line_domain()
        matching_lines = self.env['sale.order.line'].search_count(domain)
        if not matching_lines:
            channel_name = dict(self._fields['delivery_channel'].selection).get(self.delivery_channel, '')
            raise UserError(_(
                "No confirmed %s order lines found with delivery dates between %s and %s."
            ) % (
                channel_name,
                self.delivery_date_from.strftime('%d/%m/%Y'),
                self.delivery_date_to.strftime('%d/%m/%Y'),
            ))

        if self.delivery_channel == 'courier':
            report_model = self.env['report.tl_rf_reports.report_requirement_courier']
            filename_prefix = 'Courier_Requirement_Report_'
        else:
            report_model = self.env['report.tl_rf_reports.report_requirement']
            filename_prefix = 'Requirement_Report_'

        pdf_content = report_model.generate_pdf(self)
        if not pdf_content:
            channel_name = dict(self._fields['delivery_channel'].selection).get(self.delivery_channel, '')
            raise UserError(_(
                "No confirmed %s order lines found with delivery dates between %s and %s."
            ) % (
                channel_name,
                self.delivery_date_from.strftime('%d/%m/%Y'),
                self.delivery_date_to.strftime('%d/%m/%Y'),
            ))

        return self._download_action(
            pdf_content, f"{filename_prefix}{self.delivery_date_from.strftime('%Y%m%d')}.pdf"
        )

    def _action_print_combined_report(self):
        """'Both': generates the Regal Van and Courier requirement reports
        separately, using their existing/unmodified report logic and
        templates, then concatenates them into a single PDF - Regal Van
        first, Courier second. Each is a fully independent document, so
        appending their pages always starts the Courier report on a fresh
        page, never mid-page.

        Whichever channel has no matching data is silently skipped (rather
        than failing the whole print), and this only raises when neither
        channel has anything to print."""
        self.ensure_one()

        van_wizard = self._get_channel_wizard('regal_van')
        courier_wizard = self._get_channel_wizard('courier')
        SaleOrderLine = self.env['sale.order.line']

        try:
            has_van = bool(SaleOrderLine.search_count(van_wizard._get_line_domain()))
            has_courier = bool(SaleOrderLine.search_count(courier_wizard._get_line_domain()))

            if not has_van and not has_courier:
                raise UserError(_(
                    "No confirmed Regal Van or Courier order lines found with delivery dates between %s and %s."
                ) % (
                    self.delivery_date_from.strftime('%d/%m/%Y'),
                    self.delivery_date_to.strftime('%d/%m/%Y'),
                ))

            van_pdf = self.env['report.tl_rf_reports.report_requirement'].generate_pdf(van_wizard) if has_van else None
            courier_pdf = self.env['report.tl_rf_reports.report_requirement_courier'].generate_pdf(courier_wizard) if has_courier else None
        finally:
            (van_wizard | courier_wizard).unlink()

        # Order matters: Regal Van always first, Courier always second.
        pdfs = [pdf for pdf in (van_pdf, courier_pdf) if pdf]
        if not pdfs:
            raise UserError(_(
                "No confirmed Regal Van or Courier order lines with printable data were found with "
                "delivery dates between %s and %s."
            ) % (
                self.delivery_date_from.strftime('%d/%m/%Y'),
                self.delivery_date_to.strftime('%d/%m/%Y'),
            ))

        if len(pdfs) == 1:
            combined_pdf = pdfs[0]
        else:
            streams = [io.BytesIO(pdf) for pdf in pdfs]
            merged_stream = self.env['ir.actions.report']._merge_pdfs(streams)
            combined_pdf = merged_stream.getvalue()
            merged_stream.close()

        return self._download_action(
            combined_pdf, f"Requirement_Report_Combined_{self.delivery_date_from.strftime('%Y%m%d')}.pdf"
        )

    def action_view_lines(self):
        """Opens the Sale Order Line list view grouped by category and delivery date."""
        self.ensure_one()
        domain = self._get_line_domain()
        matching_lines = self.env['sale.order.line'].search_count(domain)
        if not matching_lines:
            channel_name = dict(self._fields['delivery_channel'].selection).get(self.delivery_channel, '')
            raise UserError(_(
                "No confirmed %s order lines found with delivery dates between %s and %s."
            ) % (
                channel_name,
                self.delivery_date_from.strftime('%d/%m/%Y'),
                self.delivery_date_to.strftime('%d/%m/%Y'),
            ))

        context = {
            'search_default_group_by_category': 1,
            # 'search_default_group_by_delivery_date': 1,
        }
        return {
            'name': _('Requirement Report - Order Lines'),
            'type': 'ir.actions.act_window',
            'res_model': 'sale.order.line',
            'view_mode': 'list,form',
            'views': [
                (self.env.ref('tl_rf_reports.view_sale_order_line_requirement_tree').id, 'list'),
                (False, 'form'),
            ],
            'search_view_id': [self.env.ref('tl_rf_reports.view_sale_order_line_requirement_search').id, 'search'],
            'domain': domain,
            'context': context,
        }

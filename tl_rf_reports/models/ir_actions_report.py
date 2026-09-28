import io
from collections import OrderedDict

from odoo import models


class IrActionsReport(models.Model):
    _inherit = 'ir.actions.report'

    # Odoo's standard customer invoice reports, printed in the Regal Fish
    # invoice layout instead of their QWeb template.
    RF_INVOICE_REPORTS = ('account.report_invoice_with_payments', 'account.report_invoice')
    RF_DRIVER_COPY_REPORT = 'tl_rf_reports.report_driver_copy'
    RF_CUSTOMER_COPY_REPORT = 'tl_rf_reports.report_customer_copy'

    def _render_qweb_pdf_prepare_streams(self, report_ref, data, res_ids=None):
        """Serve the Regal Fish invoice and the Driver Copy from ReportLab
        instead of QWeb/wkhtmltopdf - same mechanism the account module uses
        for 'Original Bills': one ready-made PDF stream per record. Every
        caller (Print menu, Send & Print, portal download, report attachment
        saving) goes through here, so they all get the same layout."""
        report_name = self._get_report(report_ref).report_name
        copy_reports = {self.RF_DRIVER_COPY_REPORT: 'driver', self.RF_CUSTOMER_COPY_REPORT: 'customer'}
        if not res_ids or report_name not in self.RF_INVOICE_REPORTS + tuple(copy_reports):
            return super()._render_qweb_pdf_prepare_streams(report_ref, data, res_ids=res_ids)

        if report_name in copy_reports:
            records = self.env['stock.picking'].browse(res_ids)
            generator = self.env['report.tl_rf_reports.report_driver_copy']
            copy_type = copy_reports[report_name]

            def render(record):
                return generator.generate_pdf(record, copy_type=copy_type)
        else:
            records = self.env['account.move'].browse(res_ids)
            generator = self.env['report.tl_rf_reports.report_invoice_regal']
            proforma = bool((data or {}).get('proforma') or self.env.context.get('proforma_invoice'))

            def render(record):
                return generator.with_company(record.company_id).generate_pdf(record, proforma=proforma)

        collected_streams = OrderedDict()
        for record in records:
            collected_streams[record.id] = {
                'stream': io.BytesIO(render(record)),
                'attachment': None,
            }
        return collected_streams

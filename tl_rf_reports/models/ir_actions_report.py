# -*- coding: utf-8 -*-
import io
import logging

from reportlab.lib import colors
from reportlab.pdfgen import canvas

from odoo import api, fields, models, tools
from odoo.modules import module
from odoo.tools.pdf import PdfFileReader, PdfFileWriter

_logger = logging.getLogger(__name__)

REPORT_PAGE_NUMBER_CONFIGS = {
    'tl_rf_reports.report_dock_weight_breakdown': {
        'format': 'Page {page}',
        'position': 'right',
        'font_size': 12,
        'margin_bottom': 20.0,
        'margin_side': 42.5,
    },
    'tl_rf_reports.report_delivery_note_round_van': {
        'format': '{page}',
        'position': 'center',
        'font_size': 13,
        'margin_bottom': 20.0,
    },
    'tl_rf_reports.report_packing_list': {
        'format': '{page}',
        'position': 'center',
        'font_size': 10,
        'margin_bottom': 20.0,
    },
    'tl_rf_reports.report_driver_packing_list': {
        'format': '{page}',
        'position': 'center',
        'font_size': 10,
        'margin_bottom': 20.0,
    },
    'tl_rf_reports.report_requirement': {
        'format': 'Page {page} of {total}',
        'position': 'right',
        'font_size': 11,
        'margin_bottom': 20.0,
        'margin_side': 28.35,
    },
    'tl_rf_reports.report_requirement_courier': {
        'format': 'Page {page} of {total}',
        'position': 'right',
        'font_size': 11,
        'margin_bottom': 20.0,
        'margin_side': 28.35,
    },
    'tl_rf_reports.report_production_label_document_courier': {
        'enabled': False,
    },
    'tl_rf_reports.report_production_label_document_regal_van': {
        'enabled': False,
    },
}


class IrActionsReport(models.Model):
    _inherit = 'ir.actions.report'

    @api.model
    def _get_pdf_batch_size(self):
        """Returns the batch size limit for PDF rendering to avoid overloading wkhtmltopdf."""
        try:
            param = self.env['ir.config_parameter'].sudo().get_param('report.pdf.batch_size')
            if param:
                return max(1, int(param))
        except (ValueError, TypeError):
            pass
        return 100

    @api.model
    def _stamp_page_numbers(self, pdf_content, report_ref=None, format_str=None, position=None):
        """Stamps continuous, 100% accurate page numbers onto each page of the final PDF."""
        if not pdf_content:
            return pdf_content

        try:
            reader = PdfFileReader(io.BytesIO(pdf_content))
            total_pages = reader.numPages
            if total_pages <= 0:
                return pdf_content

            report_key = False
            if report_ref:
                if isinstance(report_ref, str):
                    report_key = report_ref
                elif hasattr(report_ref, 'report_name') and report_ref.report_name:
                    report_key = report_ref.report_name

            cfg = dict(REPORT_PAGE_NUMBER_CONFIGS.get(report_key, {
                'format': 'Page {page} of {total}',
                'position': 'right',
                'font_size': 9,
                'margin_bottom': 20.0,
                'margin_side': 28.35,
            }))

            if cfg.get('enabled') is False or (report_key and ('production_label' in report_key or 'label' in report_key)):
                return pdf_content

            if format_str:
                cfg['format'] = format_str
            if position:
                cfg['position'] = position

            writer = PdfFileWriter()
            for i in range(total_pages):
                page = reader.getPage(i)
                width = float(page.mediaBox.getWidth())
                height = float(page.mediaBox.getHeight())

                packet = io.BytesIO()
                can = canvas.Canvas(packet, pagesize=(width, height))
                can.setFont('Helvetica', cfg.get('font_size', 9))
                can.setFillColor(colors.HexColor('#000000'))

                text = cfg['format'].format(page=i + 1, total=total_pages)
                mb = cfg.get('margin_bottom', 20.0)
                ms = cfg.get('margin_side', 28.35)

                pos = cfg.get('position', 'right')
                if pos == 'right':
                    can.drawRightString(width - ms, mb, text)
                elif pos == 'center':
                    can.drawCentredString(width / 2.0, mb, text)
                elif pos == 'left':
                    can.drawString(ms, mb, text)

                can.save()
                packet.seek(0)

                overlay_reader = PdfFileReader(packet)
                page.mergePage(overlay_reader.getPage(0))
                writer.addPage(page)

            out_stream = io.BytesIO()
            writer.write(out_stream)
            return out_stream.getvalue()

        except Exception as e:
            _logger.warning("Failed to stamp continuous page numbers on PDF: %s", e)
            return pdf_content

    @api.model
    def _get_pdf_workers(self):
        """Returns the number of parallel workers for PDF rendering."""
        try:
            param = self.env['ir.config_parameter'].sudo().get_param('report.pdf.workers')
            if param:
                return max(1, int(param))
        except (ValueError, TypeError):
            pass
        import os
        cpu_cnt = os.cpu_count() or 4
        return min(4, max(2, cpu_cnt))

    def _render_qweb_pdf(self, report_ref, res_ids=None, data=None):
        """Override to automatically batch large recordsets during PDF generation and merge the results with accurate page numbering."""
        if not data:
            data = {}
        if isinstance(res_ids, int):
            res_ids = [res_ids]

        # In test environments without force_report_rendering, fallback to default behavior
        if (module.current_test or tools.config.get('test_enable')) and not self.env.context.get('force_report_rendering'):
            return super()._render_qweb_pdf(report_ref, res_ids=res_ids, data=data)

        batch_size = self._get_pdf_batch_size()

        # If res_ids exceeds batch_size and not already inside a sub-batch execution
        if res_ids and len(res_ids) > batch_size and not self.env.context.get('in_pdf_batch'):
            report_sudo = self._get_report(report_ref)
            _logger.info(
                "Large PDF report detected for %r: processing %d records in batches of %d",
                report_sudo.report_name or report_ref, len(res_ids), batch_size
            )
            pdf_streams = []
            for i in range(0, len(res_ids), batch_size):
                chunk_ids = res_ids[i:i + batch_size]
                chunk_content, _ = self.with_context(in_pdf_batch=True)._render_qweb_pdf(
                    report_ref, res_ids=chunk_ids, data=data
                )
                pdf_streams.append(io.BytesIO(chunk_content))

            # Automatically combine all generated batches into a single PDF
            with self._merge_pdfs(pdf_streams) as merged_stream:
                merged_pdf = merged_stream.getvalue()
                final_pdf = self._stamp_page_numbers(merged_pdf, report_ref=report_ref)
                return final_pdf, 'pdf'

        content, report_type = super()._render_qweb_pdf(report_ref, res_ids=res_ids, data=data)
        if report_type == 'pdf' and not self.env.context.get('in_pdf_batch'):
            content = self._stamp_page_numbers(content, report_ref=report_ref)
        return content, report_type

    @api.model
    def _run_wkhtmltopdf(
            self,
            bodies,
            report_ref=False,
            header=None,
            footer=None,
            landscape=False,
            specific_paperformat_args=None,
            set_viewport_size=False):
        """Override to automatically batch large HTML body lists (pages/articles) during wkhtmltopdf conversion and execute in parallel."""
        batch_size = self._get_pdf_batch_size()

        # If number of bodies/articles exceeds batch_size and not already inside a bodies batch
        if bodies and len(bodies) > batch_size and not self.env.context.get('in_bodies_batch'):
            _logger.info(
                "Large PDF body detected: processing %d HTML bodies in batches of %d",
                len(bodies), batch_size
            )
            chunks = [bodies[i:i + batch_size] for i in range(0, len(bodies), batch_size)]
            workers = min(len(chunks), self._get_pdf_workers())

            results = None
            if workers > 1:
                from concurrent.futures import ThreadPoolExecutor

                registry = self.env.registry

                def _render_chunk(chunk_bodies):
                    with registry.cursor() as cr:
                        env = self.env(cr=cr)
                        return self.with_env(env).with_context(in_bodies_batch=True)._run_wkhtmltopdf(
                            chunk_bodies,
                            report_ref=report_ref,
                            header=header,
                            footer=footer,
                            landscape=landscape,
                            specific_paperformat_args=specific_paperformat_args,
                            set_viewport_size=set_viewport_size,
                        )

                try:
                    with ThreadPoolExecutor(max_workers=workers) as executor:
                        results = list(executor.map(_render_chunk, chunks))
                except Exception as e:
                    _logger.warning("Parallel PDF batching encountered error, falling back to sequential: %s", e)
                    results = None

            if results is None:
                results = []
                for chunk_bodies in chunks:
                    chunk_pdf = self.with_context(in_bodies_batch=True)._run_wkhtmltopdf(
                        chunk_bodies,
                        report_ref=report_ref,
                        header=header,
                        footer=footer,
                        landscape=landscape,
                        specific_paperformat_args=specific_paperformat_args,
                        set_viewport_size=set_viewport_size,
                    )
                    results.append(chunk_pdf)

            pdf_streams = [io.BytesIO(res) for res in results]

            # Automatically combine all generated batches into a single PDF
            with self._merge_pdfs(pdf_streams) as merged_stream:
                return merged_stream.getvalue()

        return super()._run_wkhtmltopdf(
            bodies,
            report_ref=report_ref,
            header=header,
            footer=footer,
            landscape=landscape,
            specific_paperformat_args=specific_paperformat_args,
            set_viewport_size=set_viewport_size,
        )

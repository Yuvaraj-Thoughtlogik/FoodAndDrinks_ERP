# -*- coding: utf-8 -*-
import io
from unittest.mock import patch, MagicMock

from odoo.tests.common import TransactionCase, tagged
from odoo.tools.pdf import PdfFileReader, PdfFileWriter


@tagged('post_install', '-at_install', 'large_pdf_report')
class TestLargePdfBatching(TransactionCase):

    def setUp(self):
        super().setUp()
        self.report_model = self.env['ir.actions.report']

    def _create_sample_pdf_bytes(self, num_pages=1):
        """Helper to create a small valid PDF in memory."""
        writer = PdfFileWriter()
        for _ in range(num_pages):
            writer.addBlankPage(width=595.27, height=841.89)
        stream = io.BytesIO()
        writer.write(stream)
        return stream.getvalue()

    def test_pdf_batch_size_configuration(self):
        """Test default and configured batch size."""
        self.assertEqual(self.report_model._get_pdf_batch_size(), 100)

        # Set custom batch size in ir.config_parameter
        self.env['ir.config_parameter'].sudo().set_param('report.pdf.batch_size', '50')
        self.assertEqual(self.report_model._get_pdf_batch_size(), 50)

        # Reset
        self.env['ir.config_parameter'].sudo().set_param('report.pdf.batch_size', '100')

    def test_res_ids_batching_1000_5000_8000_records(self):
        """Test that large record lists (1000, 5000, 8000) are automatically split, merged and stamped."""
        sample_pdf = self._create_sample_pdf_bytes(num_pages=1)
        batch_sizes_to_test = [1000, 5000, 8000]

        for record_count in batch_sizes_to_test:
            large_res_ids = list(range(1, record_count + 1))
            call_chunks = []

            def mock_super_render(report_ref, res_ids=None, data=None):
                call_chunks.append(res_ids)
                return sample_pdf, 'pdf'

            with patch('odoo.addons.base.models.ir_actions_report.IrActionsReport._render_qweb_pdf', side_effect=mock_super_render):
                with patch.object(self.report_model.__class__, '_get_report', return_value=MagicMock(report_name='test.report', model='res.partner')):
                    pdf_content, report_type = self.report_model.with_context(force_report_rendering=True)._render_qweb_pdf(
                        'test.report', res_ids=large_res_ids
                    )

            self.assertEqual(report_type, 'pdf')
            self.assertTrue(len(pdf_content) > 0, "PDF content must not be empty.")

            # Check that chunks were all <= batch_size (100)
            expected_chunks_count = (record_count + 99) // 100
            self.assertEqual(len(call_chunks), expected_chunks_count)
            for chunk in call_chunks:
                self.assertTrue(len(chunk) <= 100, f"Chunk size {len(chunk)} exceeded batch size 100")

            # Check all record IDs were covered
            flattened = [item for sublist in call_chunks for item in sublist]
            self.assertEqual(flattened, large_res_ids)

            # Check resulting PDF total page count matches chunks
            reader = PdfFileReader(io.BytesIO(pdf_content))
            self.assertEqual(reader.numPages, expected_chunks_count)

    def test_stamp_page_numbers_continuous(self):
        """Test that _stamp_page_numbers stamps continuous running page numbers across all pages."""
        sample_pdf = self._create_sample_pdf_bytes(num_pages=15)
        stamped_pdf = self.report_model._stamp_page_numbers(
            sample_pdf,
            report_ref='tl_rf_reports.report_dock_weight_breakdown'
        )
        self.assertTrue(len(stamped_pdf) > 0)
        reader = PdfFileReader(io.BytesIO(stamped_pdf))
        self.assertEqual(reader.numPages, 15)

    def test_bodies_batching_large_html_pages(self):
        """Test that large HTML bodies lists (e.g. 250 pages) are chunked in wkhtmltopdf."""
        sample_pdf = self._create_sample_pdf_bytes(num_pages=1)
        bodies = [f"<div>Page {i}</div>" for i in range(250)]
        wkhtml_chunks = []

        def mock_super_wkhtml(bodies, **kwargs):
            wkhtml_chunks.append(bodies)
            return sample_pdf

        with patch('odoo.addons.base.models.ir_actions_report.IrActionsReport._run_wkhtmltopdf', side_effect=mock_super_wkhtml):
            result_pdf = self.report_model._run_wkhtmltopdf(bodies)

        self.assertTrue(len(result_pdf) > 0)
        expected_chunks = (len(bodies) + 99) // 100
        self.assertEqual(len(wkhtml_chunks), expected_chunks)
        for chunk in wkhtml_chunks:
            self.assertTrue(len(chunk) <= 100)

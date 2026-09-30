# -*- coding: utf-8 -*-
"""Chilled Product Label - Front Sleeve Label report.

Implements the "CHILLED Product Label – Front Sleeve Label" design.
The label is generated based on products from matching Manufacturing Orders (MOs)
and displays:
- Product Name (Bold, Large, Centered)
- Cooking Instruction (Centered, sourced dynamically from the product's cooking_instructions_html)
- MO Date / Production Date (MO Created Date, formatted e.g. "15 September, 2026")
- Use By / Expiry Date (Calculated as MO Created Date + Product Expiration Duration)
- Hardcoded Disclaimer & Freezing notice (Italic, Left-aligned):
  "Take extra care when opening the film lid as the steam can get very hot!
   Suitable for home freezing, freeze on day of purchase."

DIMENSIONS & PAPER FORMAT:
- Paper Format: 100mm x 60mm Landscape/Thermal Roll format.
- Margins: 0mm paperformat margin, with 3mm inner padding.

NOTE ON TECHNICAL NAME:
The model's technical name (_name) must keep the derived SQL table name
(dots replaced with underscores) at or under PostgreSQL's 63-character
identifier limit. 'report.tl_rf_reports.report_production_label_chilled_front_sleeve'
produces a 65-character table name and is rejected by Postgres with
"Table name '...' is too long". The '_sleeve' suffix was dropped here
(the wizard's chilled_label_type field already distinguishes front vs.
back sleeve for users) to bring the table name down to 58 characters.
"""
import io
import re
from xml.sax.saxutils import escape as xml_escape

from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

from odoo import api, models

from .label_fit import LabelDocTemplate, build_fitted_label, label_cache_key

# --- Chilled Front Sleeve Label page size: 100mm x 60mm standard thermal roll size. ---
PAGE_WIDTH = 100 * mm
PAGE_HEIGHT = 60 * mm
LABEL_MARGIN = 3.0 * mm
PRINTABLE_WIDTH = PAGE_WIDTH - (2 * LABEL_MARGIN)
PRINTABLE_HEIGHT = PAGE_HEIGHT - (2 * LABEL_MARGIN)

# Border color for the box around the Product Name.
TITLE_BOX_COLOR = colors.HexColor('#2E75B6')


def _format_html_to_reportlab(html_text):
    """Converts basic HTML snippet to safe ReportLab XML tags (preserving <b>, <strong>, <i>, <em>)."""
    if not html_text:
        return ''
    text = str(html_text)
    # Normalize <strong> to <b>, <em> to <i>
    text = re.sub(r'<\s*strong\s*>', '<b>', text, flags=re.IGNORECASE)
    text = re.sub(r'<\s*/\s*strong\s*>', '</b>', text, flags=re.IGNORECASE)
    text = re.sub(r'<\s*em\s*>', '<i>', text, flags=re.IGNORECASE)
    text = re.sub(r'<\s*/\s*em\s*>', '</i>', text, flags=re.IGNORECASE)
    # Convert breaks to newline / space
    text = re.sub(r'<\s*br\s*/?\s*>', ' ', text, flags=re.IGNORECASE)
    text = re.sub(r'<\s*/\s*(p|div|li)\s*>', ' ', text, flags=re.IGNORECASE)
    # Strip remaining HTML tags
    text = re.sub(r'<(?!/?(b|i)\b)[^>]+>', '', text, flags=re.IGNORECASE)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


class ProductionLabelReportChilledFrontSleeve(models.AbstractModel):
    _name = 'report.tl_rf_reports.report_production_label_chilled_front'
    _description = 'Production Label Report Data - Chilled Front Sleeve'
    _inherit = 'report.tl_rf_reports.report_production_label_document_courier'

    # Lowest font scale tried when reflowing long content. Below this the
    # label is shrunk as a block, so it still stays on one page.
    MIN_FONT_SCALE = 0.4

    @api.model
    def _get_report_values(self, docids, data=None):
        """Standard QWeb report values generator."""
        wizard = self.env['production.label.wizard'].browse(docids) if docids else False
        if not wizard and data and data.get('wizard_id'):
            wizard = self.env['production.label.wizard'].browse(data['wizard_id'])

        label_lines = wizard._get_chilled_front_sleeve_label_data() if wizard else []
        return {
            'doc_ids': docids,
            'doc_model': 'production.label.wizard',
            'docs': wizard,
            'label_lines': label_lines,
            'company': self.env.company,
        }

    def _chilled_front_sleeve_styles(self, scale=1.0):
        def s(val):
            return val * scale

        bold = 'Helvetica-Bold'
        regular = 'Helvetica'
        italic = 'Helvetica-Oblique'

        return {
            'title': ParagraphStyle(
                'ChilledTitle',
                fontName=bold,
                fontSize=s(14.0),
                leading=s(16.5),
                alignment=1,  # Centered
                textColor=colors.black,
            ),
            'cooking': ParagraphStyle(
                'ChilledCooking',
                fontName=regular,
                fontSize=s(9.2),
                leading=s(11.5),
                alignment=1,  # Centered
                textColor=colors.black,
            ),
            'date_cell': ParagraphStyle(
                'ChilledDateCell',
                fontName=regular,
                fontSize=s(9.2),
                leading=s(12.5),
                alignment=0,  # Left
                textColor=colors.black,
            ),
            'warning_text': ParagraphStyle(
                'ChilledWarning',
                fontName=italic,
                fontSize=s(7.2),
                leading=s(9.0),
                alignment=0,  # Left
                textColor=colors.black,
            ),
        }

    def _chilled_front_sleeve_flowables(self, label, index, total_labels, styles, scale=1.0):
        def gap(val):
            return val * scale * mm

        product_name = xml_escape(label.get('product_name') or '')
        cooking_raw = label.get('cooking_instructions_html') or label.get('cooking_instructions') or ''
        cooking_text = _format_html_to_reportlab(cooking_raw)
        production_date_display = xml_escape(label.get('production_date_display') or '')
        use_by_display = xml_escape(label.get('use_by_display') or '')

        story = []

        # 1. Product Name (Centered Bold, inside a bordered box)
        story.append(Spacer(1, gap(1.0)))
        title_box = Table(
            [[Paragraph(product_name, styles['title'])]],
            colWidths=[PRINTABLE_WIDTH],
        )
        title_box.setStyle(TableStyle([
            ('BOX', (0, 0), (-1, -1), max(0.5, 0.9 * scale), TITLE_BOX_COLOR),
            ('LEFTPADDING', (0, 0), (-1, -1), gap(1.5)),
            ('RIGHTPADDING', (0, 0), (-1, -1), gap(1.5)),
            ('TOPPADDING', (0, 0), (-1, -1), gap(1.0)),
            ('BOTTOMPADDING', (0, 0), (-1, -1), gap(1.0)),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ]))
        story.append(title_box)

        # 2. Cooking Instructions (Centered Regular)
        if cooking_text:
            story.append(Spacer(1, gap(2.0)))
            story.append(Paragraph(cooking_text, styles['cooking']))
        else:
            story.append(Spacer(1, gap(1.5)))

        # 3. Production Date & Use By Date (Left-aligned Table)
        story.append(Spacer(1, gap(2.5)))
        date_data = [
            [
                Paragraph("Production Date:", styles['date_cell']),
                Paragraph(production_date_display, styles['date_cell']),
            ],
            [
                Paragraph("Use By:", styles['date_cell']),
                Paragraph(use_by_display, styles['date_cell']),
            ],
        ]
        col1_w = 32 * mm
        col2_w = PRINTABLE_WIDTH - col1_w
        date_table = Table(date_data, colWidths=[col1_w, col2_w])
        date_table.setStyle(TableStyle([
            ('LEFTPADDING', (0, 0), (-1, -1), 0),
            ('RIGHTPADDING', (0, 0), (-1, -1), 0),
            ('TOPPADDING', (0, 0), (-1, -1), gap(0.2)),
            ('BOTTOMPADDING', (0, 0), (-1, -1), gap(0.2)),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ]))
        story.append(date_table)

        # 4. Hardcoded Warning & Freezing Notice (Italic Left-aligned)
        story.append(Spacer(1, gap(2.5)))
        warning_p1 = "Take extra care when opening the film lid as the steam can get very hot!"
        warning_p2 = "Suitable for home freezing, freeze on day of purchase."
        story.append(Paragraph(warning_p1, styles['warning_text']))
        story.append(Paragraph(warning_p2, styles['warning_text']))

        return story

    def _measure_story_height(self, story, avail_width):
        """Measures total height needed by story flowables."""
        total_height = 0.0
        for flowable in story:
            try:
                _, flowable_height = flowable.wrap(avail_width, 0xFFFFFF)
            except Exception:
                flowable_height = 0
            total_height += flowable_height
        return total_height

    def _build_fitted_story(self, label, index, total_labels, fit_cache=None):
        """Builds the story for one label. Fonts shrink as far as needed so
        the label ALWAYS fits on exactly one 100x60mm page."""
        def build(scale):
            return self._chilled_front_sleeve_flowables(
                label, index, total_labels, self._chilled_front_sleeve_styles(scale), scale
            )
        return build_fitted_label(
            build, PRINTABLE_WIDTH, PRINTABLE_HEIGHT, self.MIN_FONT_SCALE,
            cache=fit_cache, cache_key=label_cache_key(label),
        )

    def generate_pdf(self, wizard, label_lines=None):
        """Returns the finished Chilled Front Sleeve Label PDF bytes."""
        # label_lines is optional: the Production Label wizard passes it (None
        # for non-Fresh labels), and the Product Label wizard does not.
        if label_lines is None:
            label_lines = wizard._get_chilled_front_sleeve_label_data()
        if not label_lines:
            return None

        total_labels = len(label_lines)
        buffer = io.BytesIO()
        doc = LabelDocTemplate(
            buffer,
            pagesize=(PAGE_WIDTH, PAGE_HEIGHT),
            leftMargin=LABEL_MARGIN,
            rightMargin=LABEL_MARGIN,
            topMargin=LABEL_MARGIN,
            bottomMargin=LABEL_MARGIN,
        )

        story = []
        fit_cache = {}
        for index, label in enumerate(label_lines):
            if index:
                story.append(PageBreak())
            story.extend(self._build_fitted_story(label, index, total_labels, fit_cache))

        doc.title = 'Chilled Front Sleeve Labels'  # PDF metadata - shown by browser PDF viewers
        doc.author = self.env.company.name or ''
        doc.build(story)
        pdf_value = buffer.getvalue()
        buffer.close()
        return pdf_value
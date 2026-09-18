# -*- coding: utf-8 -*-
"""Frozen Label report (Category = 'Frozen', Label Format = 'Frozen Label').

Implements only the "Frozen Label" design from the client's Frozen Label
functional spec. "Plain Frozen Label" and "Plain Label" (the other two
Label Format radio options on production.report.wizard) are explicitly out
of scope here - they are covered by separate FSDs, and
production_report_wizard.action_print_label() raises a clear error if
either is selected instead of silently using this layout.

Built the same way as production_label_report.py (direct ReportLab
drawing, no QWeb/wkhtmltopdf, one physical label per PDF page) and renders
the official GB/GG 476 health-mark oval stamp.

LAYOUT & DIMENSIONS:
- Paper Format: 100mm x 50mm landscape/standard thermal packaging roll format.
- Centered top block: Product Name, Scientific Name, Origin, Description, Weight.
- Top-right: Oval GB GG 476 health-mark stamp.
- Middle 2-column block:
    * Left: Storage info, Allergens, Advisory warnings.
    * Right: Production Date and Use By date aligned.
- Footer: Centered full-width company address.
"""
import io
from xml.sax.saxutils import escape as xml_escape

from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.graphics.shapes import Drawing, Ellipse, String
from reportlab.platypus import (
    Paragraph, PageBreak, SimpleDocTemplate, Spacer, Table, TableStyle,
)

from odoo import models

# --- Frozen Label page size: 100mm x 50mm standard thermal roll size. ---
PAGE_WIDTH = 100 * mm
PAGE_HEIGHT = 50 * mm
LABEL_MARGIN = 2 * mm
PRINTABLE_WIDTH = PAGE_WIDTH - (2 * LABEL_MARGIN)
PRINTABLE_HEIGHT = PAGE_HEIGHT - (2 * LABEL_MARGIN)


class ProductionLabelReportFrozen(models.AbstractModel):
    _name = 'report.tl_rf_reports.report_production_label_document_frozen'
    _description = 'Production Label Report Data - Frozen'
    _inherit = 'report.tl_rf_reports.report_production_label_document_courier'

    def _label_circle_flowable(self):
        """Approximates the UK oval health mark: 'GB / GG 476'"""
        w, h = 13 * mm, 9.5 * mm
        d = Drawing(w, h)
        d.add(Ellipse(w / 2, h / 2, (w / 2) - 0.4 * mm, (h / 2) - 0.4 * mm, strokeWidth=0.8, strokeColor=colors.black, fillColor=None))
        d.add(String(w / 2, (h / 2) + 0.6 * mm, "GB", fontName='Helvetica-Bold', fontSize=6.5, textAnchor='middle'))
        d.add(String(w / 2, (h / 2) - 2.2 * mm, "GG 476", fontName='Helvetica-Bold', fontSize=6.5, textAnchor='middle'))
        return d

    def _frozen_label_styles(self):
        base, bold, italic = 'Helvetica', 'Helvetica-Bold', 'Helvetica-Oblique'
        return {
            'title': ParagraphStyle('FrozenTitle', fontName=bold, fontSize=11, leading=12.5, alignment=1),
            'latin_name': ParagraphStyle('FrozenLatinName', fontName=italic, fontSize=7.5, leading=8.5, alignment=1),
            'origin': ParagraphStyle('FrozenOrigin', fontName=base, fontSize=7, leading=8, alignment=1),
            'description': ParagraphStyle('FrozenDescription', fontName=base, fontSize=7, leading=8, alignment=1),
            'weight': ParagraphStyle('FrozenWeight', fontName=bold, fontSize=8, leading=9, alignment=1),
            'body': ParagraphStyle('FrozenBody', fontName=base, fontSize=6.5, leading=7.8, alignment=0),
            'allergen_heading': ParagraphStyle('FrozenAllergenHeading', fontName=base, fontSize=6.5, leading=7.8, alignment=0),
            'footer_address': ParagraphStyle('FrozenFooterAddress', fontName=base, fontSize=5.6, leading=6.8, alignment=1),
            'date_label': ParagraphStyle('FrozenDateLabel', fontName=bold, fontSize=6.8, leading=8.5, alignment=0),
            'date_value': ParagraphStyle('FrozenDateValue', fontName=bold, fontSize=6.8, leading=8.5, alignment=2),
        }

    def _frozen_label_flowables(self, label, index, total_labels, styles):
        product_name = xml_escape(label.get('product_name') or '')
        latin_name = xml_escape(label.get('latin_name') or '')
        origin_display = xml_escape(label.get('origin_display') or '')
        label_description = xml_escape(label.get('label_description') or '')
        weight_range = xml_escape(label.get('weight_range') or '')
        allergens_display = xml_escape(label.get('allergens_display') or '')
        production_date_display = xml_escape(label.get('production_date_display') or '')
        use_by_display = xml_escape(label.get('frozen_use_by_display') or '')

        story = []

        # --- Top block: Product Name / Scientific Name / Origin / Description / Weight + Oval ---
        text_col = [Paragraph(product_name, styles['title'])]
        if latin_name:
            text_col.append(Paragraph(f"<i>({latin_name})</i>", styles['latin_name']))
        if origin_display:
            text_col.append(Paragraph(origin_display, styles['origin']))
        if label_description:
            text_col.append(Paragraph(label_description, styles['description']))
        if weight_range:
            text_col.append(Paragraph(weight_range, styles['weight']))

        header_table = Table(
            [[text_col, self._label_circle_flowable()]],
            colWidths=[PRINTABLE_WIDTH - 14 * mm, 14 * mm],
        )
        header_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
            ('LEFTPADDING', (0, 0), (-1, -1), 0),
            ('RIGHTPADDING', (0, 0), (-1, -1), 0),
            ('TOPPADDING', (0, 0), (-1, -1), 0),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
        ]))
        story.append(header_table)
        story.append(Spacer(1, 0.8 * mm))

        # --- Middle block: 2 Columns (Left: Storage/Allergens/Advisory, Right: Production/Use By) ---
        allergen_val = allergens_display or 'Fish'
        left_col = [
            Paragraph("Store at or below 5°C.", styles['body']),
            Paragraph("Suitable for home freezing. For best results freeze on day of purchase.", styles['body']),
            Paragraph(f"Allergens: <b>{allergen_val}</b>", styles['allergen_heading']),
            Paragraph("May contain bones.", styles['body']),
            Paragraph("Remove all outer packaging prior to cooking.", styles['body']),
        ]

        date_rows = [
            [Paragraph("Production Date:", styles['date_label']), Paragraph(production_date_display, styles['date_value'])],
            [Paragraph("Use by:", styles['date_label']), Paragraph(use_by_display, styles['date_value'])],
        ]
        date_col_w = PRINTABLE_WIDTH * 0.42
        date_table = Table(date_rows, colWidths=[date_col_w * 0.46, date_col_w * 0.54])
        date_table.setStyle(TableStyle([
            ('LEFTPADDING', (0, 0), (-1, -1), 0),
            ('RIGHTPADDING', (0, 0), (-1, -1), 0),
            ('TOPPADDING', (0, 0), (-1, -1), 0.3 * mm),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 0.3 * mm),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ]))

        mid_table = Table(
            [[left_col, date_table]],
            colWidths=[PRINTABLE_WIDTH * 0.58, date_col_w],
        )
        mid_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (0, 0), 'TOP'),
            ('VALIGN', (1, 0), (1, 0), 'BOTTOM'),
            ('LEFTPADDING', (0, 0), (-1, -1), 0),
            ('RIGHTPADDING', (0, 0), (-1, -1), 0),
            ('TOPPADDING', (0, 0), (-1, -1), 0),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
        ]))
        story.append(mid_table)
        story.append(Spacer(1, 0.8 * mm))

        # --- Footer: company address (dynamic), centered, full width -----
        company = self.env.company
        address_parts = [
            company.name,
            company.street,
            company.street2,
            company.city,
            company.state_id.name if company.state_id else False,
            company.zip,
        ]
        address_line = xml_escape(', '.join(part for part in address_parts if part))
        if address_line and not address_line.endswith('.'):
            address_line += '.'
        story.append(Paragraph(address_line, styles['footer_address']))

        return story

    def generate_pdf(self, wizard):
        """Returns the finished Frozen Label PDF (bytes), or None if there
        is nothing to print. One physical label per page at the 100mm x 50mm
        size."""
        label_lines = wizard._get_label_data()
        if not label_lines:
            return None

        styles = self._frozen_label_styles()
        total_labels = len(label_lines)

        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer, pagesize=(PAGE_WIDTH, PAGE_HEIGHT),
            leftMargin=LABEL_MARGIN, rightMargin=LABEL_MARGIN,
            topMargin=LABEL_MARGIN, bottomMargin=LABEL_MARGIN,
        )

        story = []
        for index, label in enumerate(label_lines):
            if index:
                story.append(PageBreak())
            story.extend(self._frozen_label_flowables(label, index, total_labels, styles))

        doc.build(story)
        pdf_value = buffer.getvalue()
        buffer.close()
        return pdf_value
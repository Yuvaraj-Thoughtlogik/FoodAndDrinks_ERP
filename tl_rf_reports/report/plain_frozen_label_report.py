# -*- coding: utf-8 -*-
"""Plain Frozen Product Label report (Category = 'Frozen', Label Format = 'Plain Frozen Label').

Implements the "Plain Frozen Product Label" design from the client's specification.
The label is generated based on products from matching Manufacturing Orders (MOs)
and displays:
- Product Name
- Latin / Scientific Name / Origin
- Ingredients (with bold allergens)
- Storage Instructions
- Catch Area
- Allergen Information Notice
- Advisory Notice
- Freeze Date (MO Created Date in DD.MM.YYYY format)
- Best Before Date (Calculated from MO Created Date + Product Expiration Duration)
- Official GB GG476 Oval Health Mark Stamp
- Company Address Footer

DIMENSIONS & PAPER FORMAT:
- Paper Format: 100mm x 130mm Portrait standard thermal label roll format.
- Margin: 3mm inner padding (0mm paperformat margin).
"""
import io
import re
from xml.sax.saxutils import escape as xml_escape

from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.graphics.shapes import Drawing, Ellipse, String
from reportlab.platypus import (
    Paragraph, PageBreak, SimpleDocTemplate, Spacer, Table, TableStyle,
)

from odoo import models

from .label_fit import LabelDocTemplate, build_fitted_label, label_cache_key

# --- Plain Frozen Label page size: 100mm x 130mm Portrait standard thermal roll size. ---
PAGE_WIDTH = 100 * mm
PAGE_HEIGHT = 130 * mm
LABEL_MARGIN = 3.5 * mm
PRINTABLE_WIDTH = PAGE_WIDTH - (2 * LABEL_MARGIN)
PRINTABLE_HEIGHT = PAGE_HEIGHT - (2 * LABEL_MARGIN)


class ProductionLabelReportPlainFrozen(models.AbstractModel):
    _name = 'report.tl_rf_reports.report_production_label_plain_frozen'
    _description = 'Production Label Report Data - Plain Frozen Label'
    _inherit = 'report.tl_rf_reports.report_production_label_document_courier'

    # Lowest font scale tried when reflowing long content. Below this the
    # label is shrunk as a block, so it still stays on one page.
    MIN_FONT_SCALE = 0.4

    def _label_circle_flowable(self, scale=1.0):
        """Draws the official UK health mark oval stamp: 'GB / GG476'"""
        w, h = 22 * mm * scale, 14 * mm * scale
        d = Drawing(w, h)
        d.add(Ellipse(
            w / 2, h / 2,
            (w / 2) - 0.5 * mm * scale, (h / 2) - 0.5 * mm * scale,
            strokeWidth=max(0.6, 1.0 * scale), strokeColor=colors.black, fillColor=None,
        ))
        d.add(String(w / 2, (h / 2) + 1.2 * mm * scale, "GB", fontName='Helvetica-Bold', fontSize=10 * scale, textAnchor='middle'))
        d.add(String(w / 2, (h / 2) - 2.8 * mm * scale, "GG476", fontName='Helvetica-Bold', fontSize=10 * scale, textAnchor='middle'))
        return d

    def _plain_frozen_label_styles(self, scale=1.0):
        """Paragraph styles. `scale` multiplies every font size / leading so
        long content can be shrunk to fit the fixed 100mm x 130mm label."""
        base, bold, italic = 'Helvetica', 'Helvetica-Bold', 'Helvetica-Oblique'

        def sz(value):
            return value * scale

        return {
            'title': ParagraphStyle('PlainFrozenTitle', fontName=bold, fontSize=sz(16), leading=sz(19), alignment=1, textColor=colors.black),
            'latin_name': ParagraphStyle('PlainFrozenLatin', fontName=base, fontSize=sz(12), leading=sz(15), alignment=1, textColor=colors.black),
            'ingredients': ParagraphStyle('PlainFrozenIng', fontName=base, fontSize=sz(10.5), leading=sz(13.5), alignment=0, textColor=colors.black),
            'storage': ParagraphStyle('PlainFrozenStorage', fontName=base, fontSize=sz(10.5), leading=sz(13.5), alignment=0, textColor=colors.black),
            'catch_area': ParagraphStyle('PlainFrozenCatch', fontName=base, fontSize=sz(10.5), leading=sz(13.5), alignment=0, textColor=colors.black),
            'allergen_info': ParagraphStyle('PlainFrozenAllergen', fontName=base, fontSize=sz(10.5), leading=sz(13.5), alignment=0, textColor=colors.black),
            'advisory': ParagraphStyle('PlainFrozenAdv', fontName=italic, fontSize=sz(10), leading=sz(13), alignment=1, textColor=colors.black),
            'date_label': ParagraphStyle('PlainFrozenDate', fontName=base, fontSize=sz(10.5), leading=sz(14), alignment=0, textColor=colors.black),
            'footer': ParagraphStyle('PlainFrozenFooter', fontName=base, fontSize=sz(7.5), leading=sz(9.5), alignment=1, textColor=colors.black),
        }

    def _format_html_to_reportlab(self, html_text):
        """Converts basic HTML snippet to safe ReportLab XML tags (preserving <b>, <strong> -> <b>)."""
        if not html_text:
            return ''
        text = str(html_text)
        # Normalize <strong> to <b>
        text = re.sub(r'<\s*strong\s*>', '<b>', text, flags=re.IGNORECASE)
        text = re.sub(r'<\s*/\s*strong\s*>', '</b>', text, flags=re.IGNORECASE)
        # Remove paragraphs, divs, breaks
        text = re.sub(r'<\s*p[^>]*>', '', text, flags=re.IGNORECASE)
        text = re.sub(r'<\s*/\s*p\s*>', ' ', text, flags=re.IGNORECASE)
        text = re.sub(r'<\s*div[^>]*>', '', text, flags=re.IGNORECASE)
        text = re.sub(r'<\s*/\s*div\s*>', ' ', text, flags=re.IGNORECASE)
        text = re.sub(r'<\s*br\s*/?\s*>', ' ', text, flags=re.IGNORECASE)
        text = re.sub(r'\s+', ' ', text).strip()
        return text

    def _plain_frozen_label_flowables(self, label, index, total_labels, styles, scale=1.0):
        def gap(mm_value):
            return mm_value * mm * scale

        product_name = xml_escape((label.get('product_name') or '').upper())
        latin_name = xml_escape(label.get('latin_name') or label.get('origin') or '')
        ingredients_raw = label.get('ingredients') or label.get('ingredients_display') or ''
        storage_instructions = xml_escape(label.get('storage_instructions') or 'Store at below -18°C.  Once defrosted do not refreeze')
        catch_area = xml_escape(label.get('catch_area') or 'Catch Area: Longline caught in the Pacific Ocean, FAO 61.')
        freeze_date_display = xml_escape(label.get('freeze_date_display') or '')
        best_before_display = xml_escape(label.get('best_before_display') or '')
        company_address = xml_escape(label.get('company_address') or 'Regal Fish Supplies Ltd, Thorold Street, Grimsby, DN31 3AL')

        story = []

        # 1. Product Name (Large bold, uppercase, centered)
        story.append(Paragraph(product_name, styles['title']))
        story.append(Spacer(1, gap(1.5)))

        # 2. Origin / Latin Name: (Gadus macrocephalus) (centered)
        if latin_name:
            if not latin_name.startswith('(') and not latin_name.endswith(')'):
                latin_name = f"({latin_name})"
            story.append(Paragraph(latin_name, styles['latin_name']))
        story.append(Spacer(1, gap(3.5)))

        # 3. Ingredients: Cod (FISH), water as protective glaze.
        # Format ingredients safely with <b> tags
        formatted_ing = self._format_html_to_reportlab(ingredients_raw)
        if not formatted_ing:
            formatted_ing = f"Cod <b>(FISH)</b>, water as protective glaze."
        if not formatted_ing.lower().startswith('ingredients:'):
            formatted_ing = f"Ingredients: {formatted_ing}"
        story.append(Paragraph(formatted_ing, styles['ingredients']))
        story.append(Spacer(1, gap(3.5)))

        # 4. Storage instructions: Store at below -18°C.  Once defrosted do not refreeze
        story.append(Paragraph(storage_instructions, styles['storage']))
        story.append(Spacer(1, gap(3.5)))

        # 5. Catch Area: Longline caught in the Pacific Ocean, FAO 61.
        if not catch_area.lower().startswith('catch area:'):
            catch_area = f"Catch Area: {catch_area}"
        story.append(Paragraph(catch_area, styles['catch_area']))
        story.append(Spacer(1, gap(3.5)))

        # 6. Allergen Information: For allergens see ingredients in BOLD
        allergen_notice = "For allergens see ingredients in <b>BOLD</b>"
        story.append(Paragraph(allergen_notice, styles['allergen_info']))
        story.append(Spacer(1, gap(4)))

        # 7. Advisory notice: Although every effort has been taken to remove them, this product may contain bones
        advisory_text = "Although every effort has been taken to remove them, this product may contain bones"
        story.append(Paragraph(advisory_text, styles['advisory']))
        story.append(Spacer(1, gap(3.5)))

        # 8. Bottom block: Left side (Freeze Date & Best Before End) & Right side (GB GG476 Oval stamp)
        dates_col = [
            Paragraph(f"Freeze date: {freeze_date_display}", styles['date_label']),
            Paragraph(f"Best Before End: {best_before_display}", styles['date_label']),
        ]

        oval_flow = self._label_circle_flowable(scale)

        stamp_col_w = 24 * mm * scale
        bottom_table = Table(
            [[dates_col, oval_flow]],
            colWidths=[PRINTABLE_WIDTH - stamp_col_w, stamp_col_w],
        )
        bottom_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
            ('LEFTPADDING', (0, 0), (-1, -1), 0),
            ('RIGHTPADDING', (0, 0), (-1, -1), 0),
            ('TOPPADDING', (0, 0), (-1, -1), 0),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
        ]))
        story.append(bottom_table)
        story.append(Spacer(1, gap(3.5)))

        # 9. Footer: Regal Fish Supplies Ltd, Thorold Street, Grimsby, DN31 3AL
        story.append(Paragraph(company_address, styles['footer']))

        return story

    def generate_pdf(self, wizard):
        """Returns the finished Plain Frozen Label PDF (bytes), or None if there
        is nothing to print. One physical label per page at the 100mm x 130mm
        size. Long content is shrunk to fit that one page."""
        label_lines = wizard._get_plain_frozen_label_data()
        if not label_lines:
            return None

        total_labels = len(label_lines)

        buffer = io.BytesIO()
        doc = LabelDocTemplate(
            buffer, pagesize=(PAGE_WIDTH, PAGE_HEIGHT),
            leftMargin=LABEL_MARGIN, rightMargin=LABEL_MARGIN,
            topMargin=LABEL_MARGIN, bottomMargin=LABEL_MARGIN,
        )

        story = []
        fit_cache = {}
        for index, label in enumerate(label_lines):
            if index:
                story.append(PageBreak())

            def build(scale, label=label, index=index):
                return self._plain_frozen_label_flowables(
                    label, index, total_labels, self._plain_frozen_label_styles(scale), scale
                )
            story.extend(build_fitted_label(
                build, PRINTABLE_WIDTH, PRINTABLE_HEIGHT, self.MIN_FONT_SCALE,
                cache=fit_cache, cache_key=label_cache_key(label),
            ))

        doc.title = 'Plain Frozen Labels'  # PDF metadata - shown by browser PDF viewers
        doc.author = self.env.company.name or ''
        doc.build(story)
        pdf_value = buffer.getvalue()
        buffer.close()
        return pdf_value
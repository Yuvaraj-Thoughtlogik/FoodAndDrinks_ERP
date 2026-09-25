# -*- coding: utf-8 -*-
"""Chilled Product Label - Back Sleeve Label report.

Implements the "CHILLED Product Label – Back Sleeve Label" design.
The label is generated based on products from matching Manufacturing Orders (MOs)
and displays:
- Product Name (Bold, Large, Centered)
- Ingredients (with bold allergens and scientific name in italics)
- Allergy Advice (with bold allergen references)
- Cooking Instruction (Oven and Microwave instructions)
- Bottom Section:
  - Left: Official GB GG476 Oval Health Mark Stamp + Product Weight (e.g. 250g) from MO
  - Right: Nutritional Information Table with clear grid borders

DIMENSIONS & PAPER FORMAT:
- Paper Format: 100mm x 75mm Portrait/Landscape standard thermal label roll format.
- Margins: 0mm paperformat margin, with 2.0mm inner padding.

NOTE ON TECHNICAL NAME:
The model's technical name (_name) must keep the derived SQL table name
(dots replaced with underscores) at or under PostgreSQL's 63-character
identifier limit. 'report.tl_rf_reports.report_production_label_chilled_back'
produces a 57-character table name, well within PostgreSQL's limit.
"""
import io
import re
from xml.sax.saxutils import escape as xml_escape

from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.graphics.shapes import Drawing, Ellipse, String
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    BaseDocTemplate, Frame, PageTemplate, PageBreak, Paragraph,
    SimpleDocTemplate, Spacer, Table, TableStyle,
)

from odoo import api, models

# --- Chilled Back Sleeve Label page size: 100mm x 75mm standard thermal sleeve label size. ---
PAGE_WIDTH = 100 * mm
PAGE_HEIGHT = 75 * mm
LABEL_MARGIN = 2.0 * mm
PRINTABLE_WIDTH = PAGE_WIDTH - (2 * LABEL_MARGIN)
PRINTABLE_HEIGHT = PAGE_HEIGHT - (2 * LABEL_MARGIN)


def _do_nothing(canvas_obj, doc):
    pass


class _ChilledBackLabelDocTemplate(SimpleDocTemplate):
    """Builds the doc template with zero-padding frame so measured dimensions match drawn dimensions."""

    def build(self, flowables, onFirstPage=_do_nothing, onLaterPages=_do_nothing, canvasmaker=canvas.Canvas):
        self._calc()
        frameT = Frame(
            self.leftMargin, self.bottomMargin, self.width, self.height,
            id='normal', leftPadding=0, bottomPadding=0, rightPadding=0, topPadding=0,
        )
        self.addPageTemplates([
            PageTemplate(id='First', frames=frameT, onPage=onFirstPage, pagesize=self.pagesize),
            PageTemplate(id='Later', frames=frameT, onPage=onLaterPages, pagesize=self.pagesize),
        ])
        BaseDocTemplate.build(self, flowables, canvasmaker=canvasmaker)


def _label_circle_flowable(scale=1.0):
    """Draws the official UK health mark oval stamp: 'GB / GG476'"""
    w, h = 19 * mm * scale, 11 * mm * scale
    d = Drawing(w, h)
    d.add(Ellipse(
        w / 2, h / 2,
        (w / 2) - (0.4 * mm * scale), (h / 2) - (0.4 * mm * scale),
        strokeWidth=max(0.6, 0.8 * scale), strokeColor=colors.black, fillColor=None,
    ))
    font_size = 7.5 * scale
    d.add(String(w / 2, (h / 2) + (0.9 * mm * scale), "GB", fontName='Helvetica-Bold', fontSize=font_size,
                 textAnchor='middle'))
    d.add(String(w / 2, (h / 2) - (2.4 * mm * scale), "GG476", fontName='Helvetica-Bold', fontSize=font_size,
                 textAnchor='middle'))
    return d


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
    # Convert breaks and paragraphs to line breaks
    text = re.sub(r'<\s*br\s*/?\s*>', '<br/>', text, flags=re.IGNORECASE)
    text = re.sub(r'<\s*/\s*(p|div|li)\s*>', '<br/>', text, flags=re.IGNORECASE)
    text = re.sub(r'<\s*(p|div|li)[^>]*>', '', text, flags=re.IGNORECASE)
    # Strip remaining HTML tags except <b>, <i>, <br/>
    text = re.sub(r'<(?!/?(b|i|br)\b)[^>]+>', '', text, flags=re.IGNORECASE)
    # Clean up double linebreaks or trailing linebreaks
    text = re.sub(r'(<br/>\s*)+', '<br/>', text)
    text = re.sub(r'^(<br/>)+|(<br/>)+$', '', text)
    text = text.strip()
    return text


def _format_field_to_reportlab(value):
    """Formats a backend Text or Html field value for a ReportLab Paragraph.

    Html values keep their <b>/<i>/<br/> formatting; plain Text values are
    escaped and their line breaks are kept as <br/>.
    """
    if not value:
        return ''
    text = str(value)
    if re.search(r'<[a-zA-Z/][^>]*>', text):
        return _format_html_to_reportlab(text)
    lines = [xml_escape(line.strip()) for line in text.splitlines()]
    return '<br/>'.join(line for line in lines if line)


class ProductionLabelReportChilledBackSleeve(models.AbstractModel):
    _name = 'report.tl_rf_reports.report_production_label_chilled_back'
    _description = 'Production Label Report Data - Chilled Back Sleeve'
    _inherit = 'report.tl_rf_reports.report_production_label_document_courier'

    MIN_FONT_SCALE = 0.65

    @api.model
    def _get_report_values(self, docids, data=None):
        """Standard QWeb report values generator."""
        wizard = self.env['production.label.wizard'].browse(docids) if docids else False
        if not wizard and data and data.get('wizard_id'):
            wizard = self.env['production.label.wizard'].browse(data['wizard_id'])

        label_lines = wizard._get_chilled_back_sleeve_label_data() if wizard else []
        return {
            'doc_ids': docids,
            'doc_model': 'production.label.wizard',
            'docs': wizard,
            'label_lines': label_lines,
            'company': self.env.company,
        }

    def _chilled_back_sleeve_styles(self, scale=1.0):
        def s(val):
            return val * scale

        bold = 'Helvetica-Bold'
        regular = 'Helvetica'
        italic = 'Helvetica-Oblique'

        return {
            'title': ParagraphStyle(
                'ChilledBackTitle',
                fontName=bold,
                fontSize=s(13.5),
                leading=s(15.0),
                alignment=1,  # Centered
                textColor=colors.black,
            ),
            'body': ParagraphStyle(
                'ChilledBackBody',
                fontName=regular,
                fontSize=s(6.2),
                leading=s(7.4),
                alignment=0,  # Left
                textColor=colors.black,
            ),
            'weight': ParagraphStyle(
                'ChilledBackWeight',
                fontName=bold,
                fontSize=s(12.0),
                leading=s(13.5),
                alignment=1,  # Centered
                textColor=colors.black,
            ),
            'nutri_title': ParagraphStyle(
                'ChilledBackNutriTitle',
                fontName=bold,
                fontSize=s(5.6),
                leading=s(6.6),
                alignment=1,  # Centered
                textColor=colors.black,
            ),
            'nutri_subhead': ParagraphStyle(
                'ChilledBackNutriSubhead',
                fontName=regular,
                fontSize=s(5.3),
                leading=s(6.3),
                alignment=1,  # Centered
                textColor=colors.black,
            ),
            'nutri_cell_left': ParagraphStyle(
                'ChilledBackNutriCellLeft',
                fontName=regular,
                fontSize=s(5.3),
                leading=s(6.3),
                alignment=0,  # Left
                textColor=colors.black,
            ),
            'nutri_cell_sub_left': ParagraphStyle(
                'ChilledBackNutriCellSubLeft',
                fontName=regular,
                fontSize=s(5.3),
                leading=s(6.3),
                alignment=0,  # Left
                leftIndent=s(1.5 * mm),
                textColor=colors.black,
            ),
            'nutri_cell_right': ParagraphStyle(
                'ChilledBackNutriCellRight',
                fontName=regular,
                fontSize=s(5.3),
                leading=s(6.3),
                alignment=0,  # Left
                textColor=colors.black,
            ),
        }

    def _chilled_back_sleeve_flowables(self, label, index, total_labels, styles, scale=1.0):
        def gap(val):
            return val * scale * mm

        product_name = xml_escape(label.get('product_name') or '')

        # 1. Ingredients text
        ingredients_raw = label.get('ingredients_html') or label.get('ingredients') or ''
        ingredients_formatted = _format_html_to_reportlab(ingredients_raw)
        # if not ingredients_formatted:
        #     ingredients_formatted = "<b>Ingredients:</b> Salmon (<i>Salmo Salar</i>) (<b>Fish</b>) 90%, Mint Glaze 10%, Sugar, Acids (Sodium Diacetate, Malic Acid), Dried Glucose Syrup, Modified Starch, Salt, Dried Mint (3.6%), Yeast Extract (Yeast Extract, Salt), Dried Tomato, Colours (Paprika Extract and Natural Rosemary Flavouring, Curcumin), Natural Flavouring, Thickeners (Xanthan Gum, Guar Gum) Natural Garden Mint Flavouring."
        # elif not ingredients_formatted.lower().startswith(
        #         '<b>ingredients') and not ingredients_formatted.lower().startswith('ingredients'):
        #     ingredients_formatted = f"<b>Ingredients:</b> {ingredients_formatted}"

        # 2. Allergy Advice - from the product's allergens_notice field (no hardcoded text)
        allergy_formatted = _format_field_to_reportlab(label.get('allergy_advice') or '')
        if allergy_formatted and not re.sub(r'<[^>]+>', '', allergy_formatted).strip().lower().startswith(
                'allergy advice'):
            allergy_formatted = f"<b>Allergy Advice:</b> {allergy_formatted}"

        # 3. Cooking Instructions
        cooking_raw = label.get('cooking_instructions_html') or label.get('cooking_instructions') or ''
        cooking_formatted = _format_html_to_reportlab(cooking_raw)
        # if not cooking_formatted:
        #     cooking_formatted = (
        #         "<b>Oven:</b> Pierce film and place in a pre-heated oven at 200°C for approx 20-25 minutes (chilled), 25-30 minutes (frozen).<br/>"
        #         "<b>Microwave: (850w):</b> Pierce film several times and cook on full power for 3-4 minutes (chilled), 5-6 minutes (frozen).<br/>"
        #         "Remove from packaging and serve."
        #     )

        # 4. Weight
        weight_display = xml_escape(label.get('product_weight_display') or label.get('weight_display') or '250g')

        # 5. Nutritional Info - from the product's nutritional_info_html field (no hardcoded values)
        nutrition_formatted = _format_field_to_reportlab(label.get('nutrition_html') or '')

        story = []

        # 1. Product Name (Centered Bold)
        story.append(Paragraph(product_name, styles['title']))
        story.append(Spacer(1, gap(0.8)))

        # 2. Ingredients Section
        story.append(Paragraph(ingredients_formatted, styles['body']))
        story.append(Spacer(1, gap(0.6)))

        # 3. Allergy Advice Section
        if allergy_formatted:
            story.append(Paragraph(allergy_formatted, styles['body']))
            story.append(Spacer(1, gap(0.6)))

        # 4. Cooking Instructions Section
        story.append(Paragraph(cooking_formatted, styles['body']))
        story.append(Spacer(1, gap(1.0)))

        # 5. Bottom Section (2 Columns: Left = GB Oval + Weight, Right = Nutrition Table)
        left_width = 38 * mm * scale
        right_width = PRINTABLE_WIDTH - left_width

        # Left Flowables
        stamp = _label_circle_flowable(scale=scale)
        left_table_data = [
            [stamp],
            [Spacer(1, gap(1.0))],
            [Paragraph(weight_display, styles['weight'])],
        ]
        left_table = Table(left_table_data, colWidths=[left_width])
        left_table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('LEFTPADDING', (0, 0), (-1, -1), 0),
            ('RIGHTPADDING', (0, 0), (-1, -1), 0),
            ('TOPPADDING', (0, 0), (-1, -1), 0),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
        ]))

        # Right Nutrition Table: header row + one cell holding the backend
        # nutritional_info_html text as a paragraph.
        nutri_table_data = [
            [Paragraph("Nutritional Information", styles['nutri_title'])],
            [Paragraph(nutrition_formatted, styles['nutri_cell_left'])],
        ]

        pad = max(0.2, 0.4 * scale)
        nutri_table = Table(nutri_table_data, colWidths=[right_width])
        nutri_table.setStyle(TableStyle([
            ('GRID', (0, 0), (-1, -1), max(0.4, 0.5 * scale), colors.black),
            ('ALIGN', (0, 0), (0, 0), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('LEFTPADDING', (0, 0), (-1, -1), 1.0 * scale),
            ('RIGHTPADDING', (0, 0), (-1, -1), 1.0 * scale),
            ('TOPPADDING', (0, 0), (-1, -1), pad),
            ('BOTTOMPADDING', (0, 0), (-1, -1), pad),
        ]))

        bottom_table = Table([[left_table, nutri_table]], colWidths=[left_width, right_width])
        bottom_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'BOTTOM'),
            ('LEFTPADDING', (0, 0), (-1, -1), 0),
            ('RIGHTPADDING', (0, 0), (-1, -1), 0),
            ('TOPPADDING', (0, 0), (-1, -1), 0),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
        ]))
        story.append(bottom_table)

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

    def _build_fitted_story(self, label, index, total_labels):
        """Builds story for one label, scaling down if needed to fit exactly one 100x75mm label."""
        scale = 1.0
        story = self._chilled_back_sleeve_flowables(
            label, index, total_labels, self._chilled_back_sleeve_styles(scale), scale
        )

        for _ in range(6):
            height = self._measure_story_height(story, PRINTABLE_WIDTH)
            if height <= PRINTABLE_HEIGHT:
                return story
            if scale <= self.MIN_FONT_SCALE:
                return story
            ratio = PRINTABLE_HEIGHT / height
            scale = max(self.MIN_FONT_SCALE, scale * ratio * 0.98)
            story = self._chilled_back_sleeve_flowables(
                label, index, total_labels, self._chilled_back_sleeve_styles(scale), scale
            )

        return story

    def generate_pdf(self, wizard):
        """Returns the finished Chilled Back Sleeve Label PDF bytes."""
        label_lines = wizard._get_chilled_back_sleeve_label_data()
        if not label_lines:
            return None

        total_labels = len(label_lines)
        buffer = io.BytesIO()
        doc = _ChilledBackLabelDocTemplate(
            buffer,
            pagesize=(PAGE_WIDTH, PAGE_HEIGHT),
            leftMargin=LABEL_MARGIN,
            rightMargin=LABEL_MARGIN,
            topMargin=LABEL_MARGIN,
            bottomMargin=LABEL_MARGIN,
        )

        story = []
        for index, label in enumerate(label_lines):
            if index:
                story.append(PageBreak())
            story.extend(self._build_fitted_story(label, index, total_labels))

        doc.build(story)
        pdf_value = buffer.getvalue()
        buffer.close()
        return pdf_value
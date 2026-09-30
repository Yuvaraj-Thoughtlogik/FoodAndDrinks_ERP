# -*- coding: utf-8 -*-
"""Plain Product Label report (Category = 'Frozen', Label Format = 'Plain Label').

Implements the "Plain Frozen Product Label - Plain label" design from the client's specification.
The label is generated based on products from matching Manufacturing Orders (MOs)
and displays:
- Green rounded-corner outer border (#008000 / #007A3D)
- Product Name (Large bold green centered header, with subtitle/second line if present)
- Cooking Instruction (sourced live from the product's cooking_instructions_html field)
- Ingredients (sourced live from the product's ingredients_html field, with bold allergens)
- Hardcoded Allergen Notice: "Allergens including Gluten are in Bold" (fixed legal text, not a product field)
- Hardcoded Advisory Notice: "Although every effort has been made to remove bones, some may remain." (fixed legal text, not a product field)
- Fish Catch Area / Origin info (sourced live from the product's fish_info field)
- Hardcoded Storage Notice: "Store at or below 5°C." (Bold, fixed legal text, not a product field)
- Hardcoded Freezing Notice: "Use by date shown on label or if freezing we recommend freezing on day of purchase." (Bold, fixed legal text, not a product field)
- Bottom Left: Production Date (MO Created Date), Use By Date (MO Created Date + Product Expiration Duration), Min Weight (Bold) - all sourced live, no hardcoded defaults
- Bottom Middle: Nutrition Table (sourced live from the product's Nutrition
  field - product.nutritional_info_html / product.template.nutritional_info_html -
  no hardcoded/fabricated nutrition values)
- Bottom Right: Official GB GG476 Oval Health Mark Stamp
- Footer: Company Address (sourced live from the company record, no hardcoded address text)

DIMENSIONS & PAPER FORMAT:
- Paper Format: 100mm x 130mm Portrait standard thermal label roll format.
- Margins: 0mm paperformat margin, with 2.5mm outer padding and green rounded border.
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
    BaseDocTemplate, Frame, PageTemplate, Paragraph, PageBreak,
    SimpleDocTemplate, Spacer, Table, TableStyle,
)

from odoo import api, models

from .label_fit import build_fitted_label, label_cache_key

# --- Plain Label page size: 100mm x 130mm Portrait standard thermal roll size. ---
PAGE_WIDTH = 100 * mm
PAGE_HEIGHT = 130 * mm
LABEL_MARGIN = 2.5 * mm
INNER_PADDING = 2.0 * mm
PRINTABLE_WIDTH = PAGE_WIDTH - (2 * (LABEL_MARGIN + INNER_PADDING))
PRINTABLE_HEIGHT = PAGE_HEIGHT - (2 * (LABEL_MARGIN + INNER_PADDING))

GREEN_COLOR = colors.HexColor('#008000')


def _label_circle_flowable(scale=1.0):
    """Draws the official UK health mark oval stamp: 'GB / GG476'"""
    w, h = 18 * mm * scale, 12 * mm * scale
    d = Drawing(w, h)
    d.add(Ellipse(
        w / 2, h / 2,
        (w / 2) - 0.4 * mm * scale, (h / 2) - 0.4 * mm * scale,
        strokeWidth=max(0.6, 1.0 * scale), strokeColor=colors.black, fillColor=None,
    ))
    d.add(String(w / 2, (h / 2) + 0.8 * mm * scale, "GB", fontName='Helvetica-Bold', fontSize=8 * scale, textAnchor='middle'))
    d.add(String(w / 2, (h / 2) - 2.8 * mm * scale, "GG476", fontName='Helvetica-Bold', fontSize=8 * scale, textAnchor='middle'))
    return d


def _format_html_to_reportlab(html_text):
    """Converts basic HTML snippet to safe ReportLab XML tags (preserving <b>, <strong> -> <b>)."""
    if not html_text:
        return ''
    text = str(html_text)
    # Normalize <strong> to <b>
    text = re.sub(r'<\s*strong\s*>', '<b>', text, flags=re.IGNORECASE)
    text = re.sub(r'<\s*/\s*strong\s*>', '</b>', text, flags=re.IGNORECASE)
    text = re.sub(r'<\s*em\s*>', '<i>', text, flags=re.IGNORECASE)
    text = re.sub(r'<\s*/\s*em\s*>', '</i>', text, flags=re.IGNORECASE)
    # Remove paragraphs, divs, breaks
    text = re.sub(r'<\s*p[^>]*>', '', text, flags=re.IGNORECASE)
    text = re.sub(r'<\s*/\s*p\s*>', ' ', text, flags=re.IGNORECASE)
    text = re.sub(r'<\s*div[^>]*>', '', text, flags=re.IGNORECASE)
    text = re.sub(r'<\s*/\s*div\s*>', ' ', text, flags=re.IGNORECASE)
    text = re.sub(r'<\s*br\s*/?\s*>', ' ', text, flags=re.IGNORECASE)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def _split_html_into_lines(html_text):
    """Splits a free-form HTML snippet (e.g. the product's Nutrition field)
    into a list of separate text lines, converting basic formatting tags
    (<b>/<strong>, <i>/<em>) to ReportLab-safe tags and treating <br>,
    </p>, </div>, </li> and heading close tags as line breaks. Unlike
    _format_html_to_reportlab (which collapses everything into one running
    paragraph), this keeps each line/row of the source field on its own
    line so multi-line content - e.g. one nutrient per line - still reads
    as a stacked list rather than one long sentence."""
    if not html_text:
        return []
    text = str(html_text)
    text = re.sub(r'<\s*strong\s*>', '<b>', text, flags=re.IGNORECASE)
    text = re.sub(r'<\s*/\s*strong\s*>', '</b>', text, flags=re.IGNORECASE)
    text = re.sub(r'<\s*em\s*>', '<i>', text, flags=re.IGNORECASE)
    text = re.sub(r'<\s*/\s*em\s*>', '</i>', text, flags=re.IGNORECASE)
    # Treat line-break-ish and block-closing tags as a line break.
    text = re.sub(r'<\s*br\s*/?\s*>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'<\s*/\s*(p|div|li|h[1-6]|tr)\s*>', '\n', text, flags=re.IGNORECASE)
    # Drop opening/other block-level tags we don't render as their own flowable.
    text = re.sub(r'<\s*(p|div|li|ul|ol|h[1-6]|tr|td|th|table|tbody|thead)[^>]*>', '', text, flags=re.IGNORECASE)
    text = re.sub(r'<\s*/\s*(td|th|table|tbody|thead)\s*>', '', text, flags=re.IGNORECASE)
    # Strip any remaining tags except the <b>/<i> emphasis we support.
    text = re.sub(r'<(?!/?(b|i)\b)[^>]+>', '', text, flags=re.IGNORECASE)
    lines = [re.sub(r'\s+', ' ', line).strip() for line in text.split('\n')]
    return [line for line in lines if line]


class _PlainLabelCanvas(canvas.Canvas):
    """Draws a solid green rounded rectangular border on each page."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self._draw_border()
            super().showPage()
        super().save()

    def _draw_border(self):
        self.saveState()
        self.setStrokeColor(GREEN_COLOR)
        self.setLineWidth(1.5)
        border_x = LABEL_MARGIN
        border_y = LABEL_MARGIN
        border_w = PAGE_WIDTH - (2 * LABEL_MARGIN)
        border_h = PAGE_HEIGHT - (2 * LABEL_MARGIN)
        self.roundRect(border_x, border_y, border_w, border_h, radius=3.5 * mm, stroke=1, fill=0)
        self.restoreState()


def _do_nothing(canvas_obj, doc):
    pass


class _PlainLabelDocTemplate(SimpleDocTemplate):
    """SimpleDocTemplate always builds its single content Frame with
    reportlab's default 6pt padding on every side (this is hardcoded in
    Frame's constructor and SimpleDocTemplate.build() does not expose a way
    to change it). That quietly steals about 12pt off both the usable width
    and height of a page that is only ~285-370pt tall/wide to begin with -
    real estate a fixed 100mm x 130mm thermal label can't spare. It also
    means the height the auto-shrink-to-fit logic measures against
    (PRINTABLE_WIDTH/PRINTABLE_HEIGHT) would silently be larger than the
    frame actually used to draw the page, so a label that measured as
    "fits" could still spill onto a second page. This override builds the
    frame with zero padding instead, so what gets measured is exactly what
    gets drawn."""

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


class ProductionLabelReportPlain(models.AbstractModel):
    _name = 'report.tl_rf_reports.report_production_label_plain'
    _description = 'Production Label Report Data - Plain Label (Frozen)'
    _inherit = 'report.tl_rf_reports.report_production_label_document_courier'

    def _label_circle_flowable(self, scale=1.0):
        return _label_circle_flowable(scale)

    def _format_html_to_reportlab(self, html_text):
        return _format_html_to_reportlab(html_text)

    def _split_html_into_lines(self, html_text):
        return _split_html_into_lines(html_text)

    # Font sizes below this fraction of their original size are not tried -
    # text would become illegible on a printed thermal label before that
    # point, so this is the floor for the auto-shrink-to-fit logic.
    MIN_FONT_SCALE = 0.4

    def _plain_label_styles(self, scale=1.0):
        """Builds the label's paragraph styles. `scale` multiplies every
        font size/leading (and the nutrition sub-row indent) so the whole
        label can be shrunk uniformly when the content is too long to fit
        on the fixed 100mm x 130mm page - see _build_fitted_story()."""
        base, bold, italic = 'Helvetica', 'Helvetica-Bold', 'Helvetica-Oblique'

        def sz(value):
            return value * scale

        return {
            'product_title': ParagraphStyle(
                'PlainProductTitle', fontName=bold, fontSize=sz(14.5), leading=sz(16.5),
                alignment=1, textColor=GREEN_COLOR,
            ),
            'product_subtitle': ParagraphStyle(
                'PlainProductSubtitle', fontName=bold, fontSize=sz(10.5), leading=sz(12.5),
                alignment=1, textColor=GREEN_COLOR,
            ),
            'section_heading': ParagraphStyle(
                'PlainSectionHead', fontName=bold, fontSize=sz(8.2), leading=sz(10.0),
                alignment=0, textColor=colors.black,
            ),
            'body_text': ParagraphStyle(
                'PlainBody', fontName=base, fontSize=sz(7.6), leading=sz(9.4),
                alignment=0, textColor=colors.black,
            ),
            'ingredients_text': ParagraphStyle(
                'PlainIngredients', fontName=base, fontSize=sz(7.2), leading=sz(8.8),
                alignment=0, textColor=colors.black,
            ),
            'notice_text': ParagraphStyle(
                'PlainNotice', fontName=base, fontSize=sz(7.3), leading=sz(9.0),
                alignment=0, textColor=colors.black,
            ),
            'notice_bold': ParagraphStyle(
                'PlainNoticeBold', fontName=bold, fontSize=sz(7.8), leading=sz(9.5),
                alignment=0, textColor=colors.black,
            ),
            'date_label': ParagraphStyle(
                'PlainDateLabel', fontName=base, fontSize=sz(7.8), leading=sz(9.5),
                alignment=0, textColor=colors.black,
            ),
            'date_value': ParagraphStyle(
                'PlainDateVal', fontName=base, fontSize=sz(7.8), leading=sz(9.5),
                alignment=0, textColor=colors.black,
            ),
            'weight_text': ParagraphStyle(
                'PlainWeight', fontName=bold, fontSize=sz(9.5), leading=sz(11.5),
                alignment=0, textColor=colors.black,
            ),
            'nutrition_head': ParagraphStyle(
                'PlainNutriHead', fontName=base, fontSize=sz(6.8), leading=sz(8.4),
                alignment=0, textColor=colors.black,
            ),
            'nutrition_row': ParagraphStyle(
                'PlainNutriRow', fontName=base, fontSize=sz(6.8), leading=sz(8.4),
                alignment=0, textColor=colors.black,
            ),
            'nutrition_subrow': ParagraphStyle(
                'PlainNutriSubRow', fontName=base, fontSize=sz(6.8), leading=sz(8.4),
                alignment=0, textColor=colors.black, leftIndent=sz(3 * mm),
            ),
            'footer_text': ParagraphStyle(
                'PlainFooter', fontName=base, fontSize=sz(6.8), leading=sz(8.2),
                alignment=1, textColor=colors.black,
            ),
        }

    def _plain_label_flowables(self, label, index, total_labels, styles, scale=1.0):
        # `scale` shrinks the vertical spacing between sections in step with
        # the font sizes already baked into `styles` (see _plain_label_styles
        # and _build_fitted_story), so the whole label compresses uniformly
        # rather than just the text.
        def gap(mm_value):
            return mm_value * mm * scale

        # All of these are fetched straight from the label dict the wizard
        # builds from the product/MO record - no hardcoded sample values are
        # substituted here. If a field is genuinely empty on the product,
        # that section is simply left blank on the label rather than
        # printing fabricated placeholder text/numbers.
        product_name_main = label.get('product_name_main') or label.get('product_name') or ''
        product_name_sub = label.get('product_name_sub') or ''
        cooking_heading = label.get('cooking_heading') or ''
        cooking_instructions = label.get('cooking_instructions') or ''
        ingredients_html = label.get('ingredients_html') or label.get('ingredients') or ''
        allergen_notice = label.get('allergen_notice') or ''
        advisory_notice = label.get('advisory_notice') or ''
        catch_info = label.get('catch_info') or ''
        storage_notice = label.get('storage_notice') or ''
        freezing_notice = label.get('freezing_notice') or ''
        production_date_display = label.get('production_date_display') or ''
        use_by_display = label.get('use_by_display') or ''
        weight_display = label.get('min_weight_display') or label.get('weight_display') or ''
        company_address = label.get('company_address') or ''

        story = []

        # 1. Product Name Header (Green Bold, Centered)
        story.append(Paragraph(xml_escape(product_name_main), styles['product_title']))
        if product_name_sub:
            story.append(Paragraph(xml_escape(product_name_sub), styles['product_subtitle']))
        story.append(Spacer(1, gap(1.2)))

        # 2. Cooking Instructions (Bold heading + regular body)
        if cooking_heading:
            story.append(Paragraph(f"<b>{xml_escape(cooking_heading)}</b>", styles['section_heading']))
        if cooking_instructions:
            formatted_cooking = _format_html_to_reportlab(cooking_instructions)
            story.append(Paragraph(formatted_cooking, styles['body_text']))
        story.append(Spacer(1, gap(1.5)))

        # 3. Ingredients (with BOLD allergens)
        if ingredients_html:
            formatted_ing = _format_html_to_reportlab(ingredients_html)
            if not formatted_ing.lower().startswith('ingredients:'):
                formatted_ing = f"Ingredients:{formatted_ing}"
            story.append(Paragraph(formatted_ing, styles['ingredients_text']))
        story.append(Spacer(1, gap(1.2)))

        # 4. Allergen Notice & Advisory Notices
        if allergen_notice:
            story.append(Paragraph(allergen_notice, styles['notice_text']))
        if advisory_notice:
            story.append(Paragraph(xml_escape(advisory_notice), styles['notice_text']))
        if catch_info:
            story.append(Paragraph(xml_escape(catch_info), styles['notice_text']))
        story.append(Spacer(1, gap(0.8)))

        # 5. Storage & Freezing Notices (Bold)
        if storage_notice:
            story.append(Paragraph(f"<b>{xml_escape(storage_notice)}</b>", styles['notice_bold']))
        if freezing_notice:
            story.append(Paragraph(f"<b>{xml_escape(freezing_notice)}</b>", styles['notice_bold']))
        story.append(Spacer(1, gap(1.5)))

        # 6. Bottom Data Section (3 Columns: Left Dates/Weight, Middle Nutrition, Right GB Oval)
        # Left Column: Production Date, Use By, Min Weight
        left_flowables = [
            Paragraph("Production Date:", styles['date_label']),
            Paragraph(production_date_display, styles['date_value']),
            Spacer(1, gap(0.6)),
            Paragraph("Use By:", styles['date_label']),
            Paragraph(use_by_display, styles['date_value']),
            Spacer(1, gap(1.5)),
            Paragraph(weight_display, styles['weight_text']),
        ]

        # Middle Column: Nutrition Table - built from the product's Nutrition
        # field (nutrition_html, sourced from product.nutritional_info_html /
        # product.template.nutritional_info_html). No fabricated per-100g
        # values: if the product has no nutrition data, the section is left
        # blank rather than printing made-up numbers on a food label.
        nutrition_html = label.get('nutrition_html') or label.get('nutritional_info_html')
        nutrition_text_lines = self._split_html_into_lines(nutrition_html)
        if nutrition_text_lines and not nutrition_text_lines[0].lower().startswith('nutrition'):
            nutrition_text_lines[0] = f"<b>Nutrition:</b> {nutrition_text_lines[0]}"

        nutrition_flowables = []
        for line_idx, line_text in enumerate(nutrition_text_lines):
            is_sub = line_text.lower().startswith('of which')
            style = styles['nutrition_subrow'] if is_sub else (styles['nutrition_head'] if line_idx == 0 else styles['nutrition_row'])
            nutrition_flowables.append(Paragraph(line_text, style))

        # Right Column: GB GG476 Oval Stamp
        oval_flow = _label_circle_flowable(scale)

        # Build bottom 3-column table
        left_col_w = 26.0 * mm * max(scale, 0.75)
        right_col_w = 19.0 * mm * scale
        mid_col_w = PRINTABLE_WIDTH - (left_col_w + right_col_w)

        bottom_table = Table(
            [[left_flowables, nutrition_flowables, oval_flow]],
            colWidths=[left_col_w, mid_col_w, right_col_w],
        )
        bottom_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (0, 0), 'TOP'),
            ('VALIGN', (1, 0), (1, 0), 'TOP'),
            ('VALIGN', (2, 0), (2, 0), 'BOTTOM'),
            ('ALIGN', (2, 0), (2, 0), 'RIGHT'),
            ('LEFTPADDING', (0, 0), (-1, -1), 0),
            ('RIGHTPADDING', (0, 0), (-1, -1), 0),
            ('TOPPADDING', (0, 0), (-1, -1), 0),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
        ]))
        story.append(bottom_table)
        story.append(Spacer(1, gap(1.5)))

        # 7. Footer: Company Address (as provided by the wizard/company record)
        if company_address:
            story.append(Paragraph(xml_escape(company_address), styles['footer_text']))

        return story

    def _measure_story_height(self, story, avail_width):
        """Sums the height each flowable in `story` needs when wrapped at
        `avail_width`, i.e. how tall the label would render. Used to check
        whether a label's content fits the fixed page height before it is
        actually drawn."""
        total_height = 0.0
        for flowable in story:
            try:
                _, flowable_height = flowable.wrap(avail_width, 0xFFFFFF)
            except Exception:
                flowable_height = 0
            total_height += flowable_height
        return total_height

    def _build_fitted_story(self, label, index, total_labels, fit_cache=None):
        """Builds the flowables for one label. Finds the largest font scale
        (spacing and stamp scale with it) at which the whole label fits the
        fixed 100mm x 130mm page. If the content is still too long at
        MIN_FONT_SCALE, it is shrunk as a block. Every label is exactly one
        page and nothing is cut off."""
        def build(scale):
            return self._plain_label_flowables(
                label, index, total_labels, self._plain_label_styles(scale), scale
            )
        return build_fitted_label(
            build, PRINTABLE_WIDTH, PRINTABLE_HEIGHT, self.MIN_FONT_SCALE,
            cache=fit_cache, cache_key=label_cache_key(label),
        )

    def generate_pdf(self, wizard, label_lines=None):
        """Returns the finished Plain Label PDF (bytes), or None if there
        is nothing to print. One physical label per page at the 100mm x 130mm
        size with the approved green-bordered Plain Label design. However
        long the product's ingredients/cooking-instructions/nutrition text
        turns out to be, the label is shrunk to fit on that one page rather
        than overflowing onto a second page (see _build_fitted_story)."""
        # label_lines is optional: the Production Label wizard passes it (None
        # for non-Fresh labels), and the Product Label wizard does not.
        if label_lines is None:
            label_lines = wizard._get_plain_label_data()
        if not label_lines:
            return None

        total_labels = len(label_lines)

        buffer = io.BytesIO()
        doc = _PlainLabelDocTemplate(
            buffer, pagesize=(PAGE_WIDTH, PAGE_HEIGHT),
            leftMargin=LABEL_MARGIN + INNER_PADDING,
            rightMargin=LABEL_MARGIN + INNER_PADDING,
            topMargin=LABEL_MARGIN + INNER_PADDING,
            bottomMargin=LABEL_MARGIN + INNER_PADDING,
        )

        def _make_canvas(*args, **kwargs):
            return _PlainLabelCanvas(*args, **kwargs)

        story = []
        fit_cache = {}
        for index, label in enumerate(label_lines):
            if index:
                story.append(PageBreak())
            story.extend(self._build_fitted_story(label, index, total_labels, fit_cache))

        doc.title = 'Plain Labels'  # PDF metadata - shown by browser PDF viewers
        doc.author = self.env.company.name or ''
        doc.build(story, canvasmaker=_make_canvas)
        pdf_value = buffer.getvalue()
        buffer.close()
        return pdf_value
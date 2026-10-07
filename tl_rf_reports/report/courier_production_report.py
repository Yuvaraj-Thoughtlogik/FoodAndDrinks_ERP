# -*- coding: utf-8 -*-
import io
from xml.sax.saxutils import escape as xml_escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    Flowable, Paragraph, SimpleDocTemplate, Table, TableStyle,
)

from odoo import api, fields, models, _

WEIGHT_UOM_KEYWORDS = {
    'kg', 'kgs', 'kg(s)', 'kilo', 'kilogram', 'kilograms',
    'g', 'gram', 'grams', 'lb', 'lbs', 'pound', 'pounds',
}


class _CourierProductionReportHeaderMarker(Flowable):
    """Zero-size flowable that stamps the report's title/date-range header
    data onto the canvas as soon as ReportLab draws it - same two-pass
    technique as report_production_report.py's _ProductionReportHeaderMarker."""

    def __init__(self, header_data):
        super().__init__()
        self.header_data = header_data
        self.width = 0
        self.height = 0

    def wrap(self, availWidth, availHeight):
        return (0, 0)

    def draw(self):
        self.canv.current_header = self.header_data


class _CourierProductionReportCanvas(canvas.Canvas):
    """Two-pass canvas: replays every page once all pages are known, drawing
    the "<Channel> Fresh Production Report:" title plus the packing/delivery
    date range on every physical page, and a printed-date + "Page X of Y"
    footer (Y only knowable once every page has been counted)."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []
        self.current_header = None
        self.printed_date_text = ''

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self._draw_decorations(total_pages)
            super().showPage()
        super().save()

    def _draw_decorations(self, total_pages):
        self.saveState()
        margin = 12 * mm
        width = A4[0] - (2 * margin)

        if self.current_header and isinstance(self.current_header, dict):
            h_data = self.current_header
            title_style = ParagraphStyle(
                'CPRTitle', fontName='Helvetica-Bold', fontSize=15, leading=18, textColor=colors.black
            )
            range_style = ParagraphStyle(
                'CPRRange', fontName='Helvetica', fontSize=10, leading=13, alignment=2, textColor=colors.black
            )

            left_flow = [Paragraph(xml_escape(h_data.get('title', '')), title_style)]
            right_flow = []
            if h_data.get('packing_display'):
                right_flow.append(Paragraph(xml_escape(h_data.get('packing_display', '')), range_style))
            if h_data.get('delivery_display'):
                right_flow.append(Paragraph(xml_escape(h_data.get('delivery_display', '')), range_style))

            header_tbl = Table([[left_flow, right_flow]], colWidths=[width * 0.55, width * 0.45])
            header_tbl.setStyle(TableStyle([
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('LEFTPADDING', (0, 0), (-1, -1), 0),
                ('RIGHTPADDING', (0, 0), (-1, -1), 0),
                ('TOPPADDING', (0, 0), (-1, -1), 0),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
            ]))
            header_w, h_height = header_tbl.wrap(width, 30 * mm)
            header_tbl.drawOn(self, margin, A4[1] - margin - h_height)

        if self.printed_date_text:
            footer_style_left = ParagraphStyle(
                'CPRFooterL', fontName='Helvetica', fontSize=9, leading=11, alignment=0, textColor=colors.black
            )
            footer_l = Paragraph(xml_escape(self.printed_date_text), footer_style_left)
            footer_l.wrap(width, 8 * mm)
            footer_l.drawOn(self, margin, 6 * mm)

        page_style = ParagraphStyle(
            'CPRFooterPage', fontName='Helvetica', fontSize=9, leading=11, alignment=2, textColor=colors.black
        )
        page_p = Paragraph(_("Page %(page)s of %(total)s") % {'page': self._pageNumber, 'total': total_pages}, page_style)
        page_p.wrap(width, 8 * mm)
        page_p.drawOn(self, margin, 6 * mm)

        self.restoreState()


class ReportCourierProductionReport(models.AbstractModel):
    _name = 'report.tl_rf_reports.report_courier_production_report'
    _description = 'Courier Fresh Production Report Generator (Courier, Manufacturing Order component lines, grouped by Product/Box Qty/Special Note)'

    @api.model
    def _is_weight_uom(self, uom):
        if not uom:
            return False
        category = getattr(uom, 'category_id', False) or getattr(uom, 'uom_category_id', False)
        if category:
            category_name = (getattr(category, 'name', '') or '').lower()
            measure_type = getattr(category, 'measure_type', '') or getattr(category, 'uom_type', '')
            if 'weight' in category_name or measure_type == 'weight':
                return True
        uom_name = (getattr(uom, 'name', '') or '').strip().lower()
        return uom_name in WEIGHT_UOM_KEYWORDS

    @api.model
    def _format_qty(self, qty):
        if float(qty).is_integer():
            return str(int(qty))
        return ('%g' % qty)

    # ------------------------------------------------------------------
    # Fast path: builds the PDF directly with ReportLab, in memory - no
    # QWeb template, no wkhtmltopdf, no background job (same pattern as
    # report_production_report.py's generate_pdf()). `productions` is the
    # Courier mrp.production recordset already filtered by
    # ProductionReportWizard._get_production_domain(). Each MO's own
    # product_id/product_qty IS the box-type product/qty to report on - the
    # Pack Box wizard creates one MO per box directly for that product, so
    # this groups the MOs themselves, not their raw-material component
    # lines (move_raw_ids).
    #
    # Consolidation: each MO is one box. MOs for the same product AND the
    # same quantity (product_qty) consolidate into a single row - "Boxes" is
    # the COUNT of such MOs, "Box Qty" is that shared per-box quantity. An
    # MO carrying a customer special note (production_sale_line_id.special_requirements_
    # notes_id) consolidates with any other MO carrying that SAME note
    # record (by id), even across different sale order lines, so
    # identically-noted boxes of the same product/quantity share one row
    # while a different note still gets its own - identical rule to
    # report_production_report.py's generate_pdf().
    # ------------------------------------------------------------------
    def generate_pdf(self, wizard, productions):
        """Returns the finished PDF (bytes) for the Courier Fresh Production
        Report, or None when there is nothing to print."""
        if not productions:
            return None

        productions = productions.filtered(lambda m: m.product_id)
        if wizard.category_ids:
            allowed_categ_ids = set(wizard.category_ids.ids)
            productions = productions.filtered(lambda m: m.product_id.categ_id.id in allowed_categ_ids)
        if not productions:
            return None

        groups = {}
        for mo in productions:
            product = mo.product_id
            qty = mo.product_qty or 0.0
            uom = mo.product_uom_id
            special_note = (mo.production_sale_line_id.special_requirements_notes_id.name or '').strip()
            # Notes-less MOs consolidate across any sale order line; a noted
            # MO consolidates with any other MO carrying the SAME note
            # record (by id), regardless of which sale order line it came
            # from.
            notes_scope = mo.production_sale_line_id.special_requirements_notes_id.id if special_note else 0
            group_key = (product.id, qty, uom.id, notes_scope)

            group = groups.setdefault(group_key, {
                'product_name': product.name,
                'qty': qty,
                'uom': uom,
                'special_notes': special_note,
                'count': 0,
            })
            group['count'] += 1

        if not groups:
            return None

        rows = []
        for group in groups.values():
            qty_display = self._format_qty(group['qty'])
            if self._is_weight_uom(group['uom']):
                box_qty_display = _("X %s KG") % qty_display
            else:
                box_qty_display = _("X %s") % qty_display
            rows.append({
                'count': group['count'],
                'box_qty_display': box_qty_display,
                'product_name': group['product_name'],
                'special_notes': group['special_notes'],
                'sort_key': ((group['product_name'] or '').strip().lower(), group['qty']),
            })

        rows.sort(key=lambda r: r['sort_key'])

        now_local = fields.Datetime.context_timestamp(self, fields.Datetime.now())
        printed_date_str = now_local.strftime('%d %B %Y')

        packing_display = ''
        if wizard.packing_date_from and wizard.packing_date_to:
            packing_display = _("For Packing between %s and %s") % (
                wizard.packing_date_from.strftime('%d/%m/%Y'), wizard.packing_date_to.strftime('%d/%m/%Y')
            )
        delivery_display = ''
        if wizard.delivery_date_from and wizard.delivery_date_to:
            delivery_display = "(Delivery %s-%s)" % (
                wizard.delivery_date_from.strftime('%d/%m/%Y'), wizard.delivery_date_to.strftime('%d/%m/%Y')
            )

        channel_label = dict(wizard._fields['delivery_channel'].selection).get(wizard.delivery_channel, '')
        title = _("%s Fresh Production Report:") % channel_label if channel_label else _("Fresh Production Report:")

        header_data = {'title': title, 'packing_display': packing_display, 'delivery_display': delivery_display}
        return self._build_courier_production_report_pdf(rows, header_data, printed_date_str)

    def _build_courier_production_report_pdf(self, rows, header_data, printed_date_str):
        """Pure layout step - takes already-grouped/sorted rows and draws
        them. Split out from generate_pdf() so the layout code can be
        exercised standalone without touching the ORM."""
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer, pagesize=A4,
            leftMargin=12 * mm, rightMargin=12 * mm, topMargin=30 * mm, bottomMargin=14 * mm,
        )
        width = A4[0] - (24 * mm)

        col_header_style = ParagraphStyle(
            'CPRColHeader', fontName='Helvetica-BoldOblique', fontSize=10.5, leading=13, textColor=colors.black
        )
        cell_count_style = ParagraphStyle(
            'CPRCellCount', fontName='Helvetica-Bold', fontSize=10.5, leading=14, alignment=1, textColor=colors.black
        )
        cell_qty_style = ParagraphStyle(
            'CPRCellQty', fontName='Helvetica-Bold', fontSize=10.5, leading=14, alignment=0, textColor=colors.black
        )
        cell_prod_style = ParagraphStyle(
            'CPRCellProd', fontName='Helvetica', fontSize=10.5, leading=14, alignment=0, textColor=colors.black
        )
        cell_note_style = ParagraphStyle(
            'CPRCellNote', fontName='Helvetica-Oblique', fontSize=9.5, leading=13, alignment=0, textColor=colors.black
        )

        count_w = 18 * mm
        qty_w = 25 * mm
        note_w = 45 * mm
        prod_w = width - count_w - qty_w - note_w
        col_widths = [count_w, qty_w, prod_w, note_w]

        header_cells = [
            Paragraph(_("Boxes"), col_header_style),
            Paragraph(_("Box QTY"), col_header_style),
            Paragraph(_("Product"), col_header_style),
            Paragraph(_("Box Detail"), col_header_style),
        ]
        data_rows = [header_cells] + [
            [
                Paragraph(str(r['count']), cell_count_style),
                Paragraph(xml_escape(r['box_qty_display']), cell_qty_style),
                Paragraph(xml_escape(r['product_name'] or ''), cell_prod_style),
                Paragraph(xml_escape(r['special_notes'] or ''), cell_note_style),
            ]
            for r in rows
        ]

        table = Table(data_rows, colWidths=col_widths, repeatRows=1)
        table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('ALIGN', (0, 0), (0, -1), 'CENTER'),
            ('LEFTPADDING', (0, 0), (-1, -1), 4),
            ('RIGHTPADDING', (0, 0), (-1, -1), 4),
            ('TOPPADDING', (0, 1), (-1, -1), 3),
            ('BOTTOMPADDING', (0, 1), (-1, -1), 3),
            ('TOPPADDING', (0, 0), (-1, 0), 1),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 3),
            ('LINEBELOW', (0, 0), (-1, 0), 1.25, colors.black),
            ('LINEBELOW', (0, 1), (-1, -1), 0.5, colors.black),
        ]))

        story = [_CourierProductionReportHeaderMarker(header_data), table]

        def _make_canvas(*args, **kwargs):
            c = _CourierProductionReportCanvas(*args, **kwargs)
            c.printed_date_text = printed_date_str
            return c

        doc.title = 'Courier Fresh Production Report'  # PDF metadata - shown by browser PDF viewers
        doc.author = self.env.company.name or ''
        doc.build(story, canvasmaker=_make_canvas)
        pdf_value = buffer.getvalue()
        buffer.close()
        return pdf_value

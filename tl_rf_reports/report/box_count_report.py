# -*- coding: utf-8 -*-
import io
from xml.sax.saxutils import escape as xml_escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    BaseDocTemplate, Flowable, Frame, HRFlowable, PageBreak, PageTemplate, Paragraph, Spacer, Table, TableStyle,
)

from odoo import api, fields, models, _


class _BoxCountReportHeaderMarker(Flowable):
    """Zero-size flowable that stamps the current category page's header data
    onto the canvas as soon as ReportLab draws it - same two-pass technique
    as report_production_report.py's _ProductionReportHeaderMarker."""

    def __init__(self, header_data):
        super().__init__()
        self.header_data = header_data
        self.width = 0
        self.height = 0

    def wrap(self, availWidth, availHeight):
        return (0, 0)

    def draw(self):
        self.canv.current_header = self.header_data


class _BoxCountReportCanvas(canvas.Canvas):
    """Two-pass canvas: replays every page once the header stamped by
    _BoxCountReportHeaderMarker for that page is known, drawing the
    "<CATEGORY> Box Count Report" title and delivery day/date on every
    physical page, plus a "Printed at ..." + page number footer."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []
        self.current_header = None
        self.printed_at_text = ''

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self._draw_decorations()
            super().showPage()
        super().save()

    def _draw_decorations(self):
        self.saveState()
        margin = 12 * mm
        width = A4[0] - (2 * margin)

        if self.current_header and isinstance(self.current_header, dict):
            h_data = self.current_header
            title_style = ParagraphStyle(
                'BCTitle', fontName='Helvetica-Bold', fontSize=15, leading=18, textColor=colors.black
            )
            date_style = ParagraphStyle(
                'BCDate', fontName='Helvetica-Bold', fontSize=10.5, leading=13, textColor=colors.black
            )

            flow = [Paragraph(xml_escape(h_data.get('title', '')), title_style)]
            if h_data.get('date_display'):
                flow.append(Paragraph(xml_escape(h_data.get('date_display', '')), date_style))

            header_tbl = Table([[flow]], colWidths=[width])
            header_tbl.setStyle(TableStyle([
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('LEFTPADDING', (0, 0), (-1, -1), 0),
                ('RIGHTPADDING', (0, 0), (-1, -1), 0),
                ('TOPPADDING', (0, 0), (-1, -1), 0),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
            ]))
            _, h = header_tbl.wrap(width, 30 * mm)
            header_tbl.drawOn(self, margin, A4[1] - margin - h)

        if self.printed_at_text:
            footer_style_right = ParagraphStyle(
                'BCFooterR', fontName='Helvetica', fontSize=9, leading=11, alignment=2, textColor=colors.black
            )
            footer_r = Paragraph(f"Printed at: {xml_escape(self.printed_at_text)}", footer_style_right)
            footer_r.wrap(width, 8 * mm)
            footer_r.drawOn(self, margin, 6 * mm)

        page_style = ParagraphStyle(
            'BCFooterPage', fontName='Helvetica', fontSize=9, leading=11, alignment=1, textColor=colors.black
        )
        page_p = Paragraph(str(self._pageNumber), page_style)
        page_p.wrap(width, 8 * mm)
        page_p.drawOn(self, margin, 6 * mm)

        self.restoreState()


class ReportBoxCountReport(models.AbstractModel):
    _name = 'report.tl_rf_reports.report_box_count_report'
    _description = 'Box Count Report Generator (Regal Van, Draft Manufacturing Orders, grouped by Category -> Depot -> Round Batch)'

    # ------------------------------------------------------------------
    # Sorting - categories sort FROZEN, then FRESH, then everything else
    # alphabetically (same convention as report_production_report.py);
    # depots sort alphabetically; within a depot, batches sort by their
    # numeric Batch Code when possible, falling back to a plain string sort.
    # ------------------------------------------------------------------
    @api.model
    def _get_category_sort_key(self, categ_name):
        name = (categ_name or '').strip().upper()
        if 'FROZEN' in name:
            return (0, name)
        if 'FRESH' in name:
            return (1, name)
        return (2, name)

    @api.model
    def _get_batch_sort_key(self, batch_item):
        code = (batch_item.get('batch_code') or '').strip()
        try:
            return (0, int(code), code)
        except (TypeError, ValueError):
            return (1, 0, code)

    # ------------------------------------------------------------------
    # Pagination - one category per canvas header; within a category,
    # depots are packed onto pages using the same tuned row-budget approach
    # as report_production_report.py's _paginate_depot_categories
    # (MAX_PAGE_WEIGHT is a proxy for vertical space, not a real mm/px
    # measurement), so a short depot doesn't waste a whole page and a long
    # one repeats its depot header if it spills onto the next page.
    # ------------------------------------------------------------------
    @api.model
    def _paginate_category_depots(self, depot_list):
        MAX_PAGE_WEIGHT = 40
        pages = []
        current_page_depots = []
        current_weight = 0

        for depot in depot_list:
            batches = depot['batches']
            b_idx = 0
            total_batches = len(batches)

            while b_idx < total_batches:
                depot_header_cost = 2.5

                if current_page_depots and (current_weight + depot_header_cost + 1 > MAX_PAGE_WEIGHT):
                    pages.append(current_page_depots)
                    current_page_depots = []
                    current_weight = 0

                available_weight = MAX_PAGE_WEIGHT - current_weight - depot_header_cost
                if available_weight < 1:
                    available_weight = 1

                num_to_take = min(int(available_weight), total_batches - b_idx)
                chunk_batches = batches[b_idx:b_idx + num_to_take]
                b_idx += num_to_take

                current_page_depots.append({'depot_name': depot['depot_name'], 'batches': chunk_batches})
                current_weight += depot_header_cost + len(chunk_batches)

                if b_idx < total_batches:
                    pages.append(current_page_depots)
                    current_page_depots = []
                    current_weight = 0

        if current_page_depots:
            pages.append(current_page_depots)

        return pages

    # ------------------------------------------------------------------
    # Fast path: builds the PDF directly with ReportLab, in memory - no
    # QWeb template, no wkhtmltopdf, no background job (same pattern as
    # report_production_report.py's generate_pdf(), and the same source
    # data: `productions` is the draft mrp.production recordset already
    # filtered by ProductionReportWizard._get_production_domain(), and the
    # report groups their raw-material component lines (move_raw_ids), not
    # mo.product_id - see the note in report_production_report.py.
    #
    # Unlike the Production Report (which sums each component's
    # product_uom_qty per product), the Box Count Report counts EVERY
    # component line as exactly one box, regardless of its quantity, and
    # totals that count per Round Batch (mo.round_batch_id).
    # ------------------------------------------------------------------
    def generate_pdf(self, wizard, productions):
        """Returns the finished PDF (bytes) for the Box Count Report, or
        None when there is nothing to print."""
        if not productions:
            return None

        # Matches report_production_report.py's generate_pdf() exactly here:
        # no upfront "has a category" requirement. An earlier version of
        # this method filtered out any move whose product_id.categ_id
        # resolved empty (e.g. blocked by a company-scoped category record
        # rule) before it ever reached the tolerant "Other" fallback below,
        # which could silently empty out the whole report even though
        # Production Report - reading the exact same moves - still worked.
        moves = productions.mapped('move_raw_ids').filtered(lambda m: m.product_id)
        if wizard.category_ids:
            allowed_categ_ids = set(wizard.category_ids.ids)
            moves = moves.filtered(lambda m: m.product_id.categ_id.id in allowed_categ_ids)
        if not moves:
            return None

        categ_map = {}
        for move in moves:
            mo = move.raw_material_production_id
            # mrp.production carries TWO independently-computed links, both
            # labelled "Round Batch" in the UI (which is why the MO can look
            # correctly batch-mapped there even when one of them is empty):
            # round_batch_id (tl_rf_reports/models/mrp_production.py,
            # regex-matched off mo.origin) and batch_id (round_management's
            # stock_picking.py, resolved from the MO's own
            # move_dest_ids.sale_line_id.order_id.batch_id - not dependent
            # on origin string parsing, so it stays populated in cases where
            # the regex doesn't match). Try both so a gap in one doesn't
            # empty out the whole report.
            batch = mo.round_batch_id or mo.batch_id

            categ = move.product_id.categ_id
            categ_key = categ.id or 0
            categ_name = (categ.name or _('Other')).strip().upper()

            depot = batch.depot_id if batch else mo.depot_id
            depot_key = depot.id or 0
            depot_name = depot.name or _('Grimsby')

            c_map = categ_map.setdefault(categ_key, {'categ_name': categ_name, 'dates': set(), 'depots_map': {}})
            delivery_date = batch.delivery_date if batch else mo.batch_delivery_date
            if delivery_date:
                c_map['dates'].add(delivery_date)

            d_map = c_map['depots_map'].setdefault(depot_key, {'depot_name': depot_name, 'batches': {}})

            batch_key = batch.id if batch else ('mo_%s' % mo.id)
            if batch_key not in d_map['batches']:
                d_map['batches'][batch_key] = {
                    'batch_code': batch.code if batch else (mo.name or ''),
                    'batch_reference': batch.reference if batch else (mo.origin or ''),
                    'qty': 0,
                }
            d_map['batches'][batch_key]['qty'] += 1

        if not categ_map:
            return None

        now_local = fields.Datetime.context_timestamp(self, fields.Datetime.now())
        printed_at_str = now_local.strftime('%d/%m/%Y %H:%M:%S')

        category_sections = []
        for c_key, c_val in sorted(
            categ_map.items(), key=lambda item: self._get_category_sort_key(item[1]['categ_name'])
        ):
            depot_list = []
            total_qty = 0
            for d_key, d_val in sorted(c_val['depots_map'].items(), key=lambda item: (item[1]['depot_name'] or '').lower()):
                sorted_batches = sorted(d_val['batches'].values(), key=self._get_batch_sort_key)
                for b in sorted_batches:
                    total_qty += b['qty']
                if sorted_batches:
                    depot_list.append({'depot_name': d_val['depot_name'], 'batches': sorted_batches})
            if not depot_list:
                continue

            dates = sorted(c_val['dates'])
            if len(dates) == 1:
                date_display = dates[0].strftime('%A %d/%m/%Y')
            elif dates:
                date_display = f"{dates[0].strftime('%d/%m/%Y')} - {dates[-1].strftime('%d/%m/%Y')}"
            else:
                date_display = ''

            category_sections.append({
                'title': f"{c_val['categ_name']} Box Count Report",
                'date_display': date_display,
                'depots': depot_list,
                'total_display': total_qty,
            })

        if not category_sections:
            return None

        return self._build_box_count_report_pdf(category_sections, printed_at_str)

    def _build_box_count_report_pdf(self, category_sections, printed_at_str):
        """Pure layout step - takes already-grouped/sorted category sections
        and draws them. Split out from generate_pdf() so the layout code can
        be exercised standalone without touching the ORM."""
        buffer = io.BytesIO()
        left_margin, right_margin = 12 * mm, 12 * mm
        top_margin, bottom_margin = 26 * mm, 14 * mm
        width = A4[0] - left_margin - right_margin
        height = A4[1] - top_margin - bottom_margin

        doc = BaseDocTemplate(
            buffer, pagesize=A4,
            leftMargin=left_margin, rightMargin=right_margin, topMargin=top_margin, bottomMargin=bottom_margin,
        )
        # SimpleDocTemplate.build() always creates its Frame with the
        # platypus default 6pt padding on every side, which would offset
        # story content (Paragraph/Table) 6pt to the right of the
        # canvas-drawn title/date/footer (drawn directly at the margin in
        # _draw_decorations() above) - a zero-padding Frame keeps everything
        # flush on the same left edge.
        frame = Frame(
            left_margin, bottom_margin, width, height,
            leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0, id='normal',
        )
        doc.addPageTemplates([PageTemplate(id='body', frames=[frame])])

        depot_style = ParagraphStyle(
            'BCDepot', fontName='Helvetica-Bold', fontSize=11.5, leading=15, textColor=colors.black
        )
        cell_code_style = ParagraphStyle(
            'BCCellCode', fontName='Helvetica-Bold', fontSize=10.5, leading=15, alignment=0, textColor=colors.black
        )
        cell_ref_style = ParagraphStyle(
            'BCCellRef', fontName='Helvetica-Bold', fontSize=10.5, leading=15, alignment=0, textColor=colors.black
        )
        cell_qty_style = ParagraphStyle(
            'BCCellQty', fontName='Helvetica-Bold', fontSize=10.5, leading=15, alignment=2, textColor=colors.black
        )
        total_qty_style = ParagraphStyle(
            'BCTotalQty', fontName='Helvetica-Bold', fontSize=12, leading=16, alignment=2, textColor=colors.black
        )

        code_width = 25 * mm
        qty_width = 20 * mm
        ref_width = width - code_width - qty_width
        col_widths = [code_width, ref_width, qty_width]

        story = []
        first_page = True
        for section in category_sections:
            header_data = {'title': section['title'], 'date_display': section['date_display']}
            depot_pages = self._paginate_category_depots(section['depots'])
            last_page_idx = len(depot_pages) - 1

            for page_idx, page_depots in enumerate(depot_pages):
                if not first_page:
                    story.append(PageBreak())
                first_page = False
                story.append(_BoxCountReportHeaderMarker(header_data))

                for depot in page_depots:
                    depot_name = xml_escape(depot['depot_name'])
                    depot_name_width = stringWidth(depot['depot_name'], 'Helvetica-Bold', 11.5)
                    story.append(Paragraph(depot_name, depot_style))
                    story.append(HRFlowable(
                        width=depot_name_width, thickness=1, color=colors.black,
                        hAlign='LEFT', spaceBefore=1, spaceAfter=3.5 * mm,
                    ))

                    rows = [
                        [
                            Paragraph(xml_escape(str(b['batch_code'])), cell_code_style),
                            Paragraph(xml_escape(b['batch_reference'] or ''), cell_ref_style),
                            Paragraph(str(b['qty']), cell_qty_style),
                        ]
                        for b in depot['batches']
                    ]
                    table = Table(rows, colWidths=col_widths)
                    table.setStyle(TableStyle([
                        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                        ('LEFTPADDING', (0, 0), (0, -1), 6 * mm),
                        ('LEFTPADDING', (1, 0), (-1, -1), 0),
                        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
                        ('TOPPADDING', (0, 0), (-1, -1), 2),
                        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
                    ]))
                    story.append(table)
                    # Border-bottom for the depot - an underline below the Qty
                    # column only, not a full-width rule.
                    story.append(HRFlowable(
                        width=qty_width, thickness=1, color=colors.black,
                        hAlign='RIGHT', spaceBefore=2, spaceAfter=6 * mm,
                    ))

                if page_idx == last_page_idx:
                    # Total Qty - underlines above and below the number
                    # only, scoped to the Qty column width, not full-width.
                    story.append(HRFlowable(
                        width=qty_width, thickness=1.5, color=colors.black,
                        hAlign='RIGHT', spaceBefore=0, spaceAfter=1,
                    ))
                    story.append(Paragraph(str(section['total_display']), total_qty_style))
                    story.append(HRFlowable(
                        width=qty_width, thickness=1.5, color=colors.black,
                        hAlign='RIGHT', spaceBefore=1, spaceAfter=0,
                    ))

        def _make_canvas(*args, **kwargs):
            c = _BoxCountReportCanvas(*args, **kwargs)
            c.printed_at_text = printed_at_str
            return c

        doc.build(story, canvasmaker=_make_canvas)
        pdf_value = buffer.getvalue()
        buffer.close()
        return pdf_value

# -*- coding: utf-8 -*-
import io
from xml.sax.saxutils import escape as xml_escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    Flowable, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

from odoo import api, fields, models, _


def _format_qty(val):
    if not val:
        return '0'
    formatted = f"{val:.3f}"
    if '.' in formatted:
        formatted = formatted.rstrip('0').rstrip('.')
    return formatted or '0'


class _ProductionReportHeaderMarker(Flowable):
    """Zero-size flowable that stamps the current depot page's header data
    onto the canvas as soon as ReportLab draws it - same two-pass technique
    as report_packing_list.py's _PackingListHeaderMarker."""

    def __init__(self, header_data):
        super().__init__()
        self.header_data = header_data
        self.width = 0
        self.height = 0

    def wrap(self, availWidth, availHeight):
        return (0, 0)

    def draw(self):
        self.canv.current_header = self.header_data


class _ProductionReportCanvas(canvas.Canvas):
    """Two-pass canvas: replays every page once the header stamped by
    _ProductionReportHeaderMarker for that page is known, drawing the
    "PRODUCTION REPORT" title / "Delivery On" + depot banner on every
    physical page, plus a "Printed at ..." + page number footer."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []
        self.current_header = None
        self.printed_at_text = ''
        self.title_text = 'PRODUCTION REPORT'

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
                'PRTitle', fontName='Helvetica-Bold', fontSize=16.5, leading=20, textColor=colors.black
            )
            date_style = ParagraphStyle(
                'PRDate', fontName='Helvetica-Bold', fontSize=12, leading=15, alignment=2, textColor=colors.black
            )
            depot_style = ParagraphStyle(
                'PRDepot', fontName='Helvetica-Bold', fontSize=12, leading=15, alignment=2, textColor=colors.black
            )

            left_flow = [Paragraph(self.title_text, title_style)]
            right_flow = [Paragraph(f"Delivery On: {xml_escape(h_data.get('delivery_date', ''))}", date_style)]
            if h_data.get('depot_name'):
                right_flow.append(Paragraph(xml_escape(h_data.get('depot_name', '')), depot_style))

            header_tbl = Table([[left_flow, right_flow]], colWidths=[width * 0.58, width * 0.42])
            header_tbl.setStyle(TableStyle([
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('LEFTPADDING', (0, 0), (-1, -1), 0),
                ('RIGHTPADDING', (0, 0), (-1, -1), 0),
                ('TOPPADDING', (0, 0), (-1, -1), 0),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
            ]))
            _, h = header_tbl.wrap(width, 35 * mm)
            header_tbl.drawOn(self, margin, A4[1] - margin - h)

        if self.printed_at_text:
            footer_style_right = ParagraphStyle(
                'PRFooterR', fontName='Helvetica', fontSize=9, leading=11, alignment=2, textColor=colors.black
            )
            footer_r = Paragraph(f"Printed at: {xml_escape(self.printed_at_text)}", footer_style_right)
            footer_r.wrap(width, 8 * mm)
            footer_r.drawOn(self, margin, 6 * mm)

        page_style = ParagraphStyle(
            'PRFooterPage', fontName='Helvetica', fontSize=9, leading=11, alignment=1, textColor=colors.black
        )
        page_p = Paragraph(str(self._pageNumber), page_style)
        page_p.wrap(width, 8 * mm)
        page_p.drawOn(self, margin, 6 * mm)

        self.restoreState()


class ReportProductionReport(models.AbstractModel):
    _name = 'report.tl_rf_reports.report_production_report'
    _description = 'Production Report Generator (Regal Van, Draft Manufacturing Orders)'

    # ------------------------------------------------------------------
    # Sorting - identical convention to report_packing_list.py /
    # report_driver_packing_list.py: products sort by their master "Sort
    # Seq" (food_packaging_info.product.template.sort_seq), unsorted
    # products first, ties broken alphabetically; categories sort FROZEN,
    # then FRESH, then everything else alphabetically.
    # ------------------------------------------------------------------
    @api.model
    def _get_sort_key(self, line_item):
        """Same product/name ordering as _extract_sort_number's callers
        elsewhere in this module, with the per-line "To Consume" quantity as
        a secondary key so a product's box-size variants (e.g. 0.5kg before
        1kg) stay grouped together and in ascending order."""
        sort_num = line_item.get('sort_num')
        product_name = (line_item.get('product_name') or '').strip().lower()
        qty_per_line = line_item.get('qty_per_line') or 0.0
        if not sort_num or sort_num <= 0:
            return (0, 0, product_name, qty_per_line)
        return (1, sort_num, product_name, qty_per_line)

    @api.model
    def _extract_sort_number(self, product):
        sort_val = 0
        if product:
            if hasattr(product, 'sort_seq') and product.sort_seq:
                sort_val = product.sort_seq
            elif (
                hasattr(product, 'product_tmpl_id')
                and hasattr(product.product_tmpl_id, 'sort_seq')
                and product.product_tmpl_id.sort_seq
            ):
                sort_val = product.product_tmpl_id.sort_seq

        try:
            sort_int = int(sort_val)
            return sort_int if sort_int > 0 else None
        except (ValueError, TypeError):
            return None

    @api.model
    def _get_category_sort_key(self, categ_name):
        name = (categ_name or '').strip().upper()
        if 'FROZEN' in name:
            return (0, name)
        if 'FRESH' in name:
            return (1, name)
        return (2, name)

    # ------------------------------------------------------------------
    # Pagination - one depot per PageBreak; within a depot, categories are
    # packed onto pages using the same tuned row-budget approach as
    # report_packing_list.py's _paginate_batch_categories (MAX_PAGE_WEIGHT
    # is a proxy for vertical space, not a real mm/px measurement), so a
    # short category doesn't waste a whole page and a long one repeats its
    # category header if it spills onto the next page.
    # ------------------------------------------------------------------
    @api.model
    def _paginate_depot_categories(self, category_list):
        MAX_PAGE_WEIGHT = 40
        pages = []
        current_page_categories = []
        current_weight = 0

        for cat in category_list:
            products = cat['products']
            prod_idx = 0
            total_prods = len(products)

            while prod_idx < total_prods:
                cat_header_cost = 2.5

                if current_page_categories and (current_weight + cat_header_cost + 1 > MAX_PAGE_WEIGHT):
                    pages.append(current_page_categories)
                    current_page_categories = []
                    current_weight = 0

                available_weight = MAX_PAGE_WEIGHT - current_weight - cat_header_cost
                if available_weight < 1:
                    available_weight = 1

                num_to_take = min(int(available_weight), total_prods - prod_idx)
                chunk_prods = products[prod_idx:prod_idx + num_to_take]
                prod_idx += num_to_take

                current_page_categories.append({'categ_name': cat['categ_name'], 'products': chunk_prods})
                current_weight += cat_header_cost + len(chunk_prods)

                if prod_idx < total_prods:
                    pages.append(current_page_categories)
                    current_page_categories = []
                    current_weight = 0

        if current_page_categories:
            pages.append(current_page_categories)

        return pages

    # ------------------------------------------------------------------
    # Fast path: builds the PDF directly with ReportLab, in memory - no
    # QWeb template, no wkhtmltopdf, no background job (see the "Print
    # Label" flow in production_report_wizard.py for the sibling pattern).
    # `productions` is the draft mrp.production recordset already filtered
    # by ProductionReportWizard._get_production_domain(). Each MO's own
    # product_id/product_qty IS the box-type product/qty to count (e.g.
    # "0.5 kg Cod Fillets Boned") - the Pack Box wizard
    # (round_management/models/stock_fresh_box_wizard.py action_generate_mo)
    # creates one MO per box directly for that product, so the report reads
    # the MOs themselves, not their raw-material component lines
    # (move_raw_ids).
    #
    # Consolidation: each MO is one box. MOs for the same product AND the
    # same quantity (product_qty) consolidate into a single row: "Quantity"
    # is the COUNT of such MOs, and the row's product text is prefixed with
    # that shared quantity (e.g. "1kg Cod Fillets Boned"). An MO carrying a
    # customer special note (production_sale_line_id.special_requirements_notes_id)
    # consolidates with any other MO carrying that SAME note record (by
    # id), even across different sale order lines, so identically-noted
    # boxes of the same product/quantity share one row while a different
    # note still gets its own.
    # ------------------------------------------------------------------
    def generate_pdf(self, wizard, productions):
        """Returns the finished PDF (bytes) for the Production Report, or
        None when there is nothing to print."""
        if not productions:
            return None

        if wizard.category_ids:
            allowed_categ_ids = set(wizard.category_ids.ids)
            productions = productions.filtered(lambda m: m.product_id.categ_id.id in allowed_categ_ids)
        if not productions:
            return None

        depots_map = {}
        for mo in productions:
            depot = mo.depot_id
            depot_name = depot.name or _('Grimsby')
            depot_key = depot.id or 0

            if depot_key not in depots_map:
                depots_map[depot_key] = {
                    'depot_name': depot_name,
                    'dates': set(),
                    'categories_map': {},
                }
            d_map = depots_map[depot_key]

            if mo.batch_delivery_date:
                d_map['dates'].add(mo.batch_delivery_date)

            product = mo.product_id
            categ = product.categ_id
            categ_name = (categ.name or _('Other')).strip().upper()
            categ_key = categ.id or 0
            if categ_key not in d_map['categories_map']:
                d_map['categories_map'][categ_key] = {'categ_name': categ_name, 'lines': {}}

            qty_per_line = mo.product_qty or 0.0
            special_note = (mo.production_sale_line_id.special_requirements_notes_id.name or '').strip()
            # Notes-less MOs consolidate across any sale order line; a noted
            # MO consolidates with any other MO carrying the SAME note
            # record (by id), regardless of which sale order line it came
            # from.
            notes_scope = mo.production_sale_line_id.special_requirements_notes_id.id if special_note else 0
            line_key = (product.id, qty_per_line, notes_scope)

            c_lines = d_map['categories_map'][categ_key]['lines']
            if line_key not in c_lines:
                c_lines[line_key] = {
                    'product_id': product.id,
                    'product_name': product.name,
                    'qty_per_line': qty_per_line,
                    'count': 0,
                    'special_notes': special_note,
                    'sort_num': self._extract_sort_number(product),
                }
            c_lines[line_key]['count'] += 1

        if not depots_map:
            return None

        now_local = fields.Datetime.context_timestamp(self, fields.Datetime.now())
        printed_at_str = now_local.strftime('%d/%m/%Y %H:%M:%S')

        depot_pages = []
        for d_key, d_val in sorted(depots_map.items(), key=lambda item: (item[1]['depot_name'] or '').lower()):
            category_list = []
            for c_key, c_val in sorted(
                d_val['categories_map'].items(),
                key=lambda item: self._get_category_sort_key(item[1]['categ_name'])
            ):
                sorted_lines = sorted(c_val['lines'].values(), key=self._get_sort_key)
                for item in sorted_lines:
                    item['product_display'] = f"{_format_qty(item['qty_per_line'])}kg {item['product_name'] or ''}"
                if sorted_lines:
                    category_list.append({'categ_name': c_val['categ_name'], 'products': sorted_lines})
            if not category_list:
                continue

            dates = sorted(d_val['dates'])
            if len(dates) == 1:
                date_display = dates[0].strftime('%d/%m/%Y')
            elif dates:
                date_display = f"{dates[0].strftime('%d/%m/%Y')} - {dates[-1].strftime('%d/%m/%Y')}"
            else:
                date_display = ''

            depot_pages.append({
                'depot_name': d_val['depot_name'],
                'delivery_date': date_display,
                'categories': category_list,
            })

        if not depot_pages:
            return None

        if getattr(wizard, 'all_production_report', False):
            title_text = 'ALL PRODUCTION REPORT'
        elif wizard.include_late_orders:
            title_text = 'LATE ONLY PRODUCTION REPORT'
        else:
            title_text = 'PRODUCTION REPORT'
        return self._build_production_report_pdf(depot_pages, printed_at_str, title_text)

    def _build_production_report_pdf(self, depot_pages, printed_at_str, title_text='PRODUCTION REPORT'):
        """Pure layout step - takes already-grouped/sorted depot pages and
        draws them. Split out from generate_pdf() so the layout code can be
        exercised standalone without touching the ORM."""
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer, pagesize=A4,
            leftMargin=12 * mm, rightMargin=12 * mm, topMargin=28 * mm, bottomMargin=14 * mm,
        )
        width = A4[0] - (24 * mm)

        category_style = ParagraphStyle(
            'PRCategory', fontName='Helvetica-Bold', fontSize=12, leading=15, textColor=colors.black
        )
        col_header_qty_style = ParagraphStyle(
            'PRColQty', fontName='Helvetica-BoldOblique', fontSize=10.5, leading=13, alignment=1, textColor=colors.black
        )
        col_header_prod_style = ParagraphStyle(
            'PRColProd', fontName='Helvetica-BoldOblique', fontSize=10.5, leading=13, alignment=0, textColor=colors.black
        )
        col_header_notes_style = ParagraphStyle(
            'PRColNotes', fontName='Helvetica-BoldOblique', fontSize=10.5, leading=13, alignment=0, textColor=colors.black
        )
        cell_qty_style = ParagraphStyle(
            'PRCellQty', fontName='Helvetica-Bold', fontSize=11.25, leading=15, alignment=1, textColor=colors.black
        )
        cell_prod_style = ParagraphStyle(
            'PRCellProd', fontName='Helvetica', fontSize=11.25, leading=15, alignment=0, textColor=colors.black
        )
        cell_notes_style = ParagraphStyle(
            'PRCellNotes', fontName='Helvetica-Oblique', fontSize=9.5, leading=12, alignment=0, textColor=colors.black
        )

        qty_col_width = 20 * mm
        remaining_width = width - qty_col_width
        col_widths = [qty_col_width, remaining_width * 0.55, remaining_width * 0.45]

        story = []
        first_page = True
        for d_page in depot_pages:
            header_data = {'delivery_date': d_page['delivery_date'], 'depot_name': d_page['depot_name']}
            depot_category_pages = self._paginate_depot_categories(d_page['categories'])

            for page_categories in depot_category_pages:
                if not first_page:
                    story.append(PageBreak())
                first_page = False
                story.append(_ProductionReportHeaderMarker(header_data))

                for cat in page_categories:
                    story.append(Paragraph(xml_escape(cat['categ_name']), category_style))
                    story.append(Spacer(1, 1 * mm))

                    header_row = Table(
                        [[
                            Paragraph("Quantity", col_header_qty_style),
                            Paragraph("Product / Box Contents", col_header_prod_style),
                            Paragraph("Special Notes", col_header_notes_style),
                        ]],
                        colWidths=col_widths,
                    )
                    header_row.setStyle(TableStyle([
                        ('VALIGN', (0, 0), (-1, -1), 'BOTTOM'),
                        ('LEFTPADDING', (0, 0), (0, -1), 0),
                        ('LEFTPADDING', (1, 0), (2, -1), 7.5),
                        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
                        ('TOPPADDING', (0, 0), (-1, -1), 1),
                        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
                        ('LINEBELOW', (0, 0), (-1, -1), 1.5, colors.black),
                    ]))
                    story.append(header_row)

                    rows = [
                        [
                            Paragraph(str(p['count']), cell_qty_style),
                            Paragraph(xml_escape(p['product_display'] or ''), cell_prod_style),
                            Paragraph(xml_escape(p['special_notes'] or ''), cell_notes_style),
                        ]
                        for p in cat['products']
                    ]
                    table = Table(rows, colWidths=col_widths)
                    table.setStyle(TableStyle([
                        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                        ('LEFTPADDING', (0, 0), (0, -1), 0),
                        ('LEFTPADDING', (1, 0), (2, -1), 7.5),
                        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
                        ('TOPPADDING', (0, 0), (-1, -1), 3),
                        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
                        ('LINEBELOW', (0, 0), (-1, -1), 0.75, colors.black),
                    ]))
                    story.append(table)
                    story.append(Spacer(1, 4 * mm))

        def _make_canvas(*args, **kwargs):
            c = _ProductionReportCanvas(*args, **kwargs)
            c.printed_at_text = printed_at_str
            c.title_text = title_text
            return c

        doc.build(story, canvasmaker=_make_canvas)
        pdf_value = buffer.getvalue()
        buffer.close()
        return pdf_value

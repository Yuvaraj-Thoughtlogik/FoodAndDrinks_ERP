# -*- coding: utf-8 -*-

import datetime
import io
from xml.sax.saxutils import escape as xml_escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    Flowable, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

from odoo import api, fields, models, _


class _DriverPackingListHeaderMarker(Flowable):
    """Same technique as _PackingListHeaderMarker in packing_list_report.py -
    see report_delivery_note_round_van.py for the full explanation.

    Carries the two-column batch header (title/code/name on the left,
    delivery date/depot on the right - matching the confirmed QWeb design
    for this report) as structured parts rather than one flat string, plus
    the report's "Printed at" timestamp, both of which _DriverPackingListCanvas
    re-draws on every page of this batch until the next batch's marker
    replaces them.
    """

    def __init__(self, header_parts, printed_at):
        super().__init__()
        self.header_parts = header_parts
        self.printed_at = printed_at
        self.width = 0
        self.height = 0

    def wrap(self, availWidth, availHeight):
        return (0, 0)

    def draw(self):
        self.canv.current_header_parts = self.header_parts
        self.canv.printed_at = self.printed_at


class _DriverPackingListCanvas(canvas.Canvas):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []
        self.current_header_parts = None
        self.printed_at = None

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self._draw_header()
            self._draw_footer(num_pages)
            super().showPage()
        super().save()

    def _draw_header(self):
        parts = self.current_header_parts
        if not parts:
            return
        self.saveState()
        margin = 12 * mm
        width = A4[0] - (2 * margin)

        title_style = ParagraphStyle('DPLTitle', fontName='Helvetica-Bold', fontSize=16.5, leading=20)
        code_name_style = ParagraphStyle('DPLCodeName', fontName='Helvetica-Bold', fontSize=12, leading=15, spaceBefore=3)
        right_style = ParagraphStyle('DPLHeaderRight', fontName='Helvetica-Bold', fontSize=12, leading=15, alignment=2)

        code_name_text = xml_escape(parts.get('batch_code') or '')
        if parts.get('batch_name'):
            code_name_text += '&nbsp;&nbsp;&nbsp;&nbsp;' + xml_escape(parts['batch_name'])

        right_text = 'Delivery On: ' + xml_escape(parts.get('delivery_date') or '')
        if parts.get('depot_name'):
            right_text += '<br/>' + xml_escape(parts['depot_name'])

        header_table = Table(
            [[
                [Paragraph(xml_escape(parts.get('title') or ''), title_style),
                 Paragraph(code_name_text, code_name_style)],
                Paragraph(right_text, right_style),
            ]],
            colWidths=[width * 0.6, width * 0.4],
        )
        header_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('LEFTPADDING', (0, 0), (-1, -1), 0),
            ('RIGHTPADDING', (0, 0), (-1, -1), 0),
            ('TOPPADDING', (0, 0), (-1, -1), 0),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
        ]))

        _, h = header_table.wrap(width, 40 * mm)
        header_table.drawOn(self, margin, A4[1] - margin - h)
        self.restoreState()

    def _draw_footer(self, num_pages):
        """Plain continuous page number ("1", "2", "3", ... - not "Page X of
        Y") centered at the bottom, matching the confirmed reference output,
        plus "Printed at: ..." right-aligned on the same footer line.
        Numbering runs across the whole report, not restarted per batch -
        self._pageNumber already counts every page of the document, batches
        included, since batches are separated by PageBreak() flowables
        rather than separate docs."""
        self.saveState()
        margin = 12 * mm
        width = A4[0] - (2 * margin)
        center_style = ParagraphStyle('DPLFooterPage', fontName='Helvetica', fontSize=7.5, leading=9, alignment=1)
        right_style = ParagraphStyle('DPLFooterPrinted', fontName='Helvetica', fontSize=7.5, leading=9, alignment=2)

        page_p = Paragraph(str(self._pageNumber), center_style)
        _, h = page_p.wrap(width, 10 * mm)
        y = margin - h - (2 * mm)
        page_p.drawOn(self, margin, y)

        if self.printed_at:
            printed_p = Paragraph('Printed at: ' + xml_escape(self.printed_at), right_style)
            printed_p.wrap(width, 10 * mm)
            printed_p.drawOn(self, margin, y)

        self.restoreState()


class ReportDriverPackingList(models.AbstractModel):
    _name = 'report.tl_rf_reports.report_driver_packing_list_document'
    _description = 'Driver Packing List Report Generator'

    # ------------------------------------------------------------------
    # Sorting helpers - same conventions as report.tl_rf_reports.report_packing_list:
    # Frozen first, Fresh second, everything else alphabetically; products
    # within a category ordered by their Product Master sort number.
    # ------------------------------------------------------------------
    @api.model
    def _get_sort_key(self, product_item):
        sort_num = product_item.get('sort_num')
        product_name = (product_item.get('product_name') or '').strip().lower()

        if not sort_num or sort_num <= 0:
            return (0, 0, product_name)

        return (1, sort_num, product_name)

    @api.model
    def _extract_sort_number(self, product):
        """Product-level sort number only. A Kit's component can differ from
        the product actually sold, so (unlike the standard Packing List) we
        deliberately don't fall back to the sale order line's sort_seq here
        - that would apply the sold product's sort position to a different,
        substituted component.
        """
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
    # Pagination - same MAX_PAGE_WEIGHT convention as the Factory Only
    # Packing List (report.tl_rf_reports.report_packing_list). Tune against
    # real print output if pages still break too early or too late.
    # ------------------------------------------------------------------
    @api.model
    def _paginate_batch_categories(self, category_list):
        MAX_PAGE_WEIGHT = 38

        pages = []
        current_page_categories = []
        current_weight = 0

        for cat in category_list:
            cat_name = cat['categ_name']
            products = cat['products']
            total_boxes = cat['total_boxes']

            prod_idx = 0
            total_prods = len(products)

            while prod_idx < total_prods:
                cat_header_cost = 2.5

                if (
                    current_page_categories
                    and (current_weight + cat_header_cost + 1 > MAX_PAGE_WEIGHT)
                ):
                    pages.append({
                        'categories': current_page_categories,
                        'is_last_page': False,
                    })
                    current_page_categories = []
                    current_weight = 0

                available_weight = MAX_PAGE_WEIGHT - current_weight - cat_header_cost
                if available_weight < 1:
                    available_weight = 1

                num_to_take = min(int(available_weight), total_prods - prod_idx)
                chunk_prods = products[prod_idx:prod_idx + num_to_take]
                prod_idx += num_to_take

                is_cat_complete = prod_idx >= total_prods

                current_page_categories.append({
                    'categ_name': cat_name,
                    'products': chunk_prods,
                    'is_complete': is_cat_complete,
                    'total_boxes': total_boxes if is_cat_complete else False,
                })

                current_weight += (
                    cat_header_cost
                    + len(chunk_prods)
                    + (1.5 if is_cat_complete else 0)
                )

                if prod_idx < total_prods:
                    pages.append({
                        'categories': current_page_categories,
                        'is_last_page': False,
                    })
                    current_page_categories = []
                    current_weight = 0

        if current_page_categories:
            pages.append({
                'categories': current_page_categories,
                'is_last_page': True,
            })
        elif pages:
            pages[-1]['is_last_page'] = True

        return pages

    @api.model
    def _number_pages_continuously(self, groups):
        flat_pages = [pg for g in groups for pg in g['pages']]
        total_pages = len(flat_pages)

        for idx, pg in enumerate(flat_pages, start=1):
            pg['page_number'] = idx
            pg['total_pages'] = total_pages

        return groups

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------
    @api.model
    def _get_report_values(self, docids, data=None):
        docs = self.env['packing.list.wizard'].browse(docids)

        now_utc = fields.Datetime.now()
        now_local = fields.Datetime.context_timestamp(self, now_utc)
        printed_at_str = now_local.strftime('%d/%m/%Y %H:%M:%S')

        all_batch_groups = []
        lang = self.env.lang or 'en_US'
        company_ids = tuple(self.env.companies.ids) if self.env.companies else (self.env.company.id,)

        for wizard in docs:
            depot_filter = ""
            params = {
                'date_from': wizard.delivery_date_from,
                'date_to': wizard.delivery_date_to,
                'company_ids': company_ids,
                'lang': lang,
            }
            if wizard.depot_ids:
                depot_filter = "AND b.depot_id IN %(depot_ids)s"
                params['depot_ids'] = tuple(wizard.depot_ids.ids)

            query = f"""
                SELECT 
                    b.id AS batch_id,
                    b.code AS batch_code,
                    b.reference AS batch_reference,
                    b.delivery_date AS batch_delivery_date,
                    sw.id AS depot_id,
                    sw.name AS depot_name,
                    rmr.id AS round_id,
                    rmr.name AS round_name,
                    so.id AS order_id,
                    sol.id AS line_id,
                    sol.product_uom_qty AS line_qty,
                    p.id AS product_id,
                    p.product_tmpl_id AS tmpl_id,
                    COALESCE(pt.name->>%(lang)s, pt.name->>'en_GB', pt.name->>'en_US', pt.name::text) AS product_name,
                    COALESCE(p.sort_seq, pt.sort_seq, 0) AS sort_num,
                    pc.id AS categ_id,
                    pc.name AS categ_name
                FROM round_management_batch b
                LEFT JOIN stock_warehouse sw ON sw.id = b.depot_id
                LEFT JOIN round_management_round rmr ON rmr.id = b.round_id
                JOIN sale_order so ON so.batch_id = b.id 
                    AND so.state IN ('sale', 'done') 
                    AND (so.delivery_channel = 'regal_van' OR so.delivery_channel IS NULL)
                JOIN sale_order_line sol ON sol.order_id = so.id 
                    AND sol.display_type IS NULL 
                    AND sol.product_id IS NOT NULL 
                    AND sol.product_uom_qty > 0
                JOIN product_product p ON p.id = sol.product_id
                JOIN product_template pt ON pt.id = p.product_tmpl_id
                LEFT JOIN product_category pc ON pc.id = pt.categ_id
                WHERE b.delivery_date >= %(date_from)s 
                  AND b.delivery_date <= %(date_to)s
                  {depot_filter}
                  AND (b.company_id IS NULL OR b.company_id IN %(company_ids)s)
                ORDER BY b.delivery_date ASC, b.code ASC, b.id ASC
            """
            self.env.cr.execute(query, params)
            rows = self.env.cr.dictfetchall()

            if not rows:
                continue

            # Gather all unique product & template IDs to pre-fetch phantom BOMs in bulk
            product_ids = tuple({r['product_id'] for r in rows})
            tmpl_ids = tuple({r['tmpl_id'] for r in rows})

            bom_query = """
                SELECT 
                    mb.id AS bom_id,
                    mb.product_id AS bom_product_id,
                    mb.product_tmpl_id AS bom_tmpl_id,
                    COALESCE(mb.product_qty, 1.0) AS bom_qty,
                    mb.sequence AS bom_sequence,
                    mbl.id AS bom_line_id,
                    mbl.product_id AS comp_product_id,
                    mbl.product_qty AS comp_line_qty,
                    p_comp.product_tmpl_id AS comp_tmpl_id,
                    COALESCE(pt_comp.name->>%(lang)s, pt_comp.name->>'en_GB', pt_comp.name->>'en_US', pt_comp.name::text) AS comp_product_name,
                    COALESCE(p_comp.sort_seq, pt_comp.sort_seq, 0) AS comp_sort_num,
                    pc_comp.id AS comp_categ_id,
                    pc_comp.name AS comp_categ_name
                FROM mrp_bom mb
                JOIN mrp_bom_line mbl ON mbl.bom_id = mb.id
                JOIN product_product p_comp ON p_comp.id = mbl.product_id
                JOIN product_template pt_comp ON pt_comp.id = p_comp.product_tmpl_id
                LEFT JOIN product_category pc_comp ON pc_comp.id = pt_comp.categ_id
                WHERE mb.type = 'phantom'
                  AND mb.active = true
                  AND (mb.company_id IS NULL OR mb.company_id IN %(company_ids)s)
                  AND (mb.product_id IN %(product_ids)s OR (mb.product_id IS NULL AND mb.product_tmpl_id IN %(tmpl_ids)s))
                ORDER BY mb.sequence ASC, mb.id ASC
            """
            self.env.cr.execute(bom_query, {
                'product_ids': product_ids,
                'tmpl_ids': tmpl_ids,
                'company_ids': company_ids,
                'lang': lang,
            })
            bom_rows = self.env.cr.dictfetchall()

            # Map BOMs: variant-specific first, fallback to template
            variant_boms = {}
            tmpl_boms = {}
            for br in bom_rows:
                b_id = br['bom_id']
                if br['bom_product_id']:
                    if br['bom_product_id'] not in variant_boms:
                        variant_boms[br['bom_product_id']] = {'qty': br['bom_qty'], 'lines': []}
                    variant_boms[br['bom_product_id']]['lines'].append(br)
                elif br['bom_tmpl_id']:
                    if br['bom_tmpl_id'] not in tmpl_boms:
                        tmpl_boms[br['bom_tmpl_id']] = {'qty': br['bom_qty'], 'lines': []}
                    tmpl_boms[br['bom_tmpl_id']]['lines'].append(br)

            # Group rows by batch
            batches_map = {}
            for r in rows:
                batch_id = r['batch_id']
                if batch_id not in batches_map:
                    batches_map[batch_id] = {
                        'batch_info': r,
                        'categories_map': {},
                    }

                b_map = batches_map[batch_id]
                qty = float(r['line_qty'] or 0.0)
                pid = r['product_id']
                tid = r['tmpl_id']

                # Check for phantom BOM explosion
                bom_info = variant_boms.get(pid) or tmpl_boms.get(tid)
                if bom_info and bom_info['lines']:
                    bom_produced_qty = bom_info['qty'] or 1.0
                    for comp in bom_info['lines']:
                        comp_qty = (comp['comp_line_qty'] / bom_produced_qty) * qty
                        if not comp_qty:
                            continue
                        categ_key = comp['comp_categ_id'] or 0
                        categ_name = (comp['comp_categ_name'] or _('Other')).strip().upper()
                        if categ_key not in b_map['categories_map']:
                            b_map['categories_map'][categ_key] = {
                                'categ_name': categ_name,
                                'products': {},
                            }
                        c_prods = b_map['categories_map'][categ_key]['products']
                        c_pid = comp['comp_product_id']
                        if c_pid not in c_prods:
                            sort_n = int(comp['comp_sort_num']) if comp['comp_sort_num'] and int(comp['comp_sort_num']) > 0 else None
                            c_prods[c_pid] = {
                                'product_id': c_pid,
                                'product_name': comp['comp_product_name'],
                                'box_qty': 0.0,
                                'sort_num': sort_n,
                                'sort_str': str(sort_n) if sort_n else '',
                            }
                        c_prods[c_pid]['box_qty'] += comp_qty
                else:
                    # Direct product
                    categ_key = r['categ_id'] or 0
                    categ_name = (r['categ_name'] or _('Other')).strip().upper()
                    if categ_key not in b_map['categories_map']:
                        b_map['categories_map'][categ_key] = {
                            'categ_name': categ_name,
                            'products': {},
                        }
                    c_prods = b_map['categories_map'][categ_key]['products']
                    if pid not in c_prods:
                        sort_n = int(r['sort_num']) if r['sort_num'] and int(r['sort_num']) > 0 else None
                        c_prods[pid] = {
                            'product_id': pid,
                            'product_name': r['product_name'],
                            'box_qty': 0.0,
                            'sort_num': sort_n,
                            'sort_str': str(sort_n) if sort_n else '',
                        }
                    c_prods[pid]['box_qty'] += qty

            # Format batches into output structure
            for batch_id, b_data in batches_map.items():
                categories_map = b_data['categories_map']
                category_list = []
                batch_total_boxes = 0

                for c_key, c_val in sorted(
                    categories_map.items(),
                    key=lambda item: self._get_category_sort_key(item[1]['categ_name'])
                ):
                    sorted_prods = sorted(c_val['products'].values(), key=self._get_sort_key)
                    for p in sorted_prods:
                        p['qty_display'] = f"{p['box_qty']:.2f}"

                    cat_total = int(round(sum(p['box_qty'] for p in sorted_prods)))
                    batch_total_boxes += cat_total

                    if sorted_prods:
                        category_list.append({
                            'categ_name': c_val['categ_name'],
                            'products': sorted_prods,
                            'total_boxes': cat_total,
                        })

                if category_list:
                    b_info = b_data['batch_info']
                    depot_name = b_info['depot_name'] or 'Grimsby'
                    delivery_date_str = (
                        b_info['batch_delivery_date'].strftime('%d/%m/%Y')
                        if b_info['batch_delivery_date']
                        else ''
                    )
                    batch_code = b_info['batch_code'] or ''
                    batch_name = b_info['round_name'] or b_info['batch_reference'] or ''

                    batch_pages = self._paginate_batch_categories(category_list)

                    all_batch_groups.append({
                        'delivery_date': delivery_date_str,
                        'depot_name': depot_name,
                        'batch_code': batch_code,
                        'batch_name': batch_name,
                        'pages': batch_pages,
                        'total_boxes': batch_total_boxes,
                    })

        all_batch_groups = self._number_pages_continuously(all_batch_groups)

        return {
            'doc_ids': docids,
            'doc_model': 'packing.list.wizard',
            'docs': docs,
            'printed_at': printed_at_str,
            'batch_groups': all_batch_groups,
        }

    # ------------------------------------------------------------------
    # Fast path: builds the PDF directly with ReportLab instead of QWeb+
    # wkhtmltopdf. The raw-SQL + BOM-explosion data layer above is reused
    # as-is (already fast); only the *rendering* step changes. See
    # report_delivery_note_round_courier.py for the general approach and
    # report_delivery_note_round_van.py for the repeating-header-per-group
    # technique (_DriverPackingListHeaderMarker / _DriverPackingListCanvas
    # above are the same idea, renamed for this file).
    # ------------------------------------------------------------------
    PRINTABLE_WIDTH = A4[0] - (24 * mm)

    def _pdf_styles(self):
        return {
            # 16px bold uppercase category name -> ~12pt bold.
            'category': ParagraphStyle('DPLCategory', fontName='Helvetica-Bold', fontSize=12, leading=15),
            # "Quantity" / "Product / Box Contents" column headers: 14px
            # bold italic -> ~10.5pt.
            'col_header': ParagraphStyle('DPLColHeader', fontName='Helvetica-BoldOblique', fontSize=10.5, leading=13),
            # "Sort" column header is deliberately plain/smaller in the
            # confirmed design: 13px normal weight -> ~9.75pt, right-aligned.
            'col_header_sort': ParagraphStyle('DPLColHeaderSort', fontName='Helvetica', fontSize=9.75, leading=12, alignment=2),
            # Product / Sort cell text: 15px normal -> ~11pt.
            'cell': ParagraphStyle('DPLCell', fontName='Helvetica', fontSize=11, leading=14),
            'cell_sort': ParagraphStyle('DPLCellSort', fontName='Helvetica', fontSize=11, leading=14, alignment=2),
            # Quantity cell: same size, bold, right-aligned.
            'cell_bold': ParagraphStyle('DPLCellBold', fontName='Helvetica-Bold', fontSize=11, leading=14, alignment=2),
            # "Checked By ___": 14px -> ~10.5pt, right-aligned.
            'checked_by': ParagraphStyle('DPLCheckedBy', fontName='Helvetica', fontSize=10.5, leading=13, alignment=2),
        }

    def generate_pdf(self, wizard):
        """Returns the finished PDF (bytes) for one Driver Packing List
        wizard, or None when there is nothing to print.

        This is now the ACTIVE rendering path (wired from the wizard's
        print button - see packing_list_wizard.py), replacing the QWeb
        template. The visual design deliberately mirrors the confirmed
        QWeb layout: title "Drivers Packing List : Customer" with the
        batch code/name below it on the left, "Delivery On" + depot on the
        right, uppercase bold category headers, a Quantity/Product/Sort
        column header row, quantity right-aligned with 2 decimal places,
        no "Boxes" total line, and "Checked By ___" once at the end of
        each batch. Category/Batch grouping and sorting (Frozen -> Fresh ->
        alphabetical, then Product Master sort number) are unchanged from
        before.

        Sourced from sale.order.line.report_lines (same BoM-exploded rows
        as the Factory Only Packing List - see SaleOrderLine.
        _get_report_line_vals), but combining BOTH normal and late_order
        rows into one total per product: unlike the other Packing List
        variants, the Driver Packing List is an overall total across the
        whole date range and deliberately does not filter on Late Order
        status (see PackingListWizard._action_print_driver_packing_list)."""
        line_domain = [
            ('delivery_channel', 'in', ('regal_van', False)),
            ('order_id.state', 'in', ('sale', 'done')),
            ('delivery_date', '>=', wizard.delivery_date_from),
            ('delivery_date', '<=', wizard.delivery_date_to),
            ('display_type', '=', False),
            ('product_id', '!=', False),
            ('product_uom_qty', '>', 0),
        ]
        if wizard.depot_ids:
            line_domain.append(('depot_id', 'in', wizard.depot_ids.ids))

        order_lines = self.env['sale.order.line'].search(line_domain)
        if not order_lines:
            return None

        # Force-refresh report_line_ids so a BoM line reflects the current
        # Manufacturing Order / move_raw_ids state (see
        # SaleOrderLine._recompute_report_lines) before reading them.
        order_lines._recompute_report_lines()

        report_lines = self.env['sale.order.line.report_lines'].search(
            [('sale_order_line_id', 'in', order_lines.ids)]
        )
        if not report_lines:
            return None

        report_lines = report_lines.sorted(
            lambda rl: (rl.batch_id.delivery_date or datetime.date.min, rl.batch_id.code or '', rl.batch_id.id)
        )

        batches_map = {}
        for report_line in report_lines:
            batch = report_line.batch_id
            product = report_line.product_id
            if not batch or not product:
                continue

            if batch.id not in batches_map:
                batches_map[batch.id] = {'batch': batch, 'categories_map': {}}
            b_map = batches_map[batch.id]

            categ_name = (report_line.categ_id.name or _('Other')).strip().upper()
            categ_key = report_line.categ_id.id or 0
            b_map['categories_map'].setdefault(categ_key, {'categ_name': categ_name, 'products': {}})
            c_prods = b_map['categories_map'][categ_key]['products']

            # BoM rows (physical boxes) stay separate by box qty (0.5kg vs
            # 1kg); a plain non-BoM row's qty is just the line's own
            # quantity, so those merge/sum together regardless of value -
            # this report combines normal + late rows into one total, so a
            # +2 confirmed and a -1 late delta must net to 1, not print as
            # two separate rows.
            group_key = (product.id, report_line.qty if report_line.from_bom else False, report_line.notes or '')
            if group_key not in c_prods:
                sort_num = self._extract_sort_number(product)
                c_prods[group_key] = {
                    'product_id': product.id,
                    'product_name': report_line.name or product.name,
                    'box_qty': 0.0,
                    'sort_num': sort_num,
                    'sort_str': str(sort_num) if sort_num else '',
                }
            # A BoM row is one MO's raw-material consumption - one row is
            # one physical box, so same-product rows are COUNTED (matching
            # the Factory Only Packing List). A plain non-BoM row's qty IS
            # the line's own quantity, so those are SUMMED instead.
            if report_line.from_bom:
                c_prods[group_key]['box_qty'] += 1
            else:
                c_prods[group_key]['box_qty'] += report_line.qty

        if not batches_map:
            return None

        now_utc = fields.Datetime.now()
        now_local = fields.Datetime.context_timestamp(self, now_utc)
        printed_at_str = now_local.strftime('%d/%m/%Y %H:%M:%S')

        styles = self._pdf_styles()
        width = self.PRINTABLE_WIDTH
        # 75px / 65px fixed columns out of a ~527pt printable width, same
        # proportions as the confirmed QWeb column widths.
        qty_w = width * 0.12
        sort_w = width * 0.10
        prod_w = width - qty_w - sort_w
        story = []
        printed_batches = 0

        for batch_id, b_data in batches_map.items():
            category_list = []
            for c_key, c_val in sorted(
                b_data['categories_map'].items(), key=lambda item: self._get_category_sort_key(item[1]['categ_name'])
            ):
                sorted_prods = sorted(c_val['products'].values(), key=self._get_sort_key)
                for p in sorted_prods:
                    qty_val = p['box_qty']
                    p['qty_display'] = str(int(round(qty_val))) if float(qty_val).is_integer() else f"{qty_val:.2f}"
                if sorted_prods:
                    category_list.append({'categ_name': c_val['categ_name'], 'products': sorted_prods})
            if not category_list:
                continue

            if printed_batches:
                story.append(PageBreak())
            printed_batches += 1

            batch = b_data['batch']
            depot_name = batch.depot_id.name or 'Grimsby'
            delivery_date_str = batch.delivery_date.strftime('%d/%m/%Y') if batch.delivery_date else ''
            batch_code = batch.code or ''
            batch_name = (batch.round_id.name if batch.round_id else False) or batch.reference or ''

            header_parts = {
                'title': 'Drivers Packing List : Customer',
                'batch_code': batch_code,
                'batch_name': batch_name,
                'delivery_date': delivery_date_str,
                'depot_name': depot_name,
            }
            story.append(_DriverPackingListHeaderMarker(header_parts, printed_at_str))
            story.append(Spacer(1, 4 * mm))

            for cat in category_list:
                header_row = Table(
                    [[Paragraph("Quantity", styles['col_header']), Paragraph("Product / Box Contents", styles['col_header']),
                      Paragraph("Sort", styles['col_header_sort'])]],
                    colWidths=[qty_w, prod_w, sort_w],
                )
                header_row.setStyle(TableStyle([
                    ('LINEBELOW', (0, 0), (-1, 0), 2, colors.black),
                    ('LEFTPADDING', (1, 0), (1, 0), 8), ('RIGHTPADDING', (0, 0), (0, 0), 8),
                ]))

                rows_ = [[
                    Paragraph(xml_escape(p['qty_display']), styles['cell_bold']),
                    Paragraph(xml_escape(p['product_name'] or ''), styles['cell']),
                    Paragraph(xml_escape(p['sort_str']), styles['cell_sort']),
                ] for p in cat['products']]
                table = Table(rows_, colWidths=[qty_w, prod_w, sort_w])
                table.setStyle(TableStyle([
                    ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                    ('LEFTPADDING', (1, 0), (1, -1), 8), ('RIGHTPADDING', (0, 0), (0, -1), 8),
                    ('LINEBELOW', (0, 0), (-1, -1), 0.5, colors.black),
                    ('TOPPADDING', (0, 0), (-1, -1), 3), ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
                ]))

                story.append(KeepTogether([
                    Paragraph(xml_escape(cat['categ_name']), styles['category']),
                    Spacer(1, 2 * mm), header_row, table,
                    Spacer(1, 5 * mm),
                ]))

            story.append(Spacer(1, 8 * mm))
            story.append(Paragraph("Checked By _____________________", styles['checked_by']))

        if not printed_batches:
            return None

        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer, pagesize=A4,
            leftMargin=12 * mm, rightMargin=12 * mm, topMargin=32 * mm, bottomMargin=12 * mm,
        )
        doc.build(story, canvasmaker=_DriverPackingListCanvas)
        pdf_value = buffer.getvalue()
        buffer.close()
        return pdf_value
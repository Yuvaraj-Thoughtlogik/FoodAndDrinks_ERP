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
    Flowable, HRFlowable, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

from odoo import api, fields, models, _


class _PackingListHeaderMarker(Flowable):
    """Zero-size flowable that stamps the current group's header text or dict onto
    the canvas as soon as ReportLab draws it."""

    def __init__(self, header_data):
        super().__init__()
        self.header_data = header_data
        self.width = 0
        self.height = 0

    def wrap(self, availWidth, availHeight):
        return (0, 0)

    def draw(self):
        self.canv.current_header = self.header_data


class _PackingListCanvas(canvas.Canvas):
    """Two-pass canvas: replays every page once the header stamped by
    _PackingListHeaderMarker for that page is known, drawing the 2-column batch
    header banner and footer for Regal Van reports."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []
        self.current_header = None
        self.printed_at_text = ''
        self.delivery_channel = 'regal_van'

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

        if self.delivery_channel == 'regal_van':
            if self.current_header and isinstance(self.current_header, dict):
                h_data = self.current_header
                title_style = ParagraphStyle(
                    'PLVanTitle', fontName='Helvetica-Bold', fontSize=16.5, leading=20, textColor=colors.black
                )
                batch_style = ParagraphStyle(
                    'PLVanBatch', fontName='Helvetica-Bold', fontSize=12, leading=15, spaceBefore=3, textColor=colors.black
                )
                date_style = ParagraphStyle(
                    'PLVanDate', fontName='Helvetica-Bold', fontSize=12, leading=15, alignment=2, textColor=colors.black
                )
                depot_style = ParagraphStyle(
                    'PLVanDepot', fontName='Helvetica-Bold', fontSize=12, leading=15, alignment=2, textColor=colors.black
                )

                left_flow = [
                    Paragraph("Factory Only Packing List", title_style),
                    Paragraph(
                        f"{xml_escape(h_data.get('batch_code', ''))}&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;{xml_escape(h_data.get('batch_name', ''))}",
                        batch_style,
                    ),
                ]
                right_flow = [
                    Paragraph(f"Delivery On: {xml_escape(h_data.get('delivery_date', ''))}", date_style),
                ]
                if h_data.get('depot_name'):
                    right_flow.append(Paragraph(xml_escape(h_data.get('depot_name', '')), depot_style))

                header_tbl = Table(
                    [[left_flow, right_flow]],
                    colWidths=[width * 0.58, width * 0.42],
                )
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
                    'PLVanFooterR', fontName='Helvetica', fontSize=9, leading=11, alignment=2, textColor=colors.black
                )
                footer_r = Paragraph(f"Printed at: {xml_escape(self.printed_at_text)}", footer_style_right)
                footer_r.wrap(width, 8 * mm)
                footer_r.drawOn(self, margin, 6 * mm)

            page_style_center = ParagraphStyle(
                'PLVanFooterC', fontName='Helvetica', fontSize=9, leading=11, alignment=0, textColor=colors.black
            )
            page_p = Paragraph(str(self._pageNumber), page_style_center)
            page_p.wrap(40 * mm, 8 * mm)
            page_p.drawOn(self, margin + (width * 0.48), 6 * mm)

        self.restoreState()


class ReportPackingList(models.AbstractModel):
    _name = 'report.tl_rf_reports.report_packing_list'
    _description = 'Packing List Report Generator'

    @api.model
    def _get_sort_key(self, product_item):
        """Implements sorting logic:

        1. Products with empty sort appear first.
        2. Products with numerical sort are in ascending order.
        3. Equal sort numbers (or empty) are ordered alphabetically
           by product name (A-Z).
        """
        sort_num = product_item.get('sort_num')
        product_name = (
            product_item.get('product_name') or ''
        ).strip().lower()

        if not sort_num or sort_num <= 0:
            return (0, 0, product_name)

        return (1, sort_num, product_name)

    @api.model
    def _extract_sort_number(self, product, line=None):
        """Extracts the integer sort sequence from product master
        or sale order line.
        """
        sort_val = 0

        if line and hasattr(line, 'sort_seq') and line.sort_seq:
            sort_val = line.sort_seq

        elif product:
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
        """Custom product-category ordering for the report:

        1. Categories containing FROZEN come first.
        2. Categories containing FRESH come second.
        3. All other categories follow alphabetically (A-Z).

        Examples:

            FROZEN
            FROZEN FISH
            FRESH

        """

        name = (categ_name or '').strip().upper()

        # FROZEN categories always come first
        if 'FROZEN' in name:
            return (0, name)

        # FRESH categories always come second
        if 'FRESH' in name:
            return (1, name)

        # Everything else alphabetically
        return (2, name)

    def _format_customer_name(self, partner):
        if not partner:
            return ""

        name_parts = []

        partner_title = getattr(partner, 'title', False)

        if partner_title and getattr(partner_title, 'name', False):
            title_name = partner_title.name.strip()

            if partner.name and not partner.name.strip().startswith(
                title_name
            ):
                name_parts.append(title_name)

        if partner.name:
            name_parts.append(partner.name.strip())

        return " ".join(name_parts).strip() or partner.name or ""

    def _format_address_lines(self, partner):
        if not partner:
            return {
                'line1': '',
                'line2': '',
            }

        line1_parts = [
            getattr(partner, 'street', '') or '',
            getattr(partner, 'street2', '') or '',
            getattr(partner, 'city', '') or '',
        ]

        line1 = " ".join(
            [
                p.strip()
                for p in line1_parts
                if p and p.strip()
            ]
        )

        state_name = (
            partner.state_id.name
            if getattr(partner, 'state_id', False)
            and partner.state_id
            else ''
        )

        line2_parts = [
            state_name,
            getattr(partner, 'zip', '') or '',
        ]

        line2 = " ".join(
            [
                p.strip()
                for p in line2_parts
                if p and p.strip()
            ]
        )

        return {
            'line1': line1,
            'line2': line2,
        }

    def _paginate_batch_categories(self, category_list):
        """Splits a batch's categories and products into distinct pages so
        that:

        1. Every page has the batch header.
        2. Every page has the category header and column headers
           for any category on that page.
        3. If a category spans multiple pages, the category header is
           repeated on the next page.
        4. Box totals are shown when a category finishes.
        5. The last page of the batch has is_last_page: True.

        NOTE:
        MAX_PAGE_WEIGHT is a proxy for how much vertical space a page has,
        NOT a real mm/px measurement.

        It was previously set far too low (14), which caused pages to break
        after only ~9 product rows even though an A4 page fits roughly
        35-45 rows.

        Tune this constant against real print output if pages still break
        too early or too late.
        """

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
                    and (
                        current_weight
                        + cat_header_cost
                        + 1
                        > MAX_PAGE_WEIGHT
                    )
                ):
                    pages.append({
                        'categories': current_page_categories,
                        'is_last_page': False,
                    })

                    current_page_categories = []
                    current_weight = 0

                available_weight = (
                    MAX_PAGE_WEIGHT
                    - current_weight
                    - cat_header_cost
                )

                if available_weight < 1:
                    available_weight = 1

                num_to_take = min(
                    int(available_weight),
                    total_prods - prod_idx
                )

                chunk_prods = products[
                    prod_idx:prod_idx + num_to_take
                ]

                prod_idx += num_to_take

                is_cat_complete = prod_idx >= total_prods
                is_fresh_or_smoked = ('FRESH' in cat_name) or ('SMOKED' in cat_name)

                current_page_categories.append({
                    'categ_name': cat_name,
                    'products': chunk_prods,
                    'is_complete': is_cat_complete,
                    'total_boxes': (
                        total_boxes
                        if (is_cat_complete and is_fresh_or_smoked)
                        else False
                    ),
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

    def _paginate_courier_categories(self, category_list):
        """Splits a courier customer's categories into distinct pages
        so headers repeat seamlessly.

        See note in _paginate_batch_categories regarding MAX_PAGE_WEIGHT
        being a proxy, not a real measurement.
        """

        MAX_PAGE_WEIGHT = 34

        pages = []
        current_page_categories = []
        current_weight = 0

        for cat in category_list:
            cat_name = cat['categ_name']
            products = cat['products']

            prod_idx = 0
            total_prods = len(products)

            while prod_idx < total_prods:
                cat_header_cost = 2.0

                if (
                    current_page_categories
                    and (
                        current_weight
                        + cat_header_cost
                        + 1
                        > MAX_PAGE_WEIGHT
                    )
                ):
                    pages.append({
                        'categories': current_page_categories,
                        'is_last_page': False,
                    })

                    current_page_categories = []
                    current_weight = 0

                available_weight = (
                    MAX_PAGE_WEIGHT
                    - current_weight
                    - cat_header_cost
                )

                if available_weight < 1:
                    available_weight = 1

                num_to_take = min(
                    int(available_weight),
                    total_prods - prod_idx
                )

                chunk_prods = products[
                    prod_idx:prod_idx + num_to_take
                ]

                prod_idx += num_to_take

                current_page_categories.append({
                    'categ_name': cat_name,
                    'products': chunk_prods,
                })

                current_weight += (
                    cat_header_cost
                    + len(chunk_prods)
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
        """Stamps page_number/total_pages onto every page dict across
        ALL groups (batches or customer orders), so the footer shows
        one running sequence for the whole report instead of restarting
        per batch/order.
        """

        flat_pages = [
            pg
            for g in groups
            for pg in g['pages']
        ]

        total_pages = len(flat_pages)

        for idx, pg in enumerate(flat_pages, start=1):
            pg['page_number'] = idx
            pg['total_pages'] = total_pages

        return groups

    @api.model
    def _get_report_values(self, docids, data=None):
        docs = self.env['packing.list.wizard'].browse(docids)

        now_utc = fields.Datetime.now()
        now_local = fields.Datetime.context_timestamp(
            self,
            now_utc
        )

        printed_at_str = now_local.strftime(
            '%d/%m/%Y %H:%M:%S'
        )

        wizard = docs[0] if docs else False

        delivery_channel = (
            getattr(
                wizard,
                'delivery_channel',
                'regal_van'
            )
            if wizard
            else 'regal_van'
        )

        lang = self.env.lang or 'en_US'
        company_ids = tuple(self.env.companies.ids) if self.env.companies else (self.env.company.id,)

        # ----------------------------------------------------
        # COURIER DELIVERY FLOW
        # CUSTOMER-WISE PACKING LIST
        # ----------------------------------------------------

        if delivery_channel == 'courier':

            all_customer_orders = []

            packing_date_from_str = ''
            packing_date_to_str = ''
            delivery_date_from_str = ''
            delivery_date_to_str = ''

            for wiz in docs:

                p_from = (
                    getattr(
                        wiz,
                        'packing_date_from',
                        False
                    )
                    or (
                        wiz.delivery_date_from
                        - datetime.timedelta(days=1)
                    )
                    if wiz.delivery_date_from
                    else False
                )

                p_to = (
                    getattr(
                        wiz,
                        'packing_date_to',
                        False
                    )
                    or (
                        wiz.delivery_date_to
                        - datetime.timedelta(days=1)
                    )
                    if wiz.delivery_date_to
                    else False
                )

                packing_date_from_str = (
                    p_from.strftime('%d/%m/%Y')
                    if p_from
                    else ''
                )

                packing_date_to_str = (
                    p_to.strftime('%d/%m/%Y')
                    if p_to
                    else ''
                )

                delivery_date_from_str = (
                    wiz.delivery_date_from.strftime('%d/%m/%Y')
                    if wiz.delivery_date_from
                    else ''
                )

                delivery_date_to_str = (
                    wiz.delivery_date_to.strftime('%d/%m/%Y')
                    if wiz.delivery_date_to
                    else ''
                )

                courier_query = """
                    SELECT 
                        so.id AS order_id,
                        so.name AS order_name,
                        so.delivery_date AS order_delivery_date,
                        rp_main.id AS main_partner_id,
                        rp_main.name AS main_partner_name,
                        rp_main.customer_code AS customer_code,
                        rp_main.ref AS main_partner_ref,
                        rpt.name AS partner_title_name,
                        rp_ship.id AS ship_partner_id,
                        rp_ship.street AS ship_street,
                        rp_ship.street2 AS ship_street2,
                        rp_ship.city AS ship_city,
                        rp_ship.zip AS ship_zip,
                        rcs.name AS ship_state_name,
                        sol.id AS line_id,
                        sol.product_uom_qty AS line_qty,
                        sol.name AS line_name,
                        COALESCE(sol.sort_seq, p.sort_seq, pt.sort_seq, 0) AS sort_num,
                        p.id AS product_id,
                        COALESCE(p.weight, pt.weight, 0.0) AS product_weight,
                        COALESCE(pt.name->>%(lang)s, pt.name->>'en_GB', pt.name->>'en_US', pt.name::text) AS product_name,
                        pc.id AS categ_id,
                        pc.name AS categ_name
                    FROM sale_order so
                    JOIN res_partner rp_main ON rp_main.id = so.partner_id
                    LEFT JOIN res_partner_title rpt ON rpt.id = rp_main.title
                    LEFT JOIN res_partner rp_ship ON rp_ship.id = COALESCE(so.partner_shipping_id, so.partner_id)
                    LEFT JOIN res_country_state rcs ON rcs.id = rp_ship.state_id
                    JOIN sale_order_line sol ON sol.order_id = so.id 
                        AND sol.display_type IS NULL 
                        AND sol.product_id IS NOT NULL 
                        AND sol.product_uom_qty > 0
                    JOIN product_product p ON p.id = sol.product_id
                    JOIN product_template pt ON pt.id = p.product_tmpl_id
                    LEFT JOIN product_category pc ON pc.id = pt.categ_id
                    WHERE so.delivery_channel = 'courier'
                      AND so.state IN ('sale', 'done')
                      AND so.delivery_date >= %(date_from)s
                      AND so.delivery_date <= %(date_to)s
                      AND COALESCE(so.is_late_order, false) = %(is_late)s
                      AND (so.company_id IS NULL OR so.company_id IN %(company_ids)s)
                    ORDER BY so.delivery_date ASC, so.name ASC, sol.id ASC
                """
                params = {
                    'date_from': wiz.delivery_date_from,
                    'date_to': wiz.delivery_date_to,
                    'is_late': bool(wiz.include_late_orders),
                    'company_ids': company_ids,
                    'lang': lang,
                }
                self.env.cr.execute(courier_query, params)
                c_rows = self.env.cr.dictfetchall()

                # Group by Order
                orders_map = {}
                for r in c_rows:
                    oid = r['order_id']
                    if oid not in orders_map:
                        # Format partner names and addresses
                        name_parts = []
                        if r['partner_title_name']:
                            t_name = r['partner_title_name'].strip()
                            p_name = (r['main_partner_name'] or '').strip()
                            if not p_name.lower().startswith(t_name.lower()):
                                name_parts.append(t_name)
                        if r['main_partner_name']:
                            name_parts.append(r['main_partner_name'].strip())
                        cust_name = " ".join(name_parts).strip() or r['main_partner_name'] or ""

                        l1_parts = [r['ship_street'] or '', r['ship_street2'] or '', r['ship_city'] or '']
                        line1 = " ".join([p.strip() for p in l1_parts if p and p.strip()])
                        l2_parts = [r['ship_state_name'] or '', r['ship_zip'] or '']
                        line2 = " ".join([p.strip() for p in l2_parts if p and p.strip()])

                        orders_map[oid] = {
                            'order_id': oid,
                            'order_name': r['order_name'],
                            'delivery_date': r['order_delivery_date'].strftime('%d/%m/%Y') if r['order_delivery_date'] else '',
                            'customer_code': r['customer_code'] or r['main_partner_ref'] or r['order_name'] or '',
                            'customer_name': cust_name,
                            'address_line1': line1,
                            'address_line2': line2,
                            'categories_map': {},
                            'total_order_weight_g': 0.0,
                        }

                    o_data = orders_map[oid]
                    categ_name = (r['categ_name'] or _('Other')).strip().upper()
                    categ_key = (0, categ_name)

                    if categ_key not in o_data['categories_map']:
                        o_data['categories_map'][categ_key] = {
                            'categ_name': categ_name,
                            'products': [],
                        }

                    qty_val = float(r['line_qty'] or 0.0)
                    unit_weight_kg = float(r['product_weight'] or 0.0)
                    line_weight_kg = unit_weight_kg * qty_val
                    line_weight_g = round(line_weight_kg * 1000)
                    o_data['total_order_weight_g'] += line_weight_g

                    qty_display = int(round(qty_val)) if float(qty_val).is_integer() else qty_val
                    sort_n = int(r['sort_num']) if r['sort_num'] and int(r['sort_num']) > 0 else None

                    o_data['categories_map'][categ_key]['products'].append({
                        'qty': qty_display,
                        'product_name': r['product_name'] or r['line_name'] or '',
                        'weight_g': line_weight_g,
                        'weight_display': int(round(line_weight_g)),
                        'sort_num': sort_n,
                    })

                for oid, o_data in orders_map.items():
                    category_list = []
                    for c_key, c_val in sorted(
                        o_data['categories_map'].items(),
                        key=lambda item: self._get_category_sort_key(item[1]['categ_name'])
                    ):
                        sorted_prods = sorted(c_val['products'], key=self._get_sort_key)
                        if sorted_prods:
                            category_list.append({
                                'categ_name': c_val['categ_name'],
                                'products': sorted_prods,
                            })

                    order_pages = self._paginate_courier_categories(category_list)
                    all_customer_orders.append({
                        'order_id': o_data['order_id'],
                        'order_name': o_data['order_name'],
                        'delivery_date': o_data['delivery_date'],
                        'customer_code': o_data['customer_code'],
                        'customer_name': o_data['customer_name'],
                        'address_line1': o_data['address_line1'],
                        'address_line2': o_data['address_line2'],
                        'pages': order_pages,
                        'total_weight_g': int(round(o_data['total_order_weight_g'])),
                    })

            all_customer_orders = self._number_pages_continuously(all_customer_orders)

            return {
                'doc_ids': docids,
                'doc_model': 'packing.list.wizard',
                'docs': docs,
                'printed_at': printed_at_str,
                'delivery_channel': 'courier',
                'packing_date_from_str': packing_date_from_str,
                'packing_date_to_str': packing_date_to_str,
                'delivery_date_from_str': delivery_date_from_str,
                'delivery_date_to_str': delivery_date_to_str,
                'customer_orders': all_customer_orders,
            }

        # ----------------------------------------------------
        # REGAL VAN DELIVERY FLOW
        # BATCH-BASED FACTORY ONLY PACKING LIST
        # ----------------------------------------------------

        all_batch_groups = []

        for wizard in docs:
            depot_filter = ""
            params = {
                'date_from': wizard.delivery_date_from,
                'date_to': wizard.delivery_date_to,
                'is_late': bool(wizard.include_late_orders),
                'company_ids': company_ids,
                'lang': lang,
            }
            if wizard.depot_ids:
                depot_filter = "AND b.depot_id IN %(depot_ids)s"
                params['depot_ids'] = tuple(wizard.depot_ids.ids)

            van_query = f"""
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
                    COALESCE(NULLIF(sol.box_qty, 0), sol.product_uom_qty, 0.0) AS effective_qty,
                    sol.box_qty AS box_qty,
                    sol.product_uom_qty AS product_uom_qty,
                    COALESCE(sol.sort_seq, p.sort_seq, pt.sort_seq, 0) AS sort_num,
                    p.id AS product_id,
                    COALESCE(pt.name->>%(lang)s, pt.name->>'en_GB', pt.name->>'en_US', pt.name::text) AS product_name,
                    pc.id AS categ_id,
                    pc.name AS categ_name
                FROM round_management_batch b
                LEFT JOIN stock_warehouse sw ON sw.id = b.depot_id
                LEFT JOIN round_management_round rmr ON rmr.id = b.round_id
                JOIN sale_order so ON so.batch_id = b.id 
                    AND so.state IN ('sale', 'done') 
                    AND (so.delivery_channel = 'regal_van' OR so.delivery_channel IS NULL)
                    AND COALESCE(so.is_late_order, false) = %(is_late)s
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
                ORDER BY b.delivery_date ASC, b.code ASC, b.id ASC, sol.id ASC
            """
            self.env.cr.execute(van_query, params)
            v_rows = self.env.cr.dictfetchall()

            if not v_rows:
                continue

            batches_map = {}
            for r in v_rows:
                bid = r['batch_id']
                if bid not in batches_map:
                    batches_map[bid] = {
                        'batch_info': r,
                        'categories_map': {},
                    }

                b_map = batches_map[bid]
                categ_key = r['categ_id'] or 0
                categ_name = (r['categ_name'] or _('Other')).strip().upper()

                if categ_key not in b_map['categories_map']:
                    b_map['categories_map'][categ_key] = {
                        'categ_name': categ_name,
                        'products': {},
                    }

                pid = r['product_id']
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

                c_prods[pid]['box_qty'] += float(r['effective_qty'] or 0.0)

            for bid, b_data in batches_map.items():
                categories_map = b_data['categories_map']
                category_list = []
                batch_total_boxes = 0

                for c_key, c_val in sorted(
                    categories_map.items(),
                    key=lambda item: self._get_category_sort_key(item[1]['categ_name'])
                ):
                    sorted_prods = sorted(c_val['products'].values(), key=self._get_sort_key)
                    for p in sorted_prods:
                        p['qty_display'] = (
                            int(round(p['box_qty']))
                            if float(p['box_qty']).is_integer()
                            else p['box_qty']
                        )

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
            'delivery_channel': 'regal_van',
            'batch_groups': all_batch_groups,
        }

    # ------------------------------------------------------------------
    # Fast path: builds the PDF directly with ReportLab instead of QWeb+
    # wkhtmltopdf. The raw-SQL data layer above is already fast (it exists
    # specifically to avoid N+1 ORM queries) and is reused as-is; only the
    # *rendering* step changes. See report_delivery_note_round_courier.py
    # for the general approach and report_delivery_note_round_van.py for the
    # repeating-header-per-group technique (_PackingListHeaderMarker /
    # _PackingListCanvas above are the same idea, renamed for this file).
    # ------------------------------------------------------------------
    PRINTABLE_WIDTH = A4[0] - (24 * mm)

    def generate_pdf(self, wizard):
        """Returns the finished PDF (bytes) for one Packing List wizard, or
        None when there is nothing to print."""
        if wizard.delivery_channel == 'courier':
            return self._generate_courier_pdf(wizard)
        return self._generate_van_pdf(wizard)

    def _generate_courier_pdf(self, wizard):
        """Generates pixel-perfect Courier Packing List PDF matching reference design."""
        p_from = (
            wizard.packing_date_from or (wizard.delivery_date_from - datetime.timedelta(days=1))
            if wizard.delivery_date_from else False
        )
        p_to = (
            wizard.packing_date_to or (wizard.delivery_date_to - datetime.timedelta(days=1))
            if wizard.delivery_date_to else False
        )
        packing_date_from_str = p_from.strftime('%d/%m/%Y') if p_from else ''
        packing_date_to_str = p_to.strftime('%d/%m/%Y') if p_to else ''
        delivery_date_from_str = wizard.delivery_date_from.strftime('%d/%m/%Y') if wizard.delivery_date_from else ''
        delivery_date_to_str = wizard.delivery_date_to.strftime('%d/%m/%Y') if wizard.delivery_date_to else ''

        order_domain = [
            ('delivery_channel', '=', 'courier'),
            ('state', 'in', ['sale', 'done']),
            ('delivery_date', '>=', wizard.delivery_date_from),
            ('delivery_date', '<=', wizard.delivery_date_to),
            ('is_late_order', '=', bool(wizard.include_late_orders)),
        ]
        orders = self.env['sale.order'].search(order_domain, order='delivery_date asc, name asc')
        if not orders:
            return None

        orders_map = {}
        for order in orders:
            lines = order.order_line.filtered(
                lambda l: not l.display_type and l.product_id and l.product_uom_qty > 0
            )
            if not lines:
                continue

            main_partner = order.partner_id
            ship_partner = order.partner_shipping_id or main_partner
            cust_name = self._format_customer_name(main_partner)
            addr = self._format_address_lines(ship_partner)

            o_data = orders_map[order.id] = {
                'order_name': order.name,
                'delivery_date': order.delivery_date.strftime('%d/%m/%Y') if order.delivery_date else '',
                'customer_code': getattr(main_partner, 'customer_code', False) or main_partner.ref or order.name or '',
                'customer_name': cust_name,
                'address_line1': addr['line1'],
                'address_line2': addr['line2'],
                'categories_map': {},
                'total_order_weight_g': 0.0,
            }

            for line in lines:
                product = line.product_id
                categ_name = (product.categ_id.name or _('Other')).strip().upper()
                categ_key = (0, categ_name)
                if categ_key not in o_data['categories_map']:
                    o_data['categories_map'][categ_key] = {'categ_name': categ_name, 'products': []}

                qty_val = line.product_uom_qty
                unit_weight_kg = product.weight or product.product_tmpl_id.weight or 0.0
                line_weight_g = round(unit_weight_kg * qty_val * 1000)
                o_data['total_order_weight_g'] += line_weight_g

                sort_num = self._extract_sort_number(product, line)
                qty_display = int(round(qty_val)) if float(qty_val).is_integer() else qty_val
                o_data['categories_map'][categ_key]['products'].append({
                    'qty': qty_display,
                    'product_name': product.name or line.name or '',
                    'weight_display': int(round(line_weight_g)),
                    'sort_num': sort_num,
                })

        if not orders_map:
            return None

        styles = {
            'doc_title': ParagraphStyle('CourierDocTitle', fontName='Helvetica-Bold', fontSize=22, leading=26, textColor=colors.black),
            'doc_dates': ParagraphStyle('CourierDocDates', fontName='Helvetica', fontSize=10.5, leading=14, alignment=2, textColor=colors.black),
            'cust_name': ParagraphStyle('CourierCustName', fontName='Helvetica-Bold', fontSize=13, leading=16, textColor=colors.black),
            'cust_addr': ParagraphStyle('CourierCustAddr', fontName='Helvetica-Bold', fontSize=13, leading=16, alignment=2, textColor=colors.black),
            'category': ParagraphStyle('CourierCategory', fontName='Helvetica-Bold', fontSize=12, leading=15, textColor=colors.black),
            'cell_qty': ParagraphStyle('CourierQty', fontName='Helvetica-Bold', fontSize=11, leading=14, textColor=colors.black),
            'cell_x': ParagraphStyle('CourierX', fontName='Helvetica-Bold', fontSize=11, leading=14, alignment=1, textColor=colors.black),
            'cell_name': ParagraphStyle('CourierName', fontName='Helvetica', fontSize=11, leading=14, textColor=colors.black),
            'cell_weight': ParagraphStyle('CourierWeight', fontName='Helvetica', fontSize=11, leading=14, alignment=2, textColor=colors.black),
            'total_label': ParagraphStyle('CourierTotalLabel', fontName='Helvetica-Bold', fontSize=10.5, leading=13, alignment=2, textColor=colors.black),
            'total_val': ParagraphStyle('CourierTotalVal', fontName='Helvetica', fontSize=11, leading=13, alignment=2, textColor=colors.black),
        }
        width = self.PRINTABLE_WIDTH
        story = []

        # Top Document Header on First Page
        top_header_table = Table(
            [[
                Paragraph("Courier Packing List", styles['doc_title']),
                Paragraph(
                    f"For Packing between {xml_escape(packing_date_from_str)} and {xml_escape(packing_date_to_str)}<br/>"
                    f"(Delivery {xml_escape(delivery_date_from_str)}-{xml_escape(delivery_date_to_str)})",
                    styles['doc_dates'],
                ),
            ]],
            colWidths=[width * 0.45, width * 0.55],
        )
        top_header_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('LEFTPADDING', (0, 0), (-1, -1), 0),
            ('RIGHTPADDING', (0, 0), (-1, -1), 0),
            ('TOPPADDING', (0, 0), (-1, -1), 0),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ]))
        story.append(top_header_table)
        story.append(HRFlowable(width=width, thickness=2, color=colors.black, spaceBefore=2 * mm, spaceAfter=4 * mm))

        printed_orders = 0
        for oid, o_data in orders_map.items():
            category_list = []
            for c_key, c_val in sorted(
                o_data['categories_map'].items(),
                key=lambda item: self._get_category_sort_key(item[1]['categ_name'])
            ):
                sorted_prods = sorted(c_val['products'], key=self._get_sort_key)
                if sorted_prods:
                    category_list.append({
                        'categ_name': c_val['categ_name'],
                        'products': sorted_prods,
                    })
            if not category_list:
                continue

            if printed_orders > 0:
                story.append(PageBreak())
            printed_orders += 1

            # Customer Header
            cust_left_text = f"<b>{xml_escape(o_data['customer_code'])}&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;&nbsp;{xml_escape(o_data['customer_name'])}</b>"
            cust_right_parts = []
            if o_data['address_line1']:
                cust_right_parts.append(xml_escape(o_data['address_line1']))
            if o_data['address_line2']:
                cust_right_parts.append(xml_escape(o_data['address_line2']))
            cust_right_text = f"<b>{'<br/>'.join(cust_right_parts)}</b>"

            cust_table = Table(
                [[
                    Paragraph(cust_left_text, styles['cust_name']),
                    Paragraph(cust_right_text, styles['cust_addr']),
                ]],
                colWidths=[width * 0.45, width * 0.55],
            )
            cust_table.setStyle(TableStyle([
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('LEFTPADDING', (0, 0), (-1, -1), 0),
                ('RIGHTPADDING', (0, 0), (-1, -1), 0),
                ('TOPPADDING', (0, 0), (-1, -1), 0),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
            ]))
            story.append(cust_table)
            story.append(HRFlowable(width=width, thickness=2, color=colors.black, spaceBefore=2 * mm, spaceAfter=3 * mm))

            # Categories and items
            for cat in category_list:
                story.append(Spacer(1, 2 * mm))
                story.append(Paragraph(xml_escape(cat['categ_name']), styles['category']))
                story.append(Spacer(1, 1 * mm))

                rows = []
                for p in cat['products']:
                    rows.append([
                        Paragraph(str(p['qty']), styles['cell_qty']),
                        Paragraph("X", styles['cell_x']),
                        Paragraph(xml_escape(p['product_name']), styles['cell_name']),
                        Paragraph(str(p['weight_display']), styles['cell_weight']),
                    ])

                prod_table = Table(
                    rows,
                    colWidths=[28, 22, width - 28 - 22 - 70, 70],
                )
                prod_table.setStyle(TableStyle([
                    ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                    ('LEFTPADDING', (0, 0), (-1, -1), 0),
                    ('RIGHTPADDING', (0, 0), (-1, -1), 0),
                    ('TOPPADDING', (0, 0), (-1, -1), 2),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
                    ('ALIGN', (0, 0), (0, -1), 'LEFT'),
                    ('ALIGN', (1, 0), (1, -1), 'CENTER'),
                    ('ALIGN', (2, 0), (2, -1), 'LEFT'),
                    ('ALIGN', (3, 0), (3, -1), 'RIGHT'),
                ]))
                story.append(prod_table)

                # Category divider: a line after EVERY category, not just once
                # at the end of the order (client wants each category's block
                # visually closed off before the next one starts).
                story.append(HRFlowable(width=width, thickness=1, color=colors.black, spaceBefore=1.5 * mm, spaceAfter=2 * mm))

            # Full width line after products
            story.append(HRFlowable(width=width, thickness=2, color=colors.black, spaceBefore=1 * mm, spaceAfter=3 * mm))

            # Bottom Summary
            # NOTE: the "Large Polly (s) / Small Polly / Dry Ice" checkboxes
            # were removed per client request (this is why the legacy QWeb
            # template already has that block commented out - editing the
            # XML alone never took effect because the QWeb template is not
            # what actually renders this report; this ReportLab method is).
            tot_weight_str = str(int(round(o_data['total_order_weight_g'])))
            weight_box = Table(
                [[Paragraph(tot_weight_str, styles['total_val'])]],
                colWidths=[24 * mm],
                rowHeights=[7 * mm],
            )
            weight_box.setStyle(TableStyle([
                ('BOX', (0, 0), (-1, -1), 2, colors.black),
                ('BACKGROUND', (0, 0), (-1, -1), colors.white),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('ALIGN', (0, 0), (-1, -1), 'RIGHT'),
                ('RIGHTPADDING', (0, 0), (-1, -1), 4),
                ('LEFTPADDING', (0, 0), (-1, -1), 4),
                ('TOPPADDING', (0, 0), (-1, -1), 0),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
            ]))

            # Middle empty column is just a gap between the label and the box.
            total_table = Table(
                [[
                    Paragraph("Total Weight - Not Inc Fres", styles['total_label']),
                    '',
                    weight_box,
                ]],
                colWidths=[55 * mm, 5 * mm, 26 * mm],
            )
            total_table.setStyle(TableStyle([
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('LEFTPADDING', (0, 0), (-1, -1), 0),
                ('RIGHTPADDING', (0, 0), (-1, -1), 0),
                ('TOPPADDING', (0, 0), (-1, -1), 0),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
            ]))
            # No polly-box column anymore - just the weight total, flush
            # right (matches the QWeb template's `float: right` block now
            # that the left-hand polly column is gone).
            total_table.hAlign = 'RIGHT'
            story.append(total_table)

        if not printed_orders:
            return None

        return self._build_pdf(story, delivery_channel='courier')

    def _generate_van_pdf(self, wizard):
        """Generates pixel-perfect Factory Only Packing List (Regal Van) PDF matching reference design."""
        batch_domain = [
            ('delivery_date', '>=', wizard.delivery_date_from),
            ('delivery_date', '<=', wizard.delivery_date_to),
        ]
        if wizard.depot_ids:
            batch_domain.append(('depot_id', 'in', wizard.depot_ids.ids))

        batches = self.env['round.management.batch'].search(
            batch_domain, order='delivery_date asc, code asc, id asc'
        )
        if not batches:
            return None

        batches_map = {}
        for batch in batches:
            orders = batch.order_ids.filtered(
                lambda so: so.state in ('sale', 'done')
                and getattr(so, 'delivery_channel', False) in ('regal_van', False)
                and bool(getattr(so, 'is_late_order', False)) == bool(wizard.include_late_orders)
            )
            if not orders:
                continue

            b_map = batches_map[batch.id] = {'batch': batch, 'categories_map': {}}
            for order in orders:
                lines = order.order_line.filtered(
                    lambda l: not l.display_type and l.product_id and l.product_uom_qty > 0
                )
                for line in lines:
                    product = line.product_id
                    categ_name = (product.categ_id.name or _('Other')).strip().upper()
                    categ_key = product.categ_id.id or 0
                    if categ_key not in b_map['categories_map']:
                        b_map['categories_map'][categ_key] = {'categ_name': categ_name, 'products': {}}

                    c_prods = b_map['categories_map'][categ_key]['products']
                    pid = product.id
                    if pid not in c_prods:
                        sort_num = self._extract_sort_number(product, line)
                        c_prods[pid] = {
                            'product_id': pid,
                            'product_name': product.name,
                            'box_qty': 0.0,
                            'sort_num': sort_num,
                            'sort_str': str(sort_num) if sort_num else '',
                        }
                    effective_qty = line.box_qty or line.product_uom_qty or 0.0
                    c_prods[pid]['box_qty'] += effective_qty

        if not batches_map:
            return None

        now_utc = fields.Datetime.now()
        now_local = fields.Datetime.context_timestamp(self, now_utc)
        printed_at_str = now_local.strftime('%d/%m/%Y %H:%M:%S')

        styles = {
            'category': ParagraphStyle('PLVanCategory', fontName='Helvetica-Bold', fontSize=12, leading=15, textColor=colors.black),
            'col_header_qty': ParagraphStyle('PLVanColQty', fontName='Helvetica-BoldOblique', fontSize=10.5, leading=13, alignment=1, textColor=colors.black),
            'col_header_prod': ParagraphStyle('PLVanColProd', fontName='Helvetica-BoldOblique', fontSize=10.5, leading=13, alignment=0, textColor=colors.black),
            'col_header_sort': ParagraphStyle('PLVanColSort', fontName='Helvetica', fontSize=9.75, leading=12, alignment=2, textColor=colors.black),
            'cell_qty': ParagraphStyle('PLVanCellQty', fontName='Helvetica-Bold', fontSize=11.25, leading=15, alignment=1, textColor=colors.black),
            'cell_prod': ParagraphStyle('PLVanCellProd', fontName='Helvetica', fontSize=11.25, leading=15, alignment=0, textColor=colors.black),
            'cell_sort': ParagraphStyle('PLVanCellSort', fontName='Helvetica', fontSize=11.25, leading=15, alignment=2, textColor=colors.black),
            'boxes_label': ParagraphStyle('PLVanBoxes', fontName='Helvetica-Bold', fontSize=11, leading=14, alignment=0, textColor=colors.black),
            'checked_by': ParagraphStyle('PLVanCheckedBy', fontName='Helvetica', fontSize=10.5, leading=13, alignment=2, textColor=colors.black),
        }
        width = self.PRINTABLE_WIDTH
        story = []
        printed_batches = 0

        for bid, b_data in batches_map.items():
            category_list = []
            batch_total_boxes = 0
            for c_key, c_val in sorted(
                b_data['categories_map'].items(),
                key=lambda item: self._get_category_sort_key(item[1]['categ_name'])
            ):
                sorted_prods = sorted(c_val['products'].values(), key=self._get_sort_key)
                for p in sorted_prods:
                    p['qty_display'] = int(round(p['box_qty'])) if float(p['box_qty']).is_integer() else p['box_qty']
                cat_total = int(round(sum(p['box_qty'] for p in sorted_prods)))
                batch_total_boxes += cat_total
                if sorted_prods:
                    category_list.append({
                        'categ_name': c_val['categ_name'],
                        'products': sorted_prods,
                        'total_boxes': cat_total,
                    })
            if not category_list:
                continue

            batch = b_data['batch']
            depot_name = batch.depot_id.name or 'Grimsby'
            delivery_date_str = batch.delivery_date.strftime('%d/%m/%Y') if batch.delivery_date else ''
            batch_code = batch.code or ''
            batch_name = (batch.round_id.name if batch.round_id else False) or batch.reference or ''

            batch_header_data = {
                'batch_code': batch_code,
                'batch_name': batch_name,
                'delivery_date': delivery_date_str,
                'depot_name': depot_name,
            }

            batch_pages = self._paginate_batch_categories(category_list)

            for page_idx, page in enumerate(batch_pages):
                if printed_batches > 0 or page_idx > 0:
                    story.append(PageBreak())
                if page_idx == 0:
                    story.append(_PackingListHeaderMarker(batch_header_data))

                for cat in page['categories']:
                    cat_name = cat['categ_name']
                    story.append(Paragraph(xml_escape(cat_name), styles['category']))
                    story.append(Spacer(1, 1 * mm))

                    # Column Header Table (widths mirror the original QWeb
                    # template's fixed 75px / 65px Quantity & Sort columns)
                    col_widths = [20 * mm, width - 37 * mm, 17 * mm]
                    header_row = Table(
                        [[
                            Paragraph("Quantity", styles['col_header_qty']),
                            Paragraph("Product / Box Contents", styles['col_header_prod']),
                            Paragraph("Sort", styles['col_header_sort']),
                        ]],
                        colWidths=col_widths,
                    )
                    header_row.setStyle(TableStyle([
                        ('VALIGN', (0, 0), (-1, -1), 'BOTTOM'),
                        ('LEFTPADDING', (0, 0), (0, -1), 0),
                        ('LEFTPADDING', (1, 0), (1, -1), 7.5),
                        ('LEFTPADDING', (2, 0), (2, -1), 0),
                        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
                        ('TOPPADDING', (0, 0), (-1, -1), 1),
                        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
                        ('LINEBELOW', (0, 0), (-1, -1), 1.5, colors.black),
                    ]))
                    story.append(header_row)

                    # Product rows
                    rows = []
                    for p in cat['products']:
                        rows.append([
                            Paragraph(str(p['qty_display']), styles['cell_qty']),
                            Paragraph(xml_escape(p['product_name'] or ''), styles['cell_prod']),
                            Paragraph(xml_escape(p['sort_str'] or ''), styles['cell_sort']),
                        ])

                    table = Table(rows, colWidths=col_widths)
                    table.setStyle(TableStyle([
                        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                        ('LEFTPADDING', (0, 0), (0, -1), 0),
                        ('LEFTPADDING', (1, 0), (1, -1), 7.5),
                        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
                        ('TOPPADDING', (0, 0), (-1, -1), 3),
                        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
                        ('LINEBELOW', (0, 0), (-1, -1), 0.75, colors.black),
                    ]))
                    story.append(table)

                    # Show "XX Boxes" ONLY when category is complete AND ('FRESH' in cat_name or 'SMOKED' in cat_name)
                    if cat.get('is_complete') and ('FRESH' in cat_name or 'SMOKED' in cat_name):
                        story.append(Spacer(1, 1.5 * mm))
                        story.append(Paragraph(f"{cat['total_boxes']} Boxes", styles['boxes_label']))
                        story.append(Spacer(1, 3 * mm))
                    else:
                        story.append(Spacer(1, 4 * mm))

                if page.get('is_last_page'):
                    story.append(Spacer(1, 6 * mm))
                    story.append(Paragraph("Checked By ________________", styles['checked_by']))

            printed_batches += 1

        if not printed_batches:
            return None

        return self._build_pdf(story, printed_at_text=printed_at_str, delivery_channel='regal_van')

    def _build_pdf(self, story, printed_at_text='', delivery_channel='regal_van'):
        buffer = io.BytesIO()
        top_margin = 28 * mm if delivery_channel == 'regal_van' else 12 * mm
        bottom_margin = 14 * mm if delivery_channel == 'regal_van' else 12 * mm
        doc = SimpleDocTemplate(
            buffer, pagesize=A4,
            leftMargin=12 * mm, rightMargin=12 * mm,
            topMargin=top_margin, bottomMargin=bottom_margin,
        )

        def _make_canvas(*args, **kwargs):
            c = _PackingListCanvas(*args, **kwargs)
            c.printed_at_text = printed_at_text
            c.delivery_channel = delivery_channel
            return c

        doc.build(story, canvasmaker=_make_canvas)
        pdf_value = buffer.getvalue()
        buffer.close()
        return pdf_value
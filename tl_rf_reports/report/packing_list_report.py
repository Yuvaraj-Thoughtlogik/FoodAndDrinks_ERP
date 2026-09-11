# -*- coding: utf-8 -*-

import datetime

from odoo import api, fields, models, _


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

                current_page_categories.append({
                    'categ_name': cat_name,
                    'products': chunk_prods,
                    'is_complete': is_cat_complete,
                    'total_boxes': (
                        total_boxes
                        if is_cat_complete
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
                        COALESCE(pc.name->>%(lang)s, pc.name->>'en_GB', pc.name->>'en_US', pc.name::text) AS categ_name
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
                    COALESCE(pc.name->>%(lang)s, pc.name->>'en_GB', pc.name->>'en_US', pc.name::text) AS categ_name
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
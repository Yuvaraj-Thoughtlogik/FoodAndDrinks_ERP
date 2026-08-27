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
        3. Equal sort numbers (or empty) are ordered alphabetically by product name (A-Z).
        """
        sort_num = product_item.get('sort_num')
        product_name = (product_item.get('product_name') or '').strip().lower()
        if not sort_num or sort_num <= 0:
            return (0, 0, product_name)
        return (1, sort_num, product_name)

    @api.model
    def _extract_sort_number(self, product, line=None):
        """Extracts the integer sort sequence from product master or sale order line."""
        sort_val = 0
        if line and hasattr(line, 'sort_seq') and line.sort_seq:
            sort_val = line.sort_seq
        elif product:
            if hasattr(product, 'sort_seq') and product.sort_seq:
                sort_val = product.sort_seq
            elif hasattr(product, 'product_tmpl_id') and hasattr(product.product_tmpl_id, 'sort_seq') and product.product_tmpl_id.sort_seq:
                sort_val = product.product_tmpl_id.sort_seq

        try:
            sort_int = int(sort_val)
            return sort_int if sort_int > 0 else None
        except (ValueError, TypeError):
            return None

    def _format_customer_name(self, partner):
        if not partner:
            return ""
        name_parts = []
        partner_title = getattr(partner, 'title', False)
        if partner_title and getattr(partner_title, 'name', False):
            title_name = partner_title.name.strip()
            if partner.name and not partner.name.strip().startswith(title_name):
                name_parts.append(title_name)
        if partner.name:
            name_parts.append(partner.name.strip())
        return " ".join(name_parts).strip() or partner.name or ""

    def _format_address_lines(self, partner):
        if not partner:
            return {'line1': '', 'line2': ''}

        line1_parts = [
            getattr(partner, 'street', '') or '',
            getattr(partner, 'street2', '') or '',
            getattr(partner, 'city', '') or '',
        ]
        line1 = " ".join([p.strip() for p in line1_parts if p and p.strip()])

        state_name = partner.state_id.name if getattr(partner, 'state_id', False) and partner.state_id else ''
        line2_parts = [
            state_name,
            getattr(partner, 'zip', '') or '',
        ]
        line2 = " ".join([p.strip() for p in line2_parts if p and p.strip()])

        return {
            'line1': line1,
            'line2': line2,
        }

    def _paginate_batch_categories(self, category_list):
        """Splits a batch's categories and products into distinct pages so that:
        1. Every page has the batch header.
        2. Every page has the category header and column headers for any category on that page.
        3. If a category spans multiple pages, the category header is repeated on the next page.
        4. Box totals are shown when a category finishes.
        5. The last page of the batch has is_last_page: True.

        NOTE: MAX_PAGE_WEIGHT is a proxy for how much vertical space a page has,
        NOT a real mm/px measurement. It was previously set far too low (14),
        which caused pages to break after only ~9 product rows even though an
        A4 page (with these font sizes/margins) fits roughly 35-45 rows.
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

                if current_page_categories and (current_weight + cat_header_cost + 1 > MAX_PAGE_WEIGHT):
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

                is_cat_complete = (prod_idx >= total_prods)

                current_page_categories.append({
                    'categ_name': cat_name,
                    'products': chunk_prods,
                    'is_complete': is_cat_complete,
                    'total_boxes': total_boxes if is_cat_complete else False,
                })

                current_weight += cat_header_cost + len(chunk_prods) + (1.5 if is_cat_complete else 0)

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
        """Splits a courier customer's categories into distinct pages so headers repeat seamlessly.

        See note in _paginate_batch_categories re: MAX_PAGE_WEIGHT being a proxy,
        not a real measurement. Previously 12 (far too small); raised to 34.
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

                if current_page_categories and (current_weight + cat_header_cost + 1 > MAX_PAGE_WEIGHT):
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

                current_page_categories.append({
                    'categ_name': cat_name,
                    'products': chunk_prods,
                })
                current_weight += cat_header_cost + len(chunk_prods)

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
        """Stamps page_number/total_pages onto every page dict across ALL groups
        (batches or customer orders), so the footer shows one running sequence
        for the whole report instead of restarting per batch/order.
        """
        flat_pages = [pg for g in groups for pg in g['pages']]
        total_pages = len(flat_pages)
        for idx, pg in enumerate(flat_pages, start=1):
            pg['page_number'] = idx
            pg['total_pages'] = total_pages
        return groups

    @api.model
    def _get_report_values(self, docids, data=None):
        docs = self.env['packing.list.wizard'].browse(docids)

        now_utc = fields.Datetime.now()
        now_local = fields.Datetime.context_timestamp(self, now_utc)
        printed_at_str = now_local.strftime('%d/%m/%Y %H:%M:%S')

        wizard = docs[0] if docs else False
        delivery_channel = getattr(wizard, 'delivery_channel', 'regal_van') if wizard else 'regal_van'

        # ----------------------------------------------------
        # COURIER DELIVERY FLOW (Customer-wise Packing List)
        # ----------------------------------------------------
        if delivery_channel == 'courier':
            all_customer_orders = []
            packing_date_from_str = ''
            packing_date_to_str = ''
            delivery_date_from_str = ''
            delivery_date_to_str = ''

            for wiz in docs:
                p_from = getattr(wiz, 'packing_date_from', False) or (wiz.delivery_date_from - datetime.timedelta(days=1)) if wiz.delivery_date_from else False
                p_to = getattr(wiz, 'packing_date_to', False) or (wiz.delivery_date_to - datetime.timedelta(days=1)) if wiz.delivery_date_to else False

                packing_date_from_str = p_from.strftime('%d/%m/%Y') if p_from else ''
                packing_date_to_str = p_to.strftime('%d/%m/%Y') if p_to else ''
                delivery_date_from_str = wiz.delivery_date_from.strftime('%d/%m/%Y') if wiz.delivery_date_from else ''
                delivery_date_to_str = wiz.delivery_date_to.strftime('%d/%m/%Y') if wiz.delivery_date_to else ''

                order_domain = [
                    ('delivery_channel', '=', 'courier'),
                    ('state', 'in', ['sale', 'done']),
                    ('delivery_date', '>=', wiz.delivery_date_from),
                    ('delivery_date', '<=', wiz.delivery_date_to),
                ]
                if not wiz.include_late_orders:
                    order_domain.append(('is_late_order', '=', False))
                else:
                    order_domain.append(('is_late_order', '=', True))

                applicable_orders = self.env['sale.order'].search(
                    order_domain,
                    order='delivery_date asc, name asc'
                )

                for order in applicable_orders:
                    main_partner = order.partner_id
                    ship_partner = order.partner_shipping_id or main_partner

                    customer_code = getattr(main_partner, 'customer_code', False) or getattr(main_partner, 'ref', False) or order.name or ''
                    customer_name = self._format_customer_name(main_partner)
                    address_dict = self._format_address_lines(ship_partner)

                    categories_map = {}
                    total_order_weight_g = 0.0

                    for line in order.order_line.filtered(lambda l: not l.display_type and l.product_id and l.product_uom_qty > 0):
                        product = line.product_id
                        categ = product.categ_id
                        categ_name = (categ.name or _('Other')).strip().upper() if categ else 'OTHER'
                        categ_key = (categ.sequence if categ and hasattr(categ, 'sequence') else 0, categ_name)

                        if categ_key not in categories_map:
                            categories_map[categ_key] = {
                                'categ_name': categ_name,
                                'products': [],
                            }

                        unit_weight_kg = 0.0
                        if hasattr(line, '_get_product_unit_weight_in_kg'):
                            unit_weight_kg = line._get_product_unit_weight_in_kg()
                        elif product.weight:
                            unit_weight_kg = product.weight

                        line_weight_kg = unit_weight_kg * line.product_uom_qty
                        line_weight_g = round(line_weight_kg * 1000)
                        total_order_weight_g += line_weight_g

                        qty_val = line.product_uom_qty
                        qty_display = int(round(qty_val)) if float(qty_val).is_integer() else qty_val
                        sort_num = self._extract_sort_number(product, line)

                        categories_map[categ_key]['products'].append({
                            'qty': qty_display,
                            'product_name': product.name or line.name,
                            'weight_g': line_weight_g,
                            'weight_display': int(round(line_weight_g)),
                            'sort_num': sort_num,
                        })

                    category_list = []
                    for c_key, c_val in sorted(categories_map.items(), key=lambda item: item[0]):
                        sorted_prods = sorted(c_val['products'], key=self._get_sort_key)
                        if sorted_prods:
                            category_list.append({
                                'categ_name': c_val['categ_name'],
                                'products': sorted_prods,
                            })

                    # Paginate categories for this customer order
                    order_pages = self._paginate_courier_categories(category_list)

                    all_customer_orders.append({
                        'order_id': order.id,
                        'order_name': order.name,
                        'delivery_date': order.delivery_date.strftime('%d/%m/%Y') if order.delivery_date else '',
                        'customer_code': customer_code,
                        'customer_name': customer_name,
                        'address_line1': address_dict['line1'],
                        'address_line2': address_dict['line2'],
                        'pages': order_pages,
                        'total_weight_g': int(round(total_order_weight_g)),
                    })

            # Number pages continuously across the whole courier report
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
        # REGAL VAN DELIVERY FLOW (Batch-based Factory Only Packing List)
        # ----------------------------------------------------
        all_batch_groups = []
        for wizard in docs:
            batch_domain = [
                ('delivery_date', '>=', wizard.delivery_date_from),
                ('delivery_date', '<=', wizard.delivery_date_to),
            ]
            if wizard.depot_ids:
                batch_domain.append(('depot_id', 'in', wizard.depot_ids.ids))

            batches = self.env['round.management.batch'].search(
                batch_domain,
                order='delivery_date asc, code asc'
            )

            for batch in batches:
                orders = batch.order_ids.filtered(
                    lambda so: so.state in ('sale', 'done') and getattr(so, 'delivery_channel', False) in ('regal_van', False)
                )
                if not wizard.include_late_orders:
                    orders = orders.filtered(lambda so: not getattr(so, 'is_late_order', False))
                else:
                    orders = orders.filtered(lambda so: getattr(so, 'is_late_order', False))

                if not orders:
                    continue

                categories_map = {}
                for order in orders:
                    for line in order.order_line.filtered(lambda l: not l.display_type and l.product_id):
                        product = line.product_id
                        categ = product.categ_id
                        categ_name = (categ.name or _('Other')).strip().upper() if categ else 'OTHER'
                        categ_key = categ.id if categ else 0

                        if categ_key not in categories_map:
                            categories_map[categ_key] = {
                                'categ_name': categ_name,
                                'products': {},
                            }

                        prod_key = product.id
                        if prod_key not in categories_map[categ_key]['products']:
                            sort_num = self._extract_sort_number(product, line)
                            categories_map[categ_key]['products'][prod_key] = {
                                'product_id': prod_key,
                                'product_name': product.name,
                                'box_qty': 0.0,
                                'sort_num': sort_num,
                                'sort_str': str(sort_num) if sort_num else '',
                            }

                        qty = line.box_qty if (line.box_qty and line.box_qty > 0) else line.product_uom_qty
                        categories_map[categ_key]['products'][prod_key]['box_qty'] += qty

                category_list = []
                batch_total_boxes = 0
                for c_key, c_val in sorted(categories_map.items(), key=lambda item: item[1]['categ_name']):
                    sorted_prods = sorted(
                        c_val['products'].values(),
                        key=self._get_sort_key
                    )
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

                if category_list:
                    depot_name = batch.depot_id.name if batch.depot_id else 'Grimsby'
                    delivery_date_str = batch.delivery_date.strftime('%d/%m/%Y') if batch.delivery_date else ''
                    batch_code = batch.code or ''
                    batch_name = batch.round_id.name if (batch.round_id and batch.round_id.name) else (batch.reference or '')

                    batch_pages = self._paginate_batch_categories(category_list)

                    all_batch_groups.append({
                        'delivery_date': delivery_date_str,
                        'depot_name': depot_name,
                        'batch_code': batch_code,
                        'batch_name': batch_name,
                        'pages': batch_pages,
                        'total_boxes': batch_total_boxes,
                    })

        # Number pages continuously across the whole regal van report
        # (spans all batches, not reset per batch)
        all_batch_groups = self._number_pages_continuously(all_batch_groups)

        return {
            'doc_ids': docids,
            'doc_model': 'packing.list.wizard',
            'docs': docs,
            'printed_at': printed_at_str,
            'delivery_channel': 'regal_van',
            'batch_groups': all_batch_groups,
        }
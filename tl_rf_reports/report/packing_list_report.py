# -*- coding: utf-8 -*-
from odoo import api, fields, models, _


class ReportPackingList(models.AbstractModel):
    _name = 'report.tl_rf_reports.report_packing_list'
    _description = 'Factory Only Packing List Report Generator'

    @api.model
    def _get_sort_key(self, product_item):
        """Implements the 3-level sorting logic:
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

    @api.model
    def _get_report_values(self, docids, data=None):
        docs = self.env['packing.list.wizard'].browse(docids)

        now_utc = fields.Datetime.now()
        now_local = fields.Datetime.context_timestamp(self, now_utc)
        printed_at_str = now_local.strftime('%d/%m/%Y %H:%M:%S')

        all_batch_groups = []

        for wizard in docs:
            # ----------------------------------------------------
            # COURIER DELIVERY FLOW
            # ----------------------------------------------------
            if wizard.delivery_channel == 'courier':
                order_domain = [
                    ('delivery_channel', '=', 'courier'),
                    ('state', 'in', ['sale', 'done']),
                    ('delivery_date', '>=', wizard.delivery_date_from),
                    ('delivery_date', '<=', wizard.delivery_date_to),
                ]
                if not wizard.include_late_orders:
                    order_domain.append(('is_late_order', '=', False))
                else:
                    order_domain.append(('is_late_order', '=', True))

                applicable_orders = self.env['sale.order'].search(
                    order_domain,
                    order='delivery_date asc, name asc'
                )

                # Group courier orders by delivery date
                dates_dict = {}
                for order in applicable_orders:
                    d_date = order.delivery_date or wizard.delivery_date_from
                    if d_date not in dates_dict:
                        dates_dict[d_date] = []
                    dates_dict[d_date].append(order)

                for d_date, date_orders in sorted(dates_dict.items(), key=lambda x: x[0]):
                    categories_map = {}
                    for order in date_orders:
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
                        all_batch_groups.append({
                            'delivery_date': d_date.strftime('%d/%m/%Y') if d_date else '',
                            'depot_name': '',
                            'batch_code': 'COURIER',
                            'batch_name': 'COURIER DELIVERY',
                            'categories': category_list,
                            'total_boxes': batch_total_boxes,
                        })
                continue

            # ----------------------------------------------------
            # REGAL VAN DELIVERY FLOW (BATCH-BASED)
            # ----------------------------------------------------
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
                # Find matching orders in batch
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

                    all_batch_groups.append({
                        'delivery_date': delivery_date_str,
                        'depot_name': depot_name,
                        'batch_code': batch_code,
                        'batch_name': batch_name,
                        'categories': category_list,
                        'total_boxes': batch_total_boxes,
                    })

        return {
            'doc_ids': docids,
            'doc_model': 'packing.list.wizard',
            'docs': docs,
            'printed_at': printed_at_str,
            'batch_groups': all_batch_groups,
        }

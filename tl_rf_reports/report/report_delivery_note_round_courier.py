# -*- coding: utf-8 -*-
from collections import defaultdict
from odoo import api, models
from odoo.tools.image import image_data_uri
from .report_delivery_note_common import DeliveryNoteReportMixin


class ReportDeliveryNoteRoundCourier(DeliveryNoteReportMixin, models.AbstractModel):
    _name = 'report.tl_rf_reports.report_delivery_note_round_courier'
    _description = 'Delivery Note Round Report - Courier'

    def _get_order_category_lines(self, order, delivery_product_ids=None, lines=None):
        """Group an order's lines into categorized buckets (e.g. FROZEN, FRESH, etc.)."""
        if lines is None:
            lines = order.order_line.filtered(lambda l: not l.display_type and l.product_id)
        if delivery_product_ids is not None:
            lines = [l for l in lines if l.product_id.id in delivery_product_ids]

        cat_dict = {}
        for line in lines:
            product = line.product_id
            categ_name = product.categ_id.name.strip() if product.categ_id and product.categ_id.name else ''

            c_upper = categ_name.upper()
            if 'FROZEN' in c_upper or 'FREEZE' in c_upper or getattr(product, 'use_frozen', False):
                cat_key = 'FROZEN'
                priority = 1
            elif 'FRESH' in c_upper or 'CHILLED' in c_upper or getattr(product, 'use_fresh', False):
                cat_key = 'FRESH'
                priority = 2
            elif c_upper:
                cat_key = c_upper
                priority = 3
            else:
                cat_key = 'FRESH'
                priority = 2

            if cat_key not in cat_dict:
                cat_dict[cat_key] = {
                    'name': cat_key,
                    'priority': priority,
                    'lines': []
                }

            qty = self._format_qty(getattr(line, 'product_uom_qty', 0))
            prod_name = product.name or line.name or ''
            extra_note = self._extract_hash_note((getattr(line, 'name', '') or '').strip())

            cat_dict[cat_key]['lines'].append({
                'qty': qty,
                'product_name': prod_name,
                'extra_note': extra_note,
            })

        return sorted(cat_dict.values(), key=lambda c: (c['priority'], c['name']))

    @api.model
    def _get_report_values(self, docids, data=None):
        docs = self.env['delivery.note.round.wizard'].browse(docids)
        courier_orders_data = []

        company = self.env.company
        company_logo_uri = image_data_uri(company.logo) if company.logo else False

        for wizard in docs:
            order_domain = [
                ('delivery_channel', '=', 'courier'),
                ('state', 'in', ['sale', 'done']),
                ('delivery_date', '>=', wizard.delivery_date_from),
                ('delivery_date', '<=', wizard.delivery_date_to),
                ('picking_ids', '!=', False),
            ]
            applicable_orders = self.env['sale.order'].search(
                order_domain,
                order='delivery_date asc, name asc'
            )

            if not applicable_orders:
                continue

            # Batch pre-fetch pickings, moves, and lines to avoid N+1 SQL queries
            all_pickings = self.env['stock.picking'].search([
                ('sale_id', 'in', applicable_orders.ids),
                ('state', '!=', 'cancel'),
            ])
            pickings_by_order = defaultdict(lambda: self.env['stock.picking'])
            for p in all_pickings:
                p_type = getattr(p, 'picking_type_id', False)
                code = getattr(p_type, 'code', False) if p_type else False
                if code in ('outgoing', False, None):
                    pickings_by_order[p.sale_id.id] |= p

            all_moves = self.env['stock.move'].search([
                ('picking_id', 'in', all_pickings.ids),
                ('state', '!=', 'cancel'),
            ])
            picking_to_sale = {p.id: p.sale_id.id for p in all_pickings}
            delivery_products_by_order = defaultdict(set)
            for m in all_moves:
                if m.product_id and m.picking_id.id in picking_to_sale:
                    delivery_products_by_order[picking_to_sale[m.picking_id.id]].add(m.product_id.id)

            all_lines = self.env['sale.order.line'].search([
                ('order_id', 'in', applicable_orders.ids),
                ('display_type', '=', False),
                ('product_id', '!=', False),
            ])
            lines_by_order = defaultdict(list)
            for l in all_lines:
                lines_by_order[l.order_id.id].append(l)

            for order in applicable_orders:
                pickings = pickings_by_order.get(order.id, self.env['stock.picking'])
                delivery_product_ids = delivery_products_by_order.get(order.id) if pickings else None

                order_lines = lines_by_order.get(order.id, [])
                categories = self._get_order_category_lines(order, delivery_product_ids, lines=order_lines)
                if not categories:
                    continue

                ship_partner = order.partner_shipping_id or order.partner_id
                main_partner = order.partner_id

                cust_name = self._format_customer_name(main_partner, include_code=False)
                cust_code = getattr(main_partner, 'customer_code', False) or getattr(main_partner, 'ref', False) or str(main_partner.id)
                addr_line1, addr_line2 = self._format_address_lines(ship_partner)

                d_date = order.delivery_date or wizard.delivery_date_from
                delivery_date_str = d_date.strftime('%d/%m/%Y') if d_date else ''

                courier_orders_data.append({
                    'order': order,
                    'order_no': order.client_order_ref or order.name or '',
                    'customer_id': cust_code,
                    'customer_name': cust_name,
                    'address_line1': addr_line1,
                    'address_line2': addr_line2,
                    'delivery_date': delivery_date_str,
                    'categories': categories,
                    'company': order.company_id or company,
                    'company_logo_uri': company_logo_uri,
                })

        return {
            'doc_ids': docids,
            'doc_model': 'delivery.note.round.wizard',
            'docs': docs,
            'courier_orders': courier_orders_data,
            'company': self.env.company,
            'company_logo_uri': company_logo_uri,
        }

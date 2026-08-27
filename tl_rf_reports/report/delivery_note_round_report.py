# -*- coding: utf-8 -*-
import re
from odoo import api, fields, models, _
from odoo.tools import html2plaintext


class ReportDeliveryNoteRound(models.AbstractModel):
    _name = 'report.tl_rf_reports.report_delivery_note_round'
    _description = 'Delivery Note Round Report Generator'

    def _clean_text(self, val):
        if not val:
            return ""
        txt = html2plaintext(val) if '<' in val and '>' in val else str(val)
        return txt.strip()

    def _format_address(self, partner):
        if not partner:
            return ""
        state_name = partner.state_id.name if getattr(partner, 'state_id', False) and partner.state_id else ''
        parts = [
            getattr(partner, 'street', '') or '',
            getattr(partner, 'street2', '') or '',
            getattr(partner, 'city', '') or '',
            state_name,
            getattr(partner, 'zip', '') or '',
        ]
        valid_parts = [p.strip() for p in parts if p and p.strip()]
        return " ".join(valid_parts)

    def _format_address_lines(self, partner):
        if not partner:
            return "", ""
        state_name = partner.state_id.name if getattr(partner, 'state_id', False) and partner.state_id else ''
        line1_parts = [
            getattr(partner, 'street', '') or '',
            getattr(partner, 'street2', '') or '',
            getattr(partner, 'city', '') or '',
        ]
        line2_parts = [
            state_name,
            getattr(partner, 'zip', '') or '',
        ]
        line1 = " ".join([p.strip() for p in line1_parts if p and p.strip()])
        line2 = " ".join([p.strip() for p in line2_parts if p and p.strip()])
        return line1, line2

    def _format_customer_name(self, partner, include_code=True):
        if not partner:
            return ""
        name_parts = []
        partner_title = getattr(partner, 'title', False)
        if partner_title and getattr(partner_title, 'name', False):
            t_name = partner_title.name.strip()
            p_name = (partner.name or '').strip()
            if not p_name.lower().startswith(t_name.lower()):
                name_parts.append(t_name)
        if partner.name:
            name_parts.append(partner.name.strip())
        full_name = " ".join(name_parts).strip() or partner.name or ""

        if include_code:
            code = getattr(partner, 'customer_code', False) or getattr(partner, 'ref', False)
            if code:
                return f"{full_name} ({code})"
        return full_name

    def _get_order_category_lines(self, order, delivery_product_ids=None):
        """Group an order's lines into categorized buckets (e.g. FROZEN, FRESH, etc.)."""
        lines = order.order_line.filtered(lambda l: not l.display_type and l.product_id)
        if delivery_product_ids:
            lines = lines.filtered(lambda l: l.product_id.id in delivery_product_ids)

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

            qty_val = getattr(line, 'product_uom_qty', 0)
            qty = int(qty_val) if hasattr(qty_val, 'is_integer') and qty_val.is_integer() else (int(qty_val) if float(qty_val).is_integer() else qty_val)

            prod_name = product.name or line.name or ''
            line_desc = (getattr(line, 'name', '') or '').strip()
            extra_note = ""
            if '#' in line_desc:
                match = re.search(r'(#.+?#)', line_desc)
                if match:
                    extra_note = match.group(1).strip()

            cat_dict[cat_key]['lines'].append({
                'qty': qty,
                'product_name': prod_name,
                'extra_note': extra_note,
            })

        return sorted(cat_dict.values(), key=lambda c: (c['priority'], c['name']))

    # --------------------------------------------------------------
    # DELIVERY (STOCK PICKING) HELPERS
    # --------------------------------------------------------------
    def _get_delivery_pickings(self, order):
        """Return the order's live outgoing delivery pickings (cancelled excluded)."""
        pickings = getattr(order, 'picking_ids', False)
        if not pickings:
            return self.env['stock.picking']

        def _is_delivery(pick):
            if pick.state == 'cancel':
                return False
            p_type = getattr(pick, 'picking_type_id', False)
            code = getattr(p_type, 'code', False) if p_type else False
            # If the picking type code is unavailable, keep the picking rather than lose data.
            return code in ('outgoing', False, None)

        return pickings.filtered(_is_delivery)

    def _get_delivery_product_ids(self, pickings):
        """Product ids actually present on the delivery moves (cancelled moves excluded)."""
        product_ids = set()
        for pick in pickings:
            moves = getattr(pick, 'move_ids', False)
            if moves is False:
                moves = getattr(pick, 'move_ids_without_package', False) or getattr(pick, 'move_lines', False)
            if not moves:
                continue
            for move in moves:
                if move.state == 'cancel':
                    continue
                if move.product_id:
                    product_ids.add(move.product_id.id)
        return product_ids

    def _format_line_item(self, line):
        qty_val = getattr(line, 'product_uom_qty', 0)
        qty = int(qty_val) if hasattr(qty_val, 'is_integer') and qty_val.is_integer() else (int(qty_val) if float(qty_val).is_integer() else qty_val)
        uom_name = (line.product_uom_id.name or '').strip().lower() if getattr(line, 'product_uom_id', False) and line.product_uom_id else ''

        if not uom_name or uom_name in ('units', 'unit', 'unit(s)', 'each', 'pc', 'pcs', 'p'):
            qty_prefix = f"{qty} x"
        else:
            qty_prefix = f"{qty} {line.product_uom_id.name}"

        prod_name = line.product_id.name if getattr(line, 'product_id', False) and line.product_id else (getattr(line, 'name', '') or '')

        # Check if line description contains special notes or hash annotations
        line_desc = (getattr(line, 'name', '') or '').strip()
        extra_note = ""
        if '#' in line_desc:
            match = re.search(r'(#.+?#)', line_desc)
            if match:
                extra_note = " " + match.group(1).strip()

        return f"{qty_prefix} {prod_name}{extra_note}"

    def _build_drop(self, order):
        """Build one drop dict for an order, or None when the order has no delivery
        or none of its lines are part of the delivery."""
        pickings = self._get_delivery_pickings(order)
        if not pickings:
            return None

        delivery_product_ids = self._get_delivery_product_ids(pickings)
        if not delivery_product_ids:
            return None

        delivery_lines = order.order_line.filtered(
            lambda l: not l.display_type and l.product_id and l.product_id.id in delivery_product_ids
        )
        if not delivery_lines:
            return None

        ship_partner = order.partner_shipping_id or order.partner_id
        main_partner = order.partner_id

        cust_str = self._format_customer_name(main_partner)
        addr_str = self._format_address(ship_partner)
        tel_str = getattr(ship_partner, 'phone', False) or getattr(ship_partner, 'mobile', False) or getattr(main_partner, 'mobile', False) or getattr(main_partner, 'phone', False) or ''

        items = [self._format_line_item(line) for line in delivery_lines]

        order_no = order.client_order_ref or order.name or ''
        note_str = self._clean_text(order.note)

        pay_flags = {
            'card_reader': bool(getattr(order, 'pay_card_reader', False)),
            'kb': bool(getattr(order, 'pay_kb', False)),
            'lnp': bool(getattr(order, 'pay_lnp', False)),
            'cash': bool(getattr(order, 'pay_cash', False)),
            'cheque': bool(getattr(order, 'pay_cheque', False)),
            'card': bool(getattr(order, 'pay_card', False)),
        }

        currency_sym = order.currency_id.symbol if order.currency_id else '£'
        price_str = f"{currency_sym}{order.amount_total:,.2f}"

        return {
            'cust': cust_str,
            'addr': addr_str,
            'tel': tel_str,
            'items': items,
            'order_no': order_no,
            'note': note_str,
            'pay': pay_flags,
            'price': price_str,
            'zone': '',  # filled in by the caller (differs per flow)
        }

    @api.model
    def _get_report_values(self, docids, data=None):
        docs = self.env['delivery.note.round.wizard'].browse(docids)

        all_batch_groups = []

        for wizard in docs:
            # ----------------------------------------------------
            # COURIER DELIVERY FLOW
            # ----------------------------------------------------
            if getattr(wizard, 'delivery_channel', 'regal_van') == 'courier':
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

                courier_orders_data = []
                for order in applicable_orders:
                    pickings = self._get_delivery_pickings(order)
                    delivery_product_ids = self._get_delivery_product_ids(pickings) if pickings else None

                    categories = self._get_order_category_lines(order, delivery_product_ids)
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
                        'company': order.company_id or self.env.company,
                    })

                return {
                    'doc_ids': docids,
                    'doc_model': 'delivery.note.round.wizard',
                    'docs': docs,
                    'delivery_channel': 'courier',
                    'courier_orders': courier_orders_data,
                    'batch_groups': [],
                    'company': self.env.company,
                }

            # ----------------------------------------------------
            # REGAL VAN DELIVERY FLOW
            # ----------------------------------------------------
            batch_domain = [
                ('delivery_date', '>=', wizard.delivery_date_from),
                ('delivery_date', '<=', wizard.delivery_date_to),
            ]

            batches = self.env['round.management.batch'].search(
                batch_domain,
                order='delivery_date asc, code asc'
            )

            for batch in batches:
                eligible_orders = batch.order_ids.filtered(
                    lambda so: so.state in ('sale', 'done')
                    and getattr(so, 'delivery_channel', False) in ('regal_van', False)
                    and self._get_delivery_pickings(so)
                )

                if not eligible_orders:
                    continue

                # Sort orders by name or delivery sequence
                sorted_orders = eligible_orders.sorted(key=lambda o: (o.round_code or '', o.name or ''))

                drops = []
                for order in sorted_orders:
                    drop = self._build_drop(order)
                    if not drop:
                        continue

                    # Round / Zone code
                    drop['zone'] = order.round_code or (
                        order.round_id.code if order.round_id else (
                            batch.round_code or (batch.round_id.code if batch.round_id else '')
                        )
                    ) or ''
                    drops.append(drop)

                if drops:
                    batch_name = batch.round_id.name if (batch.round_id and batch.round_id.name) else (batch.reference or '')
                    batch_code = batch.code or ''
                    depot_name = batch.depot_id.name.upper() if batch.depot_id and batch.depot_id.name else 'GRIMSBY'
                    delivery_date_str = batch.delivery_date.strftime('%d/%m/%Y') if batch.delivery_date else ''

                    all_batch_groups.append({
                        'batch_name': batch_name,
                        'batch_code': f"({batch_code})" if batch_code else "",
                        'depot_name': depot_name,
                        'delivery_date': delivery_date_str,
                        'total_deliveries': len(drops),
                        'drops': drops,
                    })

        return {
            'doc_ids': docids,
            'doc_model': 'delivery.note.round.wizard',
            'docs': docs,
            'delivery_channel': 'regal_van',
            'courier_orders': [],
            'batch_groups': all_batch_groups,
            'company': self.env.company,
        }
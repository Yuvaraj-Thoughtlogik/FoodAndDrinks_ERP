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

    def _format_customer_name(self, partner):
        if not partner:
            return ""
        name_parts = []
        partner_title = getattr(partner, 'title', False)
        if partner_title and getattr(partner_title, 'name', False):
            name_parts.append(partner_title.name)
        if partner.name:
            name_parts.append(partner.name)
        full_name = " ".join(name_parts).strip() or partner.name or ""

        code = getattr(partner, 'customer_code', False) or getattr(partner, 'ref', False)
        if code:
            return f"{full_name} ({code})"
        return full_name

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
                ]
                applicable_orders = self.env['sale.order'].search(
                    order_domain,
                    order='delivery_date asc, name asc'
                )

                # Group by delivery date
                dates_dict = {}
                for order in applicable_orders:
                    d_date = order.delivery_date or wizard.delivery_date_from
                    if d_date not in dates_dict:
                        dates_dict[d_date] = []
                    dates_dict[d_date].append(order)

                for d_date, date_orders in sorted(dates_dict.items(), key=lambda x: x[0]):
                    drops = []
                    for order in date_orders:
                        ship_partner = order.partner_shipping_id or order.partner_id
                        main_partner = order.partner_id

                        cust_str = self._format_customer_name(main_partner)
                        addr_str = self._format_address(ship_partner)
                        tel_str = getattr(ship_partner, 'phone', False) or getattr(ship_partner, 'mobile', False) or getattr(main_partner, 'mobile', False) or getattr(main_partner, 'phone', False) or ''

                        items = []
                        for line in order.order_line.filtered(lambda l: not l.display_type and l.product_id):
                            items.append(self._format_line_item(line))

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
                        zone_code = order.round_code or 'COURIER'

                        drops.append({
                            'cust': cust_str,
                            'addr': addr_str,
                            'tel': tel_str,
                            'items': items,
                            'order_no': order_no,
                            'note': note_str,
                            'pay': pay_flags,
                            'price': price_str,
                            'zone': zone_code,
                        })

                    if drops:
                        all_batch_groups.append({
                            'batch_name': 'COURIER DELIVERY',
                            'batch_code': '(COURIER)',
                            'depot_name': 'GRIMSBY',
                            'delivery_date': d_date.strftime('%d/%m/%Y') if d_date else '',
                            'total_deliveries': len(drops),
                            'drops': drops,
                        })
                continue

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
                    lambda so: so.state in ('sale', 'done') and getattr(so, 'delivery_channel', False) in ('regal_van', False)
                )

                if not eligible_orders:
                    continue

                # Sort orders by name or delivery sequence
                sorted_orders = eligible_orders.sorted(key=lambda o: (o.round_code or '', o.name or ''))

                drops = []
                for order in sorted_orders:
                    ship_partner = order.partner_shipping_id or order.partner_id
                    main_partner = order.partner_id

                    cust_str = self._format_customer_name(main_partner)
                    addr_str = self._format_address(ship_partner)
                    tel_str = getattr(ship_partner, 'phone', False) or getattr(ship_partner, 'mobile', False) or getattr(main_partner, 'mobile', False) or getattr(main_partner, 'phone', False) or ''

                    items = []
                    for line in order.order_line.filtered(lambda l: not l.display_type and l.product_id):
                        items.append(self._format_line_item(line))

                    # Order number
                    order_no = order.client_order_ref or order.name or ''

                    # Order delivery note / instructions
                    note_str = self._clean_text(order.note)

                    # Payment mode flags
                    pay_flags = {
                        'card_reader': bool(getattr(order, 'pay_card_reader', False)),
                        'kb': bool(getattr(order, 'pay_kb', False)),
                        'lnp': bool(getattr(order, 'pay_lnp', False)),
                        'cash': bool(getattr(order, 'pay_cash', False)),
                        'cheque': bool(getattr(order, 'pay_cheque', False)),
                        'card': bool(getattr(order, 'pay_card', False)),
                    }

                    # Total amount & currency
                    currency_sym = order.currency_id.symbol if order.currency_id else '£'
                    price_str = f"{currency_sym}{order.amount_total:,.2f}"

                    # Round / Zone code
                    zone_code = order.round_code or (order.round_id.code if order.round_id else (batch.round_code or (batch.round_id.code if batch.round_id else ''))) or ''

                    drops.append({
                        'cust': cust_str,
                        'addr': addr_str,
                        'tel': tel_str,
                        'items': items,
                        'order_no': order_no,
                        'note': note_str,
                        'pay': pay_flags,
                        'price': price_str,
                        'zone': zone_code,
                    })

                if drops:
                    batch_name = batch.round_id.name if (batch.round_id and batch.round_id.name) else (batch.reference or '')
                    batch_code = batch.round_id.code or batch.code or ''
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
            'batch_groups': all_batch_groups,
        }

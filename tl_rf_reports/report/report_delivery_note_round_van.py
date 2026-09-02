# -*- coding: utf-8 -*-
from odoo import api, fields, models
from .report_delivery_note_common import DeliveryNoteReportMixin


class ReportDeliveryNoteRoundVan(DeliveryNoteReportMixin, models.AbstractModel):
    _name = 'report.tl_rf_reports.report_delivery_note_round_van'
    _description = 'Delivery Note Round Report - Regal Van'

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
            'zone': '',
        }

    @api.model
    def _get_report_values(self, docids, data=None):
        docs = self.env['delivery.note.round.wizard'].browse(docids)
        all_batch_groups = []

        for wizard in docs:
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

                sorted_orders = eligible_orders.sorted(key=lambda o: (o.round_code or '', o.name or ''))

                drops = []
                for order in sorted_orders:
                    drop = self._build_drop(order)
                    if not drop:
                        continue

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
            'batch_groups': all_batch_groups,
            'company': self.env.company,
            'printed_at': fields.Datetime.now().strftime('%d/%m/%Y %H:%M:%S'),
        }

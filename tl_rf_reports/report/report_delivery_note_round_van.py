# -*- coding: utf-8 -*-
import base64
import logging
import re

from odoo import api, fields, models
from .report_delivery_note_common import DeliveryNoteReportMixin

_logger = logging.getLogger(__name__)


class ReportDeliveryNoteRoundVan(DeliveryNoteReportMixin, models.AbstractModel):
    _name = 'report.tl_rf_reports.report_delivery_note_round_van'
    _description = 'Delivery Note Round Report - Regal Van'

    # Barcode rendering: the image is generated server-side and embedded as a
    # data URI rather than pointing at /report/barcode/, so wkhtmltopdf never
    # has to make an authenticated HTTP call back into Odoo to fetch it.
    BARCODE_SYMBOLOGY = 'Code128'
    BARCODE_RENDER_WIDTH = 600     # source image px (downscaled by the template)
    BARCODE_RENDER_HEIGHT = 100

    def _barcode_data_uri(self, value):
        """Return a base64 PNG data URI for `value`, or '' when it can't be encoded."""
        if not value:
            return ''
        try:
            png = self.env['ir.actions.report'].barcode(
                self.BARCODE_SYMBOLOGY,
                value,
                width=self.BARCODE_RENDER_WIDTH,
                height=self.BARCODE_RENDER_HEIGHT,
                humanreadable=0,
            )
        except Exception:  # noqa: BLE001 - a bad barcode must not kill the print
            _logger.warning("Delivery note (van): cannot encode barcode for %r", value)
            return ''
        return 'data:image/png;base64,%s' % base64.b64encode(png).decode('ascii')

    def _get_delivery_picking_for_barcode(self, pickings):
        """The single outgoing picking whose barcode goes on the note.

        The warehouse is configured for one-step (direct) delivery, so there is
        normally exactly one. If a backorder ever produces more than one, the
        first still-open picking wins, falling back to the lowest id.
        """
        if not pickings:
            return pickings
        open_pickings = pickings.filtered(lambda p: p.state not in ('done', 'cancel'))
        candidates = open_pickings or pickings
        return candidates.sorted('id')[0]

    def _get_order_sort_key(self, order):
        """Sort key to order drops by partner street2 (Street) then street (Door no)."""
        partner = order.partner_shipping_id or order.partner_id
        street2 = (partner.street2 or '').strip().lower() if partner else ''
        street = (partner.street or '').strip() if partner else ''
        # Natural sort helper for door number so "2" comes before "10"
        door_key = [
            (1, int(c)) if c.isdigit() else (0, c.lower())
            for c in re.split(r'(\d+)', street)
            if c
        ] if street else []
        return (street2, door_key, order.name or '')

    def _build_drop(self, order, pickings=None, delivery_product_ids=None, lines=None):
        """Build one drop dict for an order, or None when the order has no delivery
        or none of its lines are part of the delivery."""
        if pickings is None:
            pickings = self._get_delivery_pickings(order)
        if not pickings:
            return None

        if delivery_product_ids is None:
            delivery_product_ids = self._get_delivery_product_ids(pickings)
        if not delivery_product_ids:
            return None

        if lines is None:
            delivery_lines = order.order_line.filtered(
                lambda l: not l.display_type and l.product_id and l.product_id.id in delivery_product_ids
            )
        else:
            delivery_lines = [
                l for l in lines
                if not l.display_type and l.product_id and l.product_id.id in delivery_product_ids
            ]

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

        # Delivery order barcode (scannable in the warehouse / on the van).
        picking = self._get_delivery_picking_for_barcode(pickings)
        picking_name = (picking.name or '') if picking else ''
        barcode_value = (getattr(picking, 'barcode', False) or picking_name) if picking else ''

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
            'picking_name': picking_name,
            'barcode_src': self._barcode_data_uri(barcode_value),
        }

    # ------------------------------------------------------------------
    # PAGINATION CALIBRATION
    # ------------------------------------------------------------------
    # All values below are expressed in "rows", where 1 row = the height of
    # one printed item line (measured at 12.6pt on the generated PDF with the
    # current paperformat: A4 portrait, 10mm top / 20mm bottom margin, 90 dpi).
    #
    #   printable height   = 842pt (A4) - 28.35pt (10mm top) - 56.7pt (20mm bottom)
    #   repeated header    = ~34pt  (round line + "For Delivery on" line + margin)
    #   space for drops    = ~722pt  ->  722 / 12.6 = ~57 rows
    #
    # PAGE_ROW_BUDGET is kept just under that measured 57 so a line that wraps
    # unexpectedly cannot push the last drop onto an unnumbered overflow page.
    PAGE_ROW_BUDGET = 55.0

    # Fixed vertical cost of a drop, on top of its item lines: top border +
    # padding, customer/address/phone line, the Order No / payment-method block
    # and the bottom margin. Measured at ~56pt -> 56 / 12.6 = ~4.4 rows.
    DROP_BASE_ROWS = 4.5

    # Approximate characters that fit on one line in each column, used only to
    # predict wrapping (item column = 68% width @13.5px, note column = 32% @13px).
    ITEM_CHARS_PER_LINE = 62
    NOTE_CHARS_PER_LINE = 30

    # The delivery-order barcode sits at the top of the right-hand column
    # (38px image + ~12px caption + margin = ~52px = ~42pt = ~3.3 rows).
    BARCODE_ROWS = 3.5

    def _estimate_wrapped_lines(self, text, chars_per_line):
        """How many printed lines a piece of text will occupy once wrapped."""
        if not text:
            return 0
        lines = 0
        for raw_line in str(text).splitlines() or ['']:
            lines += max(1, -(-len(raw_line) // chars_per_line))  # ceil division
        return max(lines, 1)

    def _drop_row_weight(self, drop):
        """Estimated height of a single drop, in rows."""
        item_rows = sum(
            self._estimate_wrapped_lines(item, self.ITEM_CHARS_PER_LINE)
            for item in drop['items']
        )
        # The barcode and the note are stacked in a column beside the items,
        # so they only add height when together they are taller than the
        # item list itself.
        right_col_rows = self._estimate_wrapped_lines(drop.get('note'), self.NOTE_CHARS_PER_LINE)
        if drop.get('barcode_src'):
            right_col_rows += self.BARCODE_ROWS
        return self.DROP_BASE_ROWS + max(item_rows, right_col_rows)

    def _paginate_drops(self, drops, max_page_weight=None):
        """Splits a batch's drops into distinct pages so that:
        1. Every page break is decided here in Python, not left to the browser
           to figure out mid-render - so each page dict below maps to exactly
           one physical PDF page.
        2. A single very large drop (many items) still gets its own page rather
           than being split apart or silently overflowing onto the next one.

        A new page is only started when the current one is genuinely full; a
        new *batch* always starts a new page, but that break is applied in the
        QWeb template (page-break-before on each group's first page), not here.

        NOTE: the weights are a proxy for vertical space, not a real mm/px
        measurement - same idea as _paginate_batch_categories in the packing
        list report. See the PAGE_ROW_BUDGET / DROP_BASE_ROWS comments above
        for how they were calibrated; re-measure them if the paperformat,
        font size or the drop layout in the template changes.
        """
        if max_page_weight is None:
            max_page_weight = self.PAGE_ROW_BUDGET

        pages = []
        current_page_drops = []
        current_weight = 0.0

        for drop in drops:
            drop_weight = self._drop_row_weight(drop)
            # If a single drop is heavier than a whole page on its own, let it
            # have the page to itself instead of looping forever trying to fit it.
            effective_max = max(max_page_weight, drop_weight)

            if current_page_drops and (current_weight + drop_weight > effective_max):
                pages.append({'drops': current_page_drops, 'is_last_page': False})
                current_page_drops = []
                current_weight = 0.0

            current_page_drops.append(drop)
            current_weight += drop_weight

        if current_page_drops:
            pages.append({'drops': current_page_drops, 'is_last_page': True})
        elif pages:
            pages[-1]['is_last_page'] = True

        return pages

    @api.model
    def _number_pages_continuously(self, groups):
        """Stamps page_number/total_pages onto every page dict across ALL batch
        groups, so the footer shows one running sequence for the whole report
        instead of restarting (or repeating) per batch.
        """
        flat_pages = [pg for g in groups for pg in g['pages']]
        total_pages = len(flat_pages)
        for idx, pg in enumerate(flat_pages, start=1):
            pg['page_number'] = idx
            pg['total_pages'] = total_pages
        return groups

    @api.model
    def _get_report_values(self, docids, data=None):
        from collections import defaultdict
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

            if not batches:
                continue

            # Batch pre-fetch pickings, moves, and lines across all orders
            all_candidate_orders = batches.order_ids.filtered(
                lambda so: so.state in ('sale', 'done')
                and getattr(so, 'delivery_channel', False) in ('regal_van', False)
            )

            all_pickings = self.env['stock.picking'].search([
                ('sale_id', 'in', all_candidate_orders.ids),
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
                ('order_id', 'in', all_candidate_orders.ids),
                ('display_type', '=', False),
                ('product_id', '!=', False),
            ])
            lines_by_order = defaultdict(list)
            for l in all_lines:
                lines_by_order[l.order_id.id].append(l)

            for batch in batches:
                eligible_orders = batch.order_ids.filtered(
                    lambda so: so.state in ('sale', 'done')
                    and getattr(so, 'delivery_channel', False) in ('regal_van', False)
                    and bool(pickings_by_order.get(so.id))
                )

                if not eligible_orders:
                    continue

                sorted_orders = sorted(eligible_orders, key=self._get_order_sort_key)

                drops = []
                for order in sorted_orders:
                    drop = self._build_drop(
                        order,
                        pickings=pickings_by_order.get(order.id),
                        delivery_product_ids=delivery_products_by_order.get(order.id),
                        lines=lines_by_order.get(order.id, []),
                    )
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

                    batch_pages = self._paginate_drops(drops)

                    all_batch_groups.append({
                        'batch_name': batch_name,
                        'batch_code': f"({batch_code})" if batch_code else "",
                        'depot_name': depot_name,
                        'delivery_date': delivery_date_str,
                        'total_deliveries': len(drops),
                        'pages': batch_pages,
                    })

        # Number pages continuously across the whole report (spans all
        # batches, not reset or repeated per batch).
        all_batch_groups = self._number_pages_continuously(all_batch_groups)

        # fields.Datetime.now() is UTC; convert to the printing user's local
        # timezone so "Printed at" shows their actual wall-clock time.
        printed_at_local = fields.Datetime.context_timestamp(self, fields.Datetime.now())

        return {
            'doc_ids': docids,
            'doc_model': 'delivery.note.round.wizard',
            'docs': docs,
            'batch_groups': all_batch_groups,
            'company': self.env.company,
            'printed_at': printed_at_local.strftime('%d/%m/%Y %H:%M:%S'),
        }
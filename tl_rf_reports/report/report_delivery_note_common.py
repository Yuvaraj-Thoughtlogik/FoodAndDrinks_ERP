# -*- coding: utf-8 -*-
import re
from odoo.tools import html2plaintext


class DeliveryNoteReportMixin(object):
    """Shared helpers for the Delivery Note Round reports (Regal Van & Courier).

    NOTE: this is a plain Python mixin, NOT an Odoo model on its own.
    It has no _name and is never registered with Odoo directly - it is only
    inherited by report_delivery_note_round_van.py and
    report_delivery_note_round_courier.py so the formatting logic
    (addresses, names, quantities, etc.) only has to be written once.
    """

    # --------------------------------------------------------------
    # TEXT / ADDRESS / NAME FORMATTING
    # --------------------------------------------------------------
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

    # --------------------------------------------------------------
    # QUANTITY / LINE FORMATTING
    # --------------------------------------------------------------
    def _format_qty(self, qty_val):
        """Return an int when the quantity has no meaningful decimal part, else the raw value."""
        try:
            return int(qty_val) if float(qty_val).is_integer() else qty_val
        except (TypeError, ValueError):
            return qty_val

    def _extract_hash_note(self, line_desc):
        """Pull a '#...#' annotation out of an order line description, if present."""
        if not line_desc or '#' not in line_desc:
            return ""
        match = re.search(r'(#.+?#)', line_desc)
        return match.group(1).strip() if match else ""

    def _special_note(self, sale_lines):
        """The Special Notes (special_requirements_notes_id) of one or more
        sale order lines, de-duplicated, as one string."""
        notes = []
        for sale_line in sale_lines or []:
            note = (sale_line.special_requirements_notes_id.name or '').strip()
            if note and note not in notes:
                notes.append(note)
        return ', '.join(notes)

    def _append_special_note(self, text, special_note):
        """`text` followed by the line's Special Note as '# note #' (same
        '#...#' convention as the notes typed in the line description)."""
        if not special_note or re.search(rf"#\s*{re.escape(special_note)}\s*#", text or ''):
            return text
        return f"{text} # {special_note} #".strip()

    def _format_line_item(self, line):
        qty = self._format_qty(getattr(line, 'product_uom_qty', 0))
        uom_name = (line.product_uom_id.name or '').strip().lower() if getattr(line, 'product_uom_id', False) and line.product_uom_id else ''

        if not uom_name or uom_name in ('units', 'unit', 'unit(s)', 'each', 'pc', 'pcs', 'p'):
            qty_prefix = f"{qty} x"
        else:
            qty_prefix = f"{qty} {line.product_uom_id.name}"

        prod_name = line.product_id.name if getattr(line, 'product_id', False) and line.product_id else (getattr(line, 'name', '') or '')
        extra_note = self._extract_hash_note((getattr(line, 'name', '') or '').strip())

        return f"{qty_prefix} {prod_name}{' ' + extra_note if extra_note else ''}"

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

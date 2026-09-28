# -*- coding: utf-8 -*-
import base64
import io
import logging
import re
from xml.sax.saxutils import escape as xml_escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    Flowable, HRFlowable, Image, KeepTogether, PageBreak, PageBreakIfNotEmpty, Paragraph, SimpleDocTemplate,
    Spacer, Table, TableStyle,
)
from reportlab.pdfgen import canvas

from odoo import api, fields, models
from .report_delivery_note_common import DeliveryNoteReportMixin

_logger = logging.getLogger(__name__)


class _HeaderMarker(Flowable):
    """Zero-size flowable that stamps the current batch's header text onto the
    canvas as soon as ReportLab draws it. Because it's inserted once at the
    top of each batch's content, whatever it sets stays the "current" header
    for every physical page that batch spans - the canvas just re-draws
    whatever was last stamped when a page is finalised (see _VanNoteCanvas).
    """
    def __init__(self, header_text, plain=False):
        super().__init__()
        self.header_text = header_text
        # plain=True: the following pages are an attached document (B2B
        # invoice / driver copy) - no round header, footer or page number.
        self.plain = plain
        self.width = 0
        self.height = 0

    def wrap(self, availWidth, availHeight):
        return (0, 0)

    def draw(self):
        self.canv.current_header = self.header_text
        self.canv.current_plain = self.plain


class _VanNoteCanvas(canvas.Canvas):
    """Two-pass canvas: replays every page once the total page count and each
    page's batch header (stamped by _HeaderMarker) are known, so the header
    banner and "Printed at" footer can be drawn identically to how the old
    QWeb template repeated them on every page."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []
        self.current_header = None
        self.current_plain = False

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
        if self.current_plain:
            return
        self.saveState()
        margin = 9 * mm
        width = A4[0] - (2 * margin)

        if self.current_header:
            header_style = ParagraphStyle(
                'VanHeaderBand', fontName='Helvetica-Bold', fontSize=12,
                leading=14, textColor=colors.black,
            )
            p = Paragraph(self.current_header, header_style)
            _, h = p.wrap(width, 20 * mm)
            p.drawOn(self, margin, A4[1] - margin - h)

        footer_style = ParagraphStyle(
            'VanFooter', fontName='Helvetica', fontSize=9, leading=11, textColor=colors.black,
        )
        footer = Paragraph(f"Printed at: {self.printed_at_text or ''}", footer_style)
        footer.wrap(width, 10 * mm)
        footer.drawOn(self, margin, 8 * mm)

        page_style = ParagraphStyle(
            'VanPageNum', fontName='Helvetica', fontSize=9, leading=11,
            textColor=colors.black, alignment=1,
        )
        page_num = Paragraph(str(self._pageNumber), page_style)
        page_num.wrap(width, 6 * mm)
        page_num.drawOn(self, margin, 4 * mm)

        self.restoreState()


class ReportDeliveryNoteRoundVan(DeliveryNoteReportMixin, models.AbstractModel):
    _name = 'report.tl_rf_reports.report_delivery_note_round_van'
    _description = 'Delivery Note Round Report - Regal Van'

    # Barcode rendering: the image is generated server-side (Code128) and
    # embedded directly - as a ReportLab Image for the fast PDF path, and as
    # a base64 PNG data URI for the (now unused, kept for parity) QWeb path -
    # so wkhtmltopdf/ReportLab never has to make an HTTP round-trip for it.
    BARCODE_SYMBOLOGY = 'Code128'
    BARCODE_RENDER_WIDTH = 600     # source image px (downscaled by the template)
    BARCODE_RENDER_HEIGHT = 100

    def _barcode_png(self, value):
        """Raw PNG bytes for `value`, or b'' when it can't be encoded."""
        if not value:
            return b''
        try:
            return self.env['ir.actions.report'].barcode(
                self.BARCODE_SYMBOLOGY,
                value,
                width=self.BARCODE_RENDER_WIDTH,
                height=self.BARCODE_RENDER_HEIGHT,
                humanreadable=0,
            )
        except Exception:  # noqa: BLE001 - a bad barcode must not kill the print
            _logger.warning("Delivery note (van): cannot encode barcode for %r", value)
            return b''

    def _barcode_data_uri(self, value):
        """Return a base64 PNG data URI for `value`, or '' when it can't be encoded."""
        png = self._barcode_png(value)
        if not png:
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

        commercial = main_partner.commercial_partner_id
        customer_type = main_partner.customer_type or commercial.customer_type

        return {
            'order_id': order.id,
            'picking_id': picking.id if picking else False,
            'is_b2b': customer_type == 'b2b_trade',
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
            'barcode_png': self._barcode_png(barcode_value),
            'barcode_src': self._barcode_data_uri(barcode_value),
        }

    # ------------------------------------------------------------------
    # Shared data prep - builds the list of {batch info, drops} used by both
    # the (now unused, kept for parity) QWeb path below and generate_pdf().
    # ------------------------------------------------------------------
    def _prepare_batch_groups(self, wizard):
        from collections import defaultdict

        batch_domain = [
            ('delivery_date', '>=', wizard.delivery_date_from),
            ('delivery_date', '<=', wizard.delivery_date_to),
        ]
        batches = self.env['round.management.batch'].search(
            batch_domain, order='delivery_date asc, code asc'
        )
        if not batches:
            return []

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

        batch_groups = []
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

            if not drops:
                continue

            batch_groups.append({
                'batch_name': batch.round_id.name if (batch.round_id and batch.round_id.name) else (batch.reference or ''),
                'batch_code': batch.code or '',
                'depot_name': batch.depot_id.name.upper() if batch.depot_id and batch.depot_id.name else 'GRIMSBY',
                'delivery_date': batch.delivery_date.strftime('%d/%m/%Y') if batch.delivery_date else '',
                'total_deliveries': len(drops),
                'drops': drops,
            })

        return batch_groups

    # ------------------------------------------------------------------
    # PAGINATION CALIBRATION (QWeb path only, kept for parity - see the note
    # at the top of generate_pdf() for why the fast path doesn't need this:
    # ReportLab lays out real content and breaks pages on actual measured
    # height, so there's nothing to calibrate).
    # ------------------------------------------------------------------
    PAGE_ROW_BUDGET = 55.0
    DROP_BASE_ROWS = 4.5
    ITEM_CHARS_PER_LINE = 62
    NOTE_CHARS_PER_LINE = 30
    BARCODE_ROWS = 3.5

    def _estimate_wrapped_lines(self, text, chars_per_line):
        if not text:
            return 0
        lines = 0
        for raw_line in str(text).splitlines() or ['']:
            lines += max(1, -(-len(raw_line) // chars_per_line))  # ceil division
        return max(lines, 1)

    def _drop_row_weight(self, drop):
        item_rows = sum(
            self._estimate_wrapped_lines(item, self.ITEM_CHARS_PER_LINE)
            for item in drop['items']
        )
        right_col_rows = self._estimate_wrapped_lines(drop.get('note'), self.NOTE_CHARS_PER_LINE)
        if drop.get('barcode_src'):
            right_col_rows += self.BARCODE_ROWS
        return self.DROP_BASE_ROWS + max(item_rows, right_col_rows)

    def _paginate_drops(self, drops, max_page_weight=None):
        if max_page_weight is None:
            max_page_weight = self.PAGE_ROW_BUDGET

        pages = []
        current_page_drops = []
        current_weight = 0.0

        for drop in drops:
            drop_weight = self._drop_row_weight(drop)
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
        flat_pages = [pg for g in groups for pg in g['pages']]
        total_pages = len(flat_pages)
        for idx, pg in enumerate(flat_pages, start=1):
            pg['page_number'] = idx
            pg['total_pages'] = total_pages
        return groups

    @api.model
    def _get_report_values(self, docids, data=None):
        docs = self.env['delivery.note.round.wizard'].browse(docids)
        all_batch_groups = []

        for wizard in docs:
            for group in self._prepare_batch_groups(wizard):
                group = dict(group)
                group['pages'] = self._paginate_drops(group.pop('drops'))
                all_batch_groups.append(group)

        all_batch_groups = self._number_pages_continuously(all_batch_groups)
        printed_at_local = fields.Datetime.context_timestamp(self, fields.Datetime.now())

        return {
            'doc_ids': docids,
            'doc_model': 'delivery.note.round.wizard',
            'docs': docs,
            'batch_groups': all_batch_groups,
            'company': self.env.company,
            'printed_at': printed_at_local.strftime('%d/%m/%Y %H:%M:%S'),
        }

    # ------------------------------------------------------------------
    # Fast path: builds the PDF directly with ReportLab. wkhtmltopdf isn't
    # normally the dominant cost here (van batches are much smaller than a
    # whole courier run - see delivery_note_round_wizard.py), but it still
    # avoids the subprocess entirely and, unlike the QWeb path, needs no
    # hand-calibrated row-weight pagination: Platypus measures the real
    # rendered height of each drop and only breaks the page when it
    # genuinely doesn't fit.
    # ------------------------------------------------------------------
    PX_TO_PT = 72.0 / 90.0  # the QWeb paperformat renders at 90dpi

    def generate_pdf(self, wizard):
        """Returns the finished PDF (bytes) for one Regal Van Delivery Note
        Round wizard, or None when there is nothing to print."""
        batch_groups = self._prepare_batch_groups(wizard)
        if not batch_groups:
            return None

        printed_at_local = fields.Datetime.context_timestamp(self, fields.Datetime.now())
        printed_at_text = printed_at_local.strftime('%d/%m/%Y %H:%M:%S')

        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer, pagesize=A4,
            leftMargin=9 * mm, rightMargin=9 * mm, topMargin=22 * mm, bottomMargin=16 * mm,
        )

        cust_style = ParagraphStyle('VanCust', fontName='Helvetica', fontSize=9.5, leading=12)
        addr_style = ParagraphStyle('VanAddr', fontName='Helvetica-Bold', fontSize=9.5, leading=12)
        tel_style = ParagraphStyle('VanTel', fontName='Helvetica-Bold', fontSize=9.5, leading=12, alignment=2)
        item_style = ParagraphStyle('VanItem', fontName='Helvetica', fontSize=9.5, leading=13)
        note_style = ParagraphStyle('VanNote', fontName='Helvetica-Bold', fontSize=9, leading=11, alignment=2)
        caption_style = ParagraphStyle('VanBarcodeCaption', fontName='Helvetica', fontSize=7, leading=8, alignment=1)
        pay_style = ParagraphStyle('VanPay', fontName='Helvetica', fontSize=9, leading=11)
        order_style = ParagraphStyle('VanOrderNo', fontName='Helvetica', fontSize=9, leading=11)
        price_style = ParagraphStyle('VanPrice', fontName='Helvetica-Bold', fontSize=10.5, leading=13, alignment=2)

        printable_width = A4[0] - (18 * mm)

        story = []
        for gi, group in enumerate(batch_groups):
            if gi:
                story.append(PageBreakIfNotEmpty())

            header_text = (
                f"DELIVERY NOTE FOR ROUND: <b>{xml_escape(group['batch_name'])}</b> "
                f"({xml_escape(group['batch_code'])})"
                f"<br/>For Delivery on: {xml_escape(group['delivery_date'])} &nbsp;&nbsp;&nbsp;"
                f"{group['total_deliveries']} Deliveries "
                f'<br/><font size="10">{xml_escape(group["depot_name"])}</font>'
            )
            story.append(_HeaderMarker(header_text))
            story.append(Spacer(1, 2 * mm))

            # Set after a B2B drop's attached invoice/driver copy: the round's
            # notes resume on a new page - but only once another drop really
            # follows. Adding the break + header marker straight after the
            # attachments would start a page for the zero-size marker alone,
            # printing an empty page (round header/footer only) at the end.
            resume_notes = False
            for drop in group['drops']:
                if resume_notes:
                    story.append(PageBreakIfNotEmpty())
                    story.append(_HeaderMarker(header_text))
                    resume_notes = False
                story.append(KeepTogether(self._build_drop_flowables(
                    drop, printable_width, cust_style, addr_style, tel_style,
                    item_style, note_style, caption_style, pay_style, order_style, price_style,
                )))
                if drop.get('is_b2b'):
                    attached = self._build_b2b_attachments(drop, printable_width)
                    if attached:
                        story.append(PageBreakIfNotEmpty())
                        story.append(_HeaderMarker(None, plain=True))
                        story += attached
                        resume_notes = True

        def _make_canvas(*args, **kwargs):
            c = _VanNoteCanvas(*args, **kwargs)
            c.printed_at_text = printed_at_text
            return c

        doc.title = 'Delivery Note Round - Regal Van'  # PDF metadata - shown by browser PDF viewers
        doc.author = self.env.company.name or ''
        doc.build(story, canvasmaker=_make_canvas)
        pdf_value = buffer.getvalue()
        buffer.close()
        return pdf_value

    def _get_b2b_invoices(self, order):
        """Customer invoices of the Sales Order, posted or still draft
        (cancelled invoices and credit notes are not printed)."""
        return order.invoice_ids.filtered(
            lambda m: m.move_type == 'out_invoice' and m.state in ('draft', 'posted')
        ).sorted('id')

    def _build_b2b_attachments(self, drop, width):
        """B2B customer: the Driver Copy and the Customer Copy of the Delivery
        Order, then the Sales Order's Invoice(s), each starting on its own page.
        Delivery Order -> Driver/Customer Copy; Delivery Order -> Sales Order -> Invoice."""
        order = self.env['sale.order'].browse(drop['order_id'])
        flowables = []
        if drop.get('picking_id'):
            picking = self.env['stock.picking'].browse(drop['picking_id'])
            copy_report = self.env['report.tl_rf_reports.report_driver_copy']
            flowables += copy_report._build_driver_copy_flowables(picking, width, copy_type='driver')
            flowables.append(PageBreak())
            flowables += copy_report._build_driver_copy_flowables(picking, width, copy_type='customer')
        invoice_report = self.env['report.tl_rf_reports.report_invoice_regal']
        for invoice in self._get_b2b_invoices(order):
            if flowables:
                flowables.append(PageBreak())
            flowables += invoice_report.with_company(invoice.company_id)._build_invoice_flowables(invoice, width)
        return flowables

    def _build_drop_flowables(
        self, drop, printable_width, cust_style, addr_style, tel_style,
        item_style, note_style, caption_style, pay_style, order_style, price_style,
    ):
        flowables = [
            HRFlowable(width=printable_width, thickness=1.5, color=colors.black, spaceAfter=2 * mm),
        ]

        top_row = Table(
            [[
                Paragraph(xml_escape(drop['cust']), cust_style),
                Paragraph(xml_escape(drop['addr']), addr_style),
                Paragraph(xml_escape(drop['tel']), tel_style),
            ]],
            colWidths=[printable_width * 0.28, printable_width * 0.54, printable_width * 0.18],
        )
        top_row.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP')]))
        flowables.append(top_row)
        flowables.append(Spacer(1, 1 * mm))

        items_html = '<br/>'.join(xml_escape(item) for item in drop['items']) or ''
        right_col = []
        if drop.get('barcode_png'):
            img = Image(io.BytesIO(drop['barcode_png']))
            img.drawWidth = 190 * self.PX_TO_PT
            img.drawHeight = 38 * self.PX_TO_PT
            right_col.append(img)
            right_col.append(Paragraph(xml_escape(drop.get('picking_name') or ''), caption_style))
            right_col.append(Spacer(1, 1 * mm))
        if drop.get('note'):
            right_col.append(Paragraph(xml_escape(drop['note']), note_style))

        body_row = Table(
            [[Paragraph(items_html, item_style), right_col or '']],
            colWidths=[printable_width * 0.68, printable_width * 0.32],
        )
        body_row.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP'), ('ALIGN', (1, 0), (1, 0), 'RIGHT')]))
        flowables.append(body_row)
        flowables.append(Spacer(1, 1 * mm))

        pay_labels = [
            ('Card Reader', drop['pay']['card_reader']), ('K/B', drop['pay']['kb']),
            ('LNP', drop['pay']['lnp']), ('Cash', drop['pay']['cash']),
            ('Cheque', drop['pay']['cheque']), ('Card', drop['pay']['card']),
        ]
        pay_text = '&nbsp;&nbsp;&nbsp;'.join(
            f"{label} [{'X' if checked else '&nbsp;'}]" for label, checked in pay_labels
        )
        bottom_row = Table(
            [[
                Paragraph(f"Order No: {xml_escape(drop['order_no'])}", order_style),
                Paragraph(pay_text, pay_style),
                Paragraph(xml_escape(drop['price']), price_style),
            ]],
            colWidths=[printable_width * 0.15, printable_width * 0.63, printable_width * 0.22],
        )
        bottom_row.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'MIDDLE')]))
        flowables.append(bottom_row)
        flowables.append(Spacer(1, 4 * mm))

        return flowables

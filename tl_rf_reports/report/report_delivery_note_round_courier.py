# -*- coding: utf-8 -*-
import base64
import io
from collections import defaultdict
from xml.sax.saxutils import escape as xml_escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.graphics.shapes import Drawing, Line
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    Image, KeepTogether, Paragraph, PageBreak, SimpleDocTemplate, Spacer, Table, TableStyle,
)

from odoo import api, models
from odoo.tools.image import image_data_uri

from .report_delivery_note_common import DeliveryNoteReportMixin


class _CourierNoteCanvas(canvas.Canvas):
    """Two-pass canvas so the footer disclaimer and "Page X of Y" can be drawn
    once the total page count is actually known, instead of being guessed."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self._draw_footer(total_pages)
            super().showPage()
        super().save()

    def _draw_footer(self, total_pages):
        self.saveState()
        margin = 9 * mm
        width = A4[0] - (2 * margin)

        disclaimer_style = ParagraphStyle(
            'CourierFooterDisclaimer', fontName='Helvetica', fontSize=7.5,
            leading=9, textColor=colors.HexColor('#333333'), alignment=1,
        )
        disclaimer = Paragraph(self.disclaimer_text or '', disclaimer_style)
        disclaimer.wrap(width, 15 * mm)
        disclaimer.drawOn(self, margin, 10 * mm)

        page_style = ParagraphStyle(
            'CourierFooterPageNum', fontName='Helvetica', fontSize=8,
            leading=10, textColor=colors.HexColor('#555555'), alignment=1,
        )
        page_num = Paragraph(f"Page {self._pageNumber} of {total_pages}", page_style)
        page_num.wrap(width, 5 * mm)
        page_num.drawOn(self, margin, 4 * mm)

        self.restoreState()


class ReportDeliveryNoteRoundCourier(DeliveryNoteReportMixin, models.AbstractModel):
    _name = 'report.tl_rf_reports.report_delivery_note_round_courier'
    _description = 'Delivery Note Round Report - Courier'

    # ------------------------------------------------------------------
    # QWeb / wkhtmltopdf path - kept registered (see report_delivery_note_
    # round_courier_views.xml) but no longer used by the Print button. See
    # generate_pdf() below for why: wkhtmltopdf renders roughly one page per
    # order here, so at a few thousand orders that was 10+ minutes and a
    # request timeout. Left in place only in case anything still calls the
    # report action directly.
    # ------------------------------------------------------------------
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

    # ------------------------------------------------------------------
    # Fast path: builds the PDF directly with ReportLab, in one pass, in
    # memory. No wkhtmltopdf subprocess, no per-page HTML rendering - just
    # native PDF drawing, so a few thousand orders finishes in seconds
    # instead of minutes. Used by delivery.note.round.wizard.action_print_
    # report() for the courier channel; see report_delivery_note_round_van.py
    # for the same treatment of the Regal Van channel. The QWeb path above is
    # left registered but unused, for parity/safety.
    # ------------------------------------------------------------------
    def _get_company_logo_flowable(self, company, max_width=45 * mm, max_height=18 * mm):
        if not company.logo:
            return None
        try:
            img = Image(io.BytesIO(base64.b64decode(company.logo)))
            aspect = img.imageWidth / float(img.imageHeight)
            if aspect > 1:
                img.drawWidth = max_width
                img.drawHeight = max_width / aspect
            else:
                img.drawHeight = max_height
                img.drawWidth = max_height * aspect
            return img
        except Exception:  # noqa: BLE001 - a bad logo must not break the print
            return None

    def generate_pdf(self, wizard):
        """Returns the finished PDF (bytes) for one Courier Delivery Note Round
        wizard, or None when there is nothing to print.

        Uses plain ORM search() + recordset iteration (same data-prep shape as
        the QWeb-era _get_report_values above) rather than raw SQL or
        search_read - the ORM already knows how each field is actually
        translated/stored, so there's no risk of the "assumed jsonb, column is
        actually varchar" class of bug a hand-written query can hit."""
        company = wizard.company_id if hasattr(wizard, 'company_id') and wizard.company_id else self.env.company

        applicable_orders = self.env['sale.order'].search(
            [
                ('delivery_channel', '=', 'courier'),
                ('state', 'in', ['sale', 'done']),
                ('delivery_date', '>=', wizard.delivery_date_from),
                ('delivery_date', '<=', wizard.delivery_date_to),
                ('picking_ids', '!=', False),
            ],
            order='delivery_date asc, name asc',
        )
        if not applicable_orders:
            return None

        # Batch pre-fetch pickings, moves, and lines to avoid N+1 queries.
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

        logo_flowable = self._get_company_logo_flowable(company)

        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer, pagesize=A4,
            leftMargin=9 * mm, rightMargin=9 * mm, topMargin=10 * mm, bottomMargin=22 * mm,
        )
        title_style = ParagraphStyle('CourierTitle', fontName='Helvetica', fontSize=13, leading=15)
        normal_style = ParagraphStyle('CourierNormal', fontName='Helvetica', fontSize=10, leading=12)
        bold_style = ParagraphStyle('CourierBold', fontName='Helvetica-Bold', fontSize=11, leading=13)
        cat_style = ParagraphStyle('CourierCategory', fontName='Helvetica-Bold', fontSize=10, leading=12)
        printable_width = A4[0] - (18 * mm)

        story = []
        printed_orders = 0
        for order in applicable_orders:
            pickings = pickings_by_order.get(order.id, self.env['stock.picking'])
            delivery_product_ids = delivery_products_by_order.get(order.id) if pickings else None

            order_lines = lines_by_order.get(order.id, [])
            categories = self._get_order_category_lines(order, delivery_product_ids, lines=order_lines)
            if not categories:
                continue

            if printed_orders:
                story.append(PageBreak())
            printed_orders += 1

            ship_partner = order.partner_shipping_id or order.partner_id
            main_partner = order.partner_id
            cust_name = self._format_customer_name(main_partner, include_code=False)
            cust_code = getattr(main_partner, 'customer_code', False) or getattr(main_partner, 'ref', False) or str(main_partner.id)
            addr_line1, addr_line2 = self._format_address_lines(ship_partner)

            d_date = order.delivery_date or wizard.delivery_date_from
            delivery_date_str = d_date.strftime('%d/%m/%Y') if d_date else ''

            header_table = Table(
                [[logo_flowable or "", Paragraph(f"Customer Delivery Note: For Delivery {xml_escape(delivery_date_str)}", title_style)]],
                colWidths=[printable_width * 0.25, printable_width * 0.75],
            )
            header_table.setStyle(TableStyle([
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('LEFTPADDING', (1, 0), (1, 0), 5),
            ]))
            story.append(header_table)
            story.append(Spacer(1, 4 * mm))
            story.append(Paragraph(f"Customer ID&nbsp;&nbsp;<b>{xml_escape(cust_code)}</b>", normal_style))
            story.append(Spacer(1, 2 * mm))

            cust_table = Table(
                [
                    [Paragraph(f"<b>{xml_escape(cust_name)}</b>", bold_style), Paragraph("Deliver To:", normal_style),
                     Paragraph(f"<b>{xml_escape(addr_line1)}</b>", bold_style)],
                    ["", "", Paragraph(f"<b>{xml_escape(addr_line2)}</b>", bold_style) if addr_line2 else ""],
                ],
                colWidths=[printable_width * 0.42, printable_width * 0.15, printable_width * 0.43],
            )
            cust_table.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP'), ('SPAN', (0, 0), (0, 1))]))
            story.append(cust_table)
            story.append(Spacer(1, 3 * mm))

            rule = Drawing(printable_width, 1)
            rule.add(Line(0, 0, printable_width, 0, strokeWidth=1, strokeColor=colors.black))
            story.append(rule)
            story.append(Spacer(1, 2 * mm))

            for cat in categories:
                cat_rule = Drawing(printable_width, 1)
                cat_rule.add(Line(0, 0, printable_width, 0, strokeWidth=1, strokeColor=colors.black))

                item_rows = [
                    [Paragraph(str(item['qty']), normal_style), Paragraph("X", normal_style),
                     Paragraph(
                         xml_escape(item['product_name']) + (f" {xml_escape(item['extra_note'])}" if item['extra_note'] else ''),
                         normal_style,
                     )]
                    for item in cat['lines']
                ]
                items_table = Table(item_rows, colWidths=[printable_width * 0.06, printable_width * 0.06, printable_width * 0.88])
                items_table.setStyle(TableStyle([
                    ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                    ('TOPPADDING', (0, 0), (-1, -1), 1),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 1),
                ]))

                story.append(KeepTogether([
                    Paragraph(xml_escape(cat['name']), cat_style), cat_rule, Spacer(1, 1 * mm),
                    items_table, Spacer(1, 1 * mm), cat_rule, Spacer(1, 3 * mm),
                ]))

        if not printed_orders:
            return None

        disclaimer_text = (
            "The goods received should arrive with you in perfect condition having been held at optimum "
            "temperature. If for any reason you are unhappy with the goods or you believe they have not been "
            "delivered as expected then please don't hesitate to contact one of our customer service team on "
            f"{xml_escape(company.phone or '')} or by email to {xml_escape(company.email or '')} and someone "
            "will be happy to assist with your query."
        )

        def _make_canvas(*args, **kwargs):
            c = _CourierNoteCanvas(*args, **kwargs)
            c.disclaimer_text = disclaimer_text
            return c

        doc.title = 'Delivery Note Round - Courier'  # PDF metadata - shown by browser PDF viewers
        doc.author = self.env.company.name or ''
        doc.build(story, canvasmaker=_make_canvas)
        pdf_value = buffer.getvalue()
        buffer.close()
        return pdf_value

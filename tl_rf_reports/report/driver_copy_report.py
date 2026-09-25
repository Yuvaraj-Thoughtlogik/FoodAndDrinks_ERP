# -*- coding: utf-8 -*-
import io
from xml.sax.saxutils import escape as xml_escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import HRFlowable, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from odoo import api, models
from .report_delivery_note_common import DeliveryNoteReportMixin


def _esc(val):
    return xml_escape(str(val or ''))


class ReportDriverCopy(DeliveryNoteReportMixin, models.AbstractModel):
    """Driver Copy of a Delivery Order, built with ReportLab.

    Printed from the Delivery Order (Print > Driver Copy, see
    models/ir_actions_report.py) and appended after a B2B customer's
    delivery note in the Regal Van Delivery Note Round report.

    Data: Delivery Order (lines, warehouse) -> its Sales Order (number,
    dates, notes, invoice/delivery addresses) -> customer (A/C code,
    company name, phone numbers).
    """
    _name = 'report.tl_rf_reports.report_driver_copy'
    _description = 'Driver Copy (ReportLab)'

    @api.model
    def _get_report_values(self, docids, data=None):
        # Only used by Odoo's HTML fallback; the PDF comes from generate_pdf().
        return {
            'doc_ids': docids,
            'doc_model': 'stock.picking',
            'docs': self.env['stock.picking'].browse(docids),
        }

    def _fmt_date(self, value):
        return value.strftime('%d/%m/%Y') if value else ''

    def _address_html(self, partner):
        if not partner:
            return ''
        state = partner.state_id.name if partner.state_id else ''
        parts = [partner.street, partner.street2, partner.city, state, partner.zip]
        return '<br/>'.join(_esc(p) for p in parts if p)

    def _line_description(self, product, sale_line=None, fallback=''):
        """Product name, plus the '#...#' annotation from the sale line (same
        convention as the delivery notes)."""
        name = product.name or fallback or ''
        hash_note = self._extract_hash_note((sale_line.name or '').strip()) if sale_line else ''
        return f"{name} {hash_note}".strip()

    def _get_driver_copy_lines(self, picking):
        """(product code, qty, description) rows, one per Sales Order line
        on this delivery - like the invoice. A Kit is shown as the sold kit
        product, not the component moves it explodes into. Quantity is the
        sale line's ordered quantity. Moves not linked to a sale line (added
        manually on the delivery) are listed as-is."""
        rows = []
        seen_sale_lines = set()
        moves = picking.move_ids.filtered(lambda m: m.state != 'cancel' and m.product_id)
        for move in moves.sorted(lambda m: (m.sale_line_id.sequence if m.sale_line_id else 10**6, m.id)):
            sale_line = move.sale_line_id
            if sale_line:
                if sale_line.id in seen_sale_lines:
                    continue
                seen_sale_lines.add(sale_line.id)
                rows.append((
                    sale_line.product_id.default_code or '',
                    sale_line.product_uom_qty,
                    self._line_description(sale_line.product_id, sale_line, sale_line.name),
                ))
            else:
                rows.append((
                    move.product_id.default_code or '',
                    move.product_uom_qty,
                    self._line_description(move.product_id, fallback=move.description_picking),
                ))
        return rows

    def _build_driver_copy_flowables(self, picking, width):
        """Flowables for one Delivery Order, fitting a frame `width` points wide."""
        order = picking.sale_id
        company = picking.company_id
        partner = order.partner_id if order else picking.partner_id
        commercial = partner.commercial_partner_id if partner else partner
        invoice_partner = (order.partner_invoice_id if order else False) or commercial
        delivery_partner = (order.partner_shipping_id if order else False) or picking.partner_id
        warehouse = picking.picking_type_id.warehouse_id or (order.warehouse_id if order else False)
        order_no = order.name if order else (picking.origin or '')

        big = ParagraphStyle('DCBig', fontName='Helvetica', fontSize=12, leading=15)
        big_bold = ParagraphStyle('DCBigBold', fontName='Helvetica-Bold', fontSize=12, leading=15)
        title = ParagraphStyle('DCTitle', fontName='Helvetica', fontSize=11, leading=14, alignment=TA_CENTER)
        company_name = ParagraphStyle('DCCompany', fontName='Helvetica-Bold', fontSize=9, leading=11, alignment=TA_CENTER)
        company_addr = ParagraphStyle('DCCompanyAddr', fontName='Helvetica', fontSize=7.5, leading=9.5, alignment=TA_CENTER)
        label = ParagraphStyle('DCLabel', fontName='Helvetica-Bold', fontSize=8, leading=10)
        value = ParagraphStyle('DCValue', fontName='Helvetica', fontSize=8, leading=10)
        value_center = ParagraphStyle('DCValueC', parent=value, alignment=TA_CENTER)
        th = ParagraphStyle('DCTh', fontName='Helvetica-Bold', fontSize=8, leading=10)
        th_center = ParagraphStyle('DCThC', parent=th, alignment=TA_CENTER)

        def u(text):
            return f"<u>{_esc(text)}</u>"

        flow = []

        # --- "Del Note number" + "Driver Copy" ---
        top = Table(
            [[
                '',
                Paragraph(f"Del Note number: &nbsp;&nbsp;&nbsp;&nbsp;<b>{_esc(order_no)}</b>", big),
            ]],
            colWidths=[width * 0.55, width * 0.45],
        )
        top.setStyle(TableStyle([('ALIGN', (1, 0), (1, 0), 'RIGHT'), ('LEFTPADDING', (0, 0), (-1, -1), 0)]))
        flow += [top, Spacer(1, 3 * mm), Paragraph(u('Driver Copy'), title), Spacer(1, 4 * mm)]

        # --- Company header ---
        company_bits = [company.street, company.street2, company.city, company.state_id.name if company.state_id else '', company.zip]
        contact_bits = []
        if company.phone:
            contact_bits.append(f"Tel: {_esc(company.phone)}")
        if getattr(company, 'fax', False):
            contact_bits.append(f"Fax: {_esc(company.fax)}")
        box = [
            Paragraph(_esc(company.name), company_name),
            Paragraph(_esc(', '.join(b for b in company_bits if b)), company_addr),
            Paragraph(' '.join(contact_bits), company_addr),
            Spacer(1, 4 * mm),
        ]

        # --- Customer / order summary ---
        summary = Table(
            [
                [Paragraph(u('Customer A/C No:'), label), Paragraph(u('Order No:'), label),
                 Paragraph(u('Order Date:'), label), Paragraph(u('Delivery Date:'), label)],
                [Paragraph(_esc(getattr(commercial, 'customer_code', False) or (commercial.ref if commercial else '')), value),
                 Paragraph(_esc(order_no), value),
                 Paragraph(_esc(self._fmt_date(order.date_order if order else False)), value),
                 Paragraph(_esc(self._fmt_date(
                     (getattr(order, 'delivery_date', False) if order else False) or picking.scheduled_date
                 )), value)],
            ],
            colWidths=[width * 0.235] * 4,
        )
        summary.setStyle(TableStyle([('LEFTPADDING', (0, 0), (-1, -1), 0), ('TOPPADDING', (0, 0), (-1, -1), 1),
                                     ('BOTTOMPADDING', (0, 0), (-1, -1), 1)]))
        company_row = Table(
            [[
                Paragraph(u('Company Name:'), label),
                Paragraph(_esc((commercial.name or '')[:40] if commercial else ''), value),
                Paragraph(u('Depot:'), label),
                Paragraph(_esc(warehouse.name if warehouse else ''), value),
            ]],
            colWidths=[width * 0.18, width * 0.46, width * 0.10, width * 0.20],
        )
        company_row.setStyle(TableStyle([('LEFTPADDING', (0, 0), (-1, -1), 0), ('ALIGN', (2, 0), (2, 0), 'RIGHT')]))
        box += [summary, company_row, Spacer(1, 1 * mm),
                HRFlowable(width='100%', thickness=0.75, color=colors.black, spaceAfter=3 * mm)]

        # --- Addresses ---
        phone = (partner.phone if partner else '') or ''
        mobile = (getattr(partner, 'mobile', '') if partner else '') or ''
        addresses = Table(
            [
                [Paragraph(u('Invoice Address:'), label), Paragraph(u('Delivery Address:'), label)],
                [Paragraph(self._address_html(invoice_partner), value), Paragraph(self._address_html(delivery_partner), value)],
                [Paragraph(f"tel: ({_esc(phone)})", value_center), Paragraph(f"mob: ({_esc(mobile)})", value_center)],
            ],
            colWidths=[width * 0.47, width * 0.47],
        )
        addresses.setStyle(TableStyle([
            ('LEFTPADDING', (0, 0), (-1, -1), 6 * mm),
            ('TOPPADDING', (0, 2), (-1, 2), 4 * mm),
        ]))
        box.append(addresses)

        # Rounded frame around the company/customer header (as on the
        # sample). The lines and notes stay outside it so a long order can
        # flow onto further pages - a single table cell can't split.
        frame = Table([[box]], colWidths=[width])
        frame.setStyle(TableStyle([
            ('BOX', (0, 0), (-1, -1), 0.75, colors.black),
            ('ROUNDEDCORNERS', [6, 6, 6, 6]),
            ('LEFTPADDING', (0, 0), (-1, -1), 4 * mm),
            ('RIGHTPADDING', (0, 0), (-1, -1), 4 * mm),
            ('TOPPADDING', (0, 0), (-1, -1), 3 * mm),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4 * mm),
        ]))
        flow += [frame, Spacer(1, 5 * mm)]

        # --- Lines ---
        rows = [[Paragraph(u('Product Code:'), th), Paragraph(u('Qty Ordered:'), th_center), Paragraph(u('Description:'), th)]]
        for code, qty, description in self._get_driver_copy_lines(picking):
            rows.append([
                Paragraph(_esc(code), value),
                Paragraph(f"{qty:.2f}", value_center),
                Paragraph(_esc(description), value),
            ])
        lines_table = Table(rows, colWidths=[width * 0.28, width * 0.18, width * 0.54], repeatRows=1)
        lines_table.setStyle(TableStyle([
            ('BOX', (0, 0), (-1, -1), 0.75, colors.black),
            ('LINEAFTER', (0, 0), (1, -1), 0.75, colors.black),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('TOPPADDING', (0, 0), (-1, -1), 2),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 5),
        ]))
        flow += [lines_table, Spacer(1, 6 * mm)]

        # --- Delivery notes (sales order notes) ---
        notes = self._clean_text(order.note) if order else ''
        flow.append(Paragraph(u('Delivery Notes:'), label))
        if notes:
            flow.append(Paragraph(_esc(notes).replace('\n', '<br/>'), ParagraphStyle(
                'DCNotes', parent=value, leftIndent=4 * mm, spaceBefore=1 * mm,
            )))
        return flow

    def generate_pdf(self, pickings):
        """One PDF containing a Driver Copy for every picking, each on a new page."""
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer, pagesize=A4,
            leftMargin=12 * mm, rightMargin=12 * mm, topMargin=12 * mm, bottomMargin=12 * mm,
            title=', '.join(p.name or '' for p in pickings),
        )
        width = A4[0] - 24 * mm
        story = []
        for idx, picking in enumerate(pickings):
            if idx:
                story.append(PageBreak())
            story += self._build_driver_copy_flowables(picking, width)
        doc.author = self.env.company.name or ''
        doc.build(story)
        value = buffer.getvalue()
        buffer.close()
        return value

# -*- coding: utf-8 -*-
import base64
import io
from xml.sax.saxutils import escape as xml_escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from odoo import models


def _esc(val):
    return xml_escape(str(val or ''))


class ReportRegalInvoice(models.AbstractModel):
    """Regal Fish customer invoice layout, built with ReportLab.

    Replaces the output of Odoo's standard invoice reports
    (account.report_invoice_with_payments / account.report_invoice - see
    models/ir_actions_report.py), so Print, Send & Print and the portal
    download all produce this format. _build_invoice_flowables() is also
    used directly by the Regal Van Delivery Note Round report, which prints
    the invoice right after a B2B customer's delivery note.
    """
    _name = 'report.tl_rf_reports.report_invoice_regal'
    _description = 'Regal Fish Invoice (ReportLab)'

    GREY = colors.HexColor('#9e9e9e')
    HEADER_BG = colors.HexColor('#d9d9d9')

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _money(self, move, amount):
        symbol = move.currency_id.symbol or ''
        return f"{symbol}{amount:,.2f}"

    def _vat_label(self, line):
        """'20.00%' style label from the line's percentage taxes."""
        percents = [t.amount for t in line.tax_ids if t.amount_type == 'percent']
        return f"{sum(percents):.2f}%" if percents else '0.00%'

    def _delivery_date(self, move):
        orders = move.invoice_line_ids.sale_line_ids.order_id
        order_date = next((o.delivery_date for o in orders if getattr(o, 'delivery_date', False)), False)
        return order_date or getattr(move, 'delivery_date', False) or False

    def _partner_lines(self, partner):
        state = partner.state_id.name if partner.state_id else ''
        return [p for p in (partner.street, partner.street2, partner.city, state, partner.zip) if p]

    def _company_logo(self, company, max_w, max_h):
        if not company.logo:
            return None
        try:
            img = Image(io.BytesIO(base64.b64decode(company.logo)))
        except Exception:  # noqa: BLE001 - a bad logo must not kill the print
            return None
        ratio = min(max_w / img.imageWidth, max_h / img.imageHeight)
        img.drawWidth = img.imageWidth * ratio
        img.drawHeight = img.imageHeight * ratio
        img.hAlign = 'RIGHT'
        return img

    def _title(self, move, proforma=False):
        # if proforma:
        #     return 'Pro-Forma Invoice'
        # if move.move_type == 'out_refund':
        #     return 'Credit Note'
        # if move.state == 'draft':
        #     return 'Draft Invoice'
        return 'Invoice'

    # ------------------------------------------------------------------
    # Layout
    # ------------------------------------------------------------------
    def _build_invoice_flowables(self, move, width, proforma=False):
        """Flowables for one invoice, fitting a frame `width` points wide."""
        company = move.company_id
        partner = move.partner_id
        commercial = partner.commercial_partner_id

        title_style = ParagraphStyle(
            'RFInvTitle', fontName='Helvetica-Bold', fontSize=30, leading=34, textColor=self.GREY,
        )
        company_style = ParagraphStyle(
            'RFInvCompany', fontName='Helvetica', fontSize=8.5, leading=11, alignment=TA_RIGHT,
        )
        label_style = ParagraphStyle('RFInvLabel', fontName='Helvetica-Bold', fontSize=9, leading=12)
        text_style = ParagraphStyle('RFInvText', fontName='Helvetica', fontSize=8.5, leading=11.5)
        meta_label = ParagraphStyle(
            'RFInvMetaLabel', fontName='Helvetica-Bold', fontSize=8.5, leading=12, alignment=TA_RIGHT,
        )
        meta_value = ParagraphStyle(
            'RFInvMetaValue', fontName='Helvetica', fontSize=8.5, leading=12, alignment=TA_RIGHT,
        )
        th_left = ParagraphStyle('RFInvTh', fontName='Helvetica', fontSize=8.5, leading=11, alignment=TA_LEFT)
        th_right = ParagraphStyle('RFInvThR', parent=th_left, alignment=TA_RIGHT)
        td_left = ParagraphStyle('RFInvTd', fontName='Helvetica', fontSize=8.5, leading=11)
        td_right = ParagraphStyle('RFInvTdR', parent=td_left, alignment=TA_RIGHT)
        tot_label = ParagraphStyle(
            'RFInvTotLabel', fontName='Helvetica-Bold', fontSize=8.5, leading=12, alignment=TA_RIGHT,
        )
        tot_value = ParagraphStyle('RFInvTotValue', fontName='Helvetica', fontSize=8.5, leading=12, alignment=TA_RIGHT)
        grand_value = ParagraphStyle('RFInvGrand', parent=tot_value, fontName='Helvetica-Bold')

        flow = []

        # --- Header: big title (left) / logo + company address (right) ---
        company_lines = [f"{_esc(company.name)}"] + [_esc(l) for l in self._partner_lines(company.partner_id)]
        if company.phone:
            company_lines.append(f"Tel: {_esc(company.phone)}")
        if getattr(company, 'fax', False):
            company_lines.append(f"Fax: {_esc(company.fax)}")
        if company.email:
            company_lines.append(f"Email: {_esc(company.email)}")
        right_col = []
        logo = self._company_logo(company, width * 0.36, 26 * mm)
        if logo:
            right_col += [logo, Spacer(1, 3 * mm)]
        right_col.append(Paragraph('<br/>'.join(company_lines), company_style))

        header = Table(
            [[Paragraph(_esc(self._title(move, proforma)), title_style), right_col]],
            colWidths=[width * 0.55, width * 0.45],
        )
        header.setStyle(TableStyle([
            ('VALIGN', (0, 0), (0, 0), 'MIDDLE'),
            ('VALIGN', (1, 0), (1, 0), 'TOP'),
            ('LEFTPADDING', (0, 0), (-1, -1), 0),
            ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ]))
        flow += [header, Spacer(1, 8 * mm)]

        # --- Invoice To (left) / invoice meta (right) ---
        to_lines = []
        if partner != commercial and partner.name:
            to_lines.append(_esc(partner.name))
        to_lines += [_esc(l) for l in self._partner_lines(partner)]
        invoice_to = [
            Paragraph('Invoice To:', label_style),
            Paragraph(_esc(commercial.name), label_style),
            Spacer(1, 1.5 * mm),
            Paragraph('<br/>'.join(to_lines), text_style),
        ]

        delivery_date = self._delivery_date(move)
        meta_rows = [
            ('Invoice Number:', move.name if move.name and move.name != '/' else ''),
            ('Account Number:', getattr(commercial, 'customer_code', False) or commercial.ref or ''),
            ('Invoice Date:', move.invoice_date.strftime('%d/%m/%Y') if move.invoice_date else ''),
            ('Delivery Date:', delivery_date.strftime('%d/%m/%Y') if delivery_date else ''),
        ]
        meta = Table(
            [[Paragraph(_esc(k), meta_label), Paragraph(_esc(v), meta_value)] for k, v in meta_rows],
            colWidths=[width * 0.20, width * 0.14],
        )
        meta.setStyle(TableStyle([
            ('TOPPADDING', (0, 0), (-1, -1), 1),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 1),
            ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ]))

        addr_block = Table([[invoice_to, meta]], colWidths=[width * 0.60, width * 0.40])
        addr_block.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('VALIGN', (1, 0), (1, 0), 'MIDDLE'),
            ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
            ('LEFTPADDING', (0, 0), (-1, -1), 0),
            ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ]))
        flow += [addr_block, Spacer(1, 2 * mm)]

        # --- Lines ---
        rows = [[
            Paragraph('Qty', th_left),
            Paragraph('Item Description', th_left),
            Paragraph('Unit Price', th_right),
            Paragraph('VAT %', th_right),
            Paragraph('Line Total', th_right),
        ]]
        for line in move.invoice_line_ids.filtered(lambda l: l.display_type == 'product'):
            description = line.product_id.name if line.product_id else (line.name or '')
            rows.append([
                Paragraph(f"{line.quantity:.2f}", td_left),
                Paragraph(_esc(description), td_left),
                Paragraph(_esc(self._money(move, line.price_unit)), td_right),
                Paragraph(_esc(self._vat_label(line)), td_right),
                Paragraph(_esc(self._money(move, line.price_subtotal)), td_right),
            ])
        lines_table = Table(
            rows,
            colWidths=[width * w for w in (0.09, 0.53, 0.12, 0.12, 0.14)],
            repeatRows=1,
        )
        lines_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), self.HEADER_BG),
            ('BOX', (0, 0), (-1, -1), 0.75, colors.black),
            ('INNERGRID', (0, 0), (-1, 0), 0.75, colors.black),
            ('LINEAFTER', (0, 1), (-2, -1), 0.75, colors.black),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('TOPPADDING', (0, 0), (-1, -1), 3),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ]))
        flow.append(lines_table)

        # --- Totals ---
        totals = Table(
            [
                [Paragraph('Sub Total:', tot_label), Paragraph(_esc(self._money(move, move.amount_untaxed)), tot_value)],
                [Paragraph('Total Vat:', tot_label), Paragraph(_esc(self._money(move, move.amount_tax)), tot_value)],
                [Paragraph('Order Total:', tot_label), Paragraph(_esc(self._money(move, move.amount_total)), grand_value)],
            ],
            colWidths=[width * 0.20, width * 0.14],
            hAlign='RIGHT',
        )
        totals.setStyle(TableStyle([
            ('TOPPADDING', (0, 0), (-1, -1), 2),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
            ('LINEBELOW', (1, 0), (1, 0), 0.5, colors.black),
            ('LINEBELOW', (1, 1), (1, 1), 0.5, colors.black),
        ]))
        flow += [Spacer(1, 2 * mm), totals]
        return flow

    def generate_pdf(self, moves, proforma=False):
        """One PDF containing every invoice in `moves`, each starting on a new page."""
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer, pagesize=A4,
            leftMargin=15 * mm, rightMargin=15 * mm, topMargin=12 * mm, bottomMargin=15 * mm,
            title=', '.join(m.name or '' for m in moves),
        )
        width = A4[0] - 30 * mm
        story = []
        for idx, move in enumerate(moves):
            if idx:
                story.append(PageBreak())
            story += self._build_invoice_flowables(move, width, proforma=proforma)
        doc.author = self.env.company.name or ''
        doc.build(story)
        value = buffer.getvalue()
        buffer.close()
        return value

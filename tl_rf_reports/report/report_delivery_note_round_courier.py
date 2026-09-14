# -*- coding: utf-8 -*-
import io
import base64
from collections import defaultdict
from odoo import api, fields, models, _
from odoo.exceptions import UserError

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, KeepTogether, Image
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.graphics.shapes import Drawing, Line
from reportlab.pdfgen import canvas


class NumberedCanvas(canvas.Canvas):
    """
    Two-pass canvas to dynamically calculate and render 'Page X of Y' 
    along with the fixed customer service footer on every page.
    """
    def __init__(self, *args, **kwargs):
        super(NumberedCanvas, self).__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_decorations(num_pages)
            super(NumberedCanvas, self).showPage()
        super(NumberedCanvas, self).save()

    def draw_page_decorations(self, page_count):
        self.saveState()
        margin = 9 * mm
        width = A4[0] - (2 * margin)
        
        # 1. Main Footer Paragraph
        footer_style = ParagraphStyle(
            'FooterStyle',
            fontName='Helvetica',
            fontSize=7.5,
            leading=9,
            textColor=colors.HexColor('#333333'),
            alignment=1
        )
        footer_text = (
            "The goods received should arrive with you in perfect condition having been held at optimum temperature. "
            "If for any reason you are unhappy with the goods or you believe they have not been delivered as expected "
            "then please don't hesitate to contact one of our customer service team on 08453 893 973 or by email to "
            "info@regalfish.co.uk and someone will be happy to assist with your query."
        )
        p = Paragraph(footer_text, footer_style)
        w, h = p.wrap(width, 15 * mm)
        p.drawOn(self, margin, 10 * mm)

        # 2. Page Numbering ("Page X of Y")
        page_style = ParagraphStyle(
            'PageNumStyle',
            fontName='Helvetica',
            fontSize=8,
            leading=10,
            textColor=colors.HexColor('#555555'),
            alignment=1
        )
        page_text = f"Page {self._pageNumber} of {page_count}"
        p_page = Paragraph(page_text, page_style)
        w_p, h_p = p_page.wrap(width, 5 * mm)
        p_page.drawOn(self, margin, 4 * mm)

        self.restoreState()


class DeliveryNoteRoundWizard(models.TransientModel):
    _inherit = 'delivery.note.round.wizard'

    def action_print_report(self):
        """Generates the PDF in memory with logo and returns a base64 download action."""
        self.ensure_one()
        if self.delivery_channel == 'courier':
            report_model = self.env['report.tl_rf_reports.report_delivery_note_round_courier']
            pdf_bytes = report_model.generate_pdf_stream(self)
            
            pdf_base64 = base64.b64encode(pdf_bytes)
            
            filename = f"Delivery_Note_Round_Courier_{self.delivery_date_from.strftime('%Y%m%d')}.pdf"
            attachment = self.env['ir.attachment'].create({
                'name': filename,
                'type': 'binary',
                'datas': pdf_base64,
                'mimetype': 'application/pdf',
                'res_model': self._name,
                'res_id': self.id,
            })
            
            return {
                'type': 'ir.actions.act_url',
                'url': f'/web/content/{attachment.id}?download=true',
                'target': 'self',
            }
        return super().action_print_report()


class ReportDeliveryNoteRoundCourier(models.AbstractModel):
    _name = 'report.tl_rf_reports.report_delivery_note_round_courier'
    _description = 'Direct Memory PDF Generator - Courier'

    def _get_company_logo_flowable(self, company, max_width=45*mm, max_height=18*mm):
        """Extracts company logo binary and converts it to a ReportLab Image object."""
        if not company.logo:
            return ""
        try:
            logo_data = base64.b64decode(company.logo)
            logo_stream = io.BytesIO(logo_data)
            img = Image(logo_stream)
            
            aspect = img.imageWidth / float(img.imageHeight)
            if aspect > 1:
                img.drawWidth = max_width
                img.drawHeight = max_width / aspect
            else:
                img.drawHeight = max_height
                img.drawWidth = max_height * aspect
            return img
        except Exception:
            return ""

    def generate_pdf_stream(self, wizard):
        company = self.env.company
        logo_image = self._get_company_logo_flowable(company)
        
        # 1. Fetch orders
        orders = self.env['sale.order'].search([
            ('delivery_channel', '=', 'courier'),
            ('state', 'in', ['sale', 'done']),
            ('delivery_date', '>=', wizard.delivery_date_from),
            ('delivery_date', '<=', wizard.delivery_date_to),
        ], order='delivery_date asc, name asc')

        if not orders:
            raise UserError(_("No confirmed Courier orders found for the selected dates."))

        order_ids = orders.ids

        # Fetch lines & products
        sol_read = self.env['sale.order.line'].search_read(
            [('order_id', 'in', order_ids), ('display_type', '=', False), ('product_id', '!=', False)],
            ['order_id', 'product_id', 'product_uom_qty', 'name']
        )
        product_ids = list({l['product_id'][0] for l in sol_read if l['product_id']})
        products = {
            p['id']: p for p in self.env['product.product'].search_read(
                [('id', 'in', product_ids)],
                ['id', 'name', 'categ_id', 'use_frozen', 'use_fresh']
            )
        }

        lines_by_order = defaultdict(list)
        for l in sol_read:
            p_info = products.get(l['product_id'][0], {})
            lines_by_order[l['order_id'][0]].append({
                'product_name': p_info.get('name') or l['product_id'][1],
                'categ_name': p_info.get('categ_id')[1] if p_info.get('categ_id') else '',
                'use_frozen': p_info.get('use_frozen', False),
                'use_fresh': p_info.get('use_fresh', False),
                'qty': int(l['product_uom_qty']) if l['product_uom_qty'] % 1 == 0 else round(l['product_uom_qty'], 2),
                'note': l['name'].split('#')[1].strip() if '#' in (l['name'] or '') else '',
            })

        # 2. Document Setup
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer,
            pagesize=A4,
            leftMargin=9 * mm,
            rightMargin=9 * mm,
            topMargin=10 * mm,
            bottomMargin=22 * mm  # Space allocated for footer text + page numbers
        )

        styles = getSampleStyleSheet()
        normal_style = ParagraphStyle('NormalStyle', fontName='Helvetica', fontSize=10, leading=12)
        title_style = ParagraphStyle('TitleStyle', fontName='Helvetica', fontSize=13, leading=15)
        bold_11 = ParagraphStyle('Bold11', fontName='Helvetica-Bold', fontSize=11, leading=13)
        cat_style = ParagraphStyle('CatStyle', fontName='Helvetica-Bold', fontSize=10, leading=12)

        printable_width = A4[0] - (18 * mm)
        story = []

        total_orders = len(orders)
        for idx, order in enumerate(orders):
            lines_data = lines_by_order.get(order.id, [])
            if not lines_data:
                continue

            d_date = getattr(order, 'delivery_date', False) or wizard.delivery_date_from
            delivery_date_str = d_date.strftime('%d/%m/%Y') if d_date else ''

            # Header with Logo & Title Table
            header_text = f"Customer Delivery Note: For Delivery {delivery_date_str}"
            header_table_data = [[
                logo_image if logo_image else "",
                Paragraph(header_text, title_style)
            ]]
            
            header_table = Table(
                header_table_data, 
                colWidths=[printable_width * 0.25, printable_width * 0.75]
            )
            header_table.setStyle(TableStyle([
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('LEFTPADDING', (1, 0), (1, 0), 5),
            ]))
            story.append(header_table)
            story.append(Spacer(1, 4 * mm))

            # Customer Info
            main_partner = order.partner_id
            ship_partner = order.partner_shipping_id or main_partner
            cust_code = getattr(main_partner, 'customer_code', False) or main_partner.ref or str(main_partner.id)

            cust_id_text = f"Customer ID &nbsp;&nbsp;<b>{cust_code}</b>"
            story.append(Paragraph(cust_id_text, normal_style))
            story.append(Spacer(1, 2 * mm))

            addr1 = ", ".join([p for p in [ship_partner.street, ship_partner.street2] if p])
            addr2 = ", ".join([p for p in [ship_partner.city, ship_partner.zip] if p])

            cust_table_data = [
                [
                    Paragraph(f"<b>{main_partner.name or ''}</b>", bold_11),
                    Paragraph("Deliver To:", normal_style),
                    Paragraph(f"<b>{addr1}</b>", bold_11)
                ],
                [
                    "",
                    "",
                    Paragraph(f"<b>{addr2}</b>", bold_11) if addr2 else ""
                ]
            ]
            cust_table = Table(cust_table_data, colWidths=[printable_width * 0.42, printable_width * 0.15, printable_width * 0.43])
            cust_table.setStyle(TableStyle([
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('SPAN', (0, 0), (0, 1)),
            ]))
            story.append(cust_table)
            story.append(Spacer(1, 3 * mm))

            # Divider Line
            d = Drawing(printable_width, 1)
            d.add(Line(0, 0, printable_width, 0, strokeWidth=1, strokeColor=colors.black))
            story.append(d)
            story.append(Spacer(1, 2 * mm))

            # Categories
            cat_dict = {}
            for line in lines_data:
                c_upper = line['categ_name'].upper()
                if 'FROZEN' in c_upper or 'FREEZE' in c_upper or line['use_frozen']:
                    cat_key = 'FROZEN'
                    priority = 1
                elif 'FRESH' in c_upper or 'CHILLED' in c_upper or line['use_fresh']:
                    cat_key = 'FRESH'
                    priority = 2
                else:
                    cat_key = c_upper or 'FRESH'
                    priority = 3 if c_upper else 2

                if cat_key not in cat_dict:
                    cat_dict[cat_key] = {'priority': priority, 'lines': []}
                cat_dict[cat_key]['lines'].append(line)

            sorted_cats = sorted(cat_dict.items(), key=lambda c: (c[1]['priority'], c[0]))

            for cat_name, cat_val in sorted_cats:
                cat_elements = []
                cat_elements.append(Paragraph(cat_name, cat_style))
                
                d_cat = Drawing(printable_width, 1)
                d_cat.add(Line(0, 0, printable_width, 0, strokeWidth=1, strokeColor=colors.black))
                cat_elements.append(d_cat)
                cat_elements.append(Spacer(1, 1 * mm))

                table_rows = []
                for l in cat_val['lines']:
                    item_name = l['product_name'] + (f" {l['note']}" if l['note'] else '')
                    table_rows.append([
                        Paragraph(str(l['qty']), normal_style),
                        Paragraph("X", normal_style),
                        Paragraph(item_name, normal_style)
                    ])

                items_table = Table(table_rows, colWidths=[printable_width * 0.06, printable_width * 0.06, printable_width * 0.88])
                items_table.setStyle(TableStyle([
                    ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 1),
                    ('TOPPADDING', (0, 0), (-1, -1), 1),
                ]))
                cat_elements.append(items_table)
                cat_elements.append(Spacer(1, 1 * mm))
                cat_elements.append(d_cat)
                cat_elements.append(Spacer(1, 3 * mm))

                story.append(KeepTogether(cat_elements))

            if idx < total_orders - 1:
                story.append(PageBreak())

        # Build PDF using NumberedCanvas for exact 'Page X of Y' rendering
        doc.build(story, canvasmaker=NumberedCanvas)

        pdf_value = buffer.getvalue()
        buffer.close()
        return pdf_value

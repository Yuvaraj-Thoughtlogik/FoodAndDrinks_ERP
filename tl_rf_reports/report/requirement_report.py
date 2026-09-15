# -*- coding: utf-8 -*-
import datetime
import io
import math
from xml.sax.saxutils import escape as xml_escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from odoo import api, fields, models, _


def _format_qty(val):
    if val is None:
        return '0'
    formatted = f"{val:.3f}".rstrip('0').rstrip('.')
    return formatted if formatted else '0'


class ReportRequirement(models.AbstractModel):
    _name = 'report.tl_rf_reports.report_requirement'
    _description = 'Requirement Report Generator'

    @api.model
    def _add_requirement_entry(self, categories_map, wizard, product, qty, d_date_str,
                                delivery_date_from_str, delivery_date_to_str):
        """Consolidate one (stock item, qty, delivery date) entry into categories_map.

        This is used both for products that have no BOM (reported as-is) and for BOM
        components (reported in place of the finished product they belong to). Calling
        this multiple times for the same product/component - whether it comes from
        different Sale Orders, or as a component of two different BOM'd products - will
        automatically sum into a single consolidated line rather than duplicating it.
        """
        categ = product.categ_id
        categ_key = categ.id if categ else 0
        categ_name = (categ.name or _('Uncategorized')).strip() if categ else _('Uncategorized')

        if categ_key not in categories_map:
            if wizard.delivery_channel == 'courier':
                cat_title = f"Courier {categ_name} Requirements"
            else:
                cat_title = f"{categ_name} Total Between {delivery_date_from_str} and {delivery_date_to_str}"

            categories_map[categ_key] = {
                'categ_id': categ_key,
                'categ_name': categ_name,
                'title': cat_title,
                'products': {},
                'total_qty': 0.0,
            }

        prod_key = product.id
        if prod_key not in categories_map[categ_key]['products']:
            categories_map[categ_key]['products'][prod_key] = {
                'product_id': prod_key,
                'product_name': product.name or product.display_name,
                'product_code': product.default_code or '',
                'dates_map': {},
                'total_qty': 0.0,
            }

        prod_item = categories_map[categ_key]['products'][prod_key]
        if d_date_str not in prod_item['dates_map']:
            prod_item['dates_map'][d_date_str] = 0.0
        prod_item['dates_map'][d_date_str] += qty
        prod_item['total_qty'] += qty

        categories_map[categ_key]['total_qty'] += qty

    @api.model
    def _get_report_values(self, docids, data=None):
        docs = self.env['requirement.report.wizard'].browse(docids)

        report_results = []
        for wizard in docs:
            # Format display dates
            delivery_date_from_str = wizard.delivery_date_from.strftime('%d/%m/%Y') if wizard.delivery_date_from else ''
            delivery_date_to_str = wizard.delivery_date_to.strftime('%d/%m/%Y') if wizard.delivery_date_to else ''

            # Calculate packing dates (1 day before delivery date for courier)
            packing_date_from = (wizard.delivery_date_from - datetime.timedelta(days=1)) if wizard.delivery_date_from else False
            packing_date_to = (wizard.delivery_date_to - datetime.timedelta(days=1)) if wizard.delivery_date_to else False
            packing_date_from_str = packing_date_from.strftime('%d/%m/%Y') if packing_date_from else delivery_date_from_str
            packing_date_to_str = packing_date_to.strftime('%d/%m/%Y') if packing_date_to else delivery_date_to_str

            # Current timestamp in user timezone for footer
            current_dt = fields.Datetime.context_timestamp(self, fields.Datetime.now())
            printed_at_str = current_dt.strftime('%d/%m/%Y %H:%M:%S')

            if wizard.delivery_channel == 'courier':
                footer_date_str = packing_date_from.strftime('%d %B %Y') if packing_date_from else current_dt.strftime('%d %B %Y')
            else:
                footer_date_str = current_dt.strftime('%d %B %Y')

            # Fetch matching order lines - reuses the wizard's own domain
            # builder (also used by its search_count validation) instead of
            # duplicating the domain here, so the two stay in sync.
            domain = wizard._get_line_domain()
            lines = self.env['sale.order.line'].search(domain, order='order_id, id asc')

            # Preload BOMs for every product found on the matching lines in a single call.
            # _bom_find correctly resolves variant-specific vs. template-level BOMs and
            # simply won't have an entry (or maps to a falsy value) for products with no BOM.
            all_products = lines.mapped('product_id')
            boms_by_product = self.env['mrp.bom']._bom_find(products=all_products) if all_products else {}

            # Group by Category -> Product -> Delivery Date
            categories_map = {}
            grand_total_qty = 0.0

            for line in lines:
                product = line.product_id
                if not product:
                    continue

                # Delivery date for this line
                d_date = line.order_id.delivery_date or wizard.delivery_date_from
                d_date_str = d_date.strftime('%d/%m/%Y') if d_date else delivery_date_from_str

                qty = line.product_uom_qty
                bom = boms_by_product.get(product)

                if bom:
                    # Product has a BOM: explode into its components, scaled to the
                    # ordered quantity, and report the components instead of the
                    # finished product itself (the finished product is never added here).
                    bom_batch_qty = bom.product_qty or 1.0
                    for bom_line in bom.bom_line_ids:
                        component = bom_line.product_id
                        if not component:
                            continue
                        component_qty = (bom_line.product_qty / bom_batch_qty) * qty
                        if not component_qty:
                            continue
                        self._add_requirement_entry(
                            categories_map, wizard, component, component_qty, d_date_str,
                            delivery_date_from_str, delivery_date_to_str,
                        )
                        grand_total_qty += component_qty
                else:
                    # No BOM: report the product itself, exactly as before.
                    self._add_requirement_entry(
                        categories_map, wizard, product, qty, d_date_str,
                        delivery_date_from_str, delivery_date_to_str,
                    )
                    grand_total_qty += qty

            # Format category pages and split products into 2 columns (for Regal Van)
            category_pages = []
            MAX_ROWS_PER_COL = 26

            for c_key, c_val in sorted(categories_map.items(), key=lambda item: item[1]['categ_name']):
                prod_list = []
                for p_key, p_val in sorted(c_val['products'].items(), key=lambda item: item[1]['product_name']):
                    date_entries = []
                    for d_str, d_qty in sorted(p_val['dates_map'].items(), key=lambda d: d[0]):
                        date_entries.append({
                            'delivery_date_str': d_str,
                            'qty': d_qty,
                            'formatted_qty': _format_qty(d_qty),
                        })

                    prod_list.append({
                        'product_id': p_val['product_id'],
                        'product_name': p_val['product_name'],
                        'product_code': p_val['product_code'],
                        'dates': date_entries,
                        'total_qty': p_val['total_qty'],
                        'formatted_total_qty': _format_qty(p_val['total_qty']),
                    })

                if prod_list:
                    if wizard.delivery_channel == 'courier':
                        # Courier: 1-column layout, paginated by max rows
                        COURIER_MAX_ROWS = 25
                        for i in range(0, len(prod_list), COURIER_MAX_ROWS):
                            chunk = prod_list[i:i + COURIER_MAX_ROWS]
                            category_pages.append({
                                'categ_id': c_val['categ_id'],
                                'categ_name': c_val['categ_name'],
                                'title': c_val['title'],
                                'products': chunk,
                                'total_qty': c_val['total_qty'],
                                'formatted_total_qty': _format_qty(c_val['total_qty']),
                            })
                    else:
                        # Regal Van: 2-column layout filling col1 completely before moving to col2
                        idx = 0
                        total_prods = len(prod_list)
                        while idx < total_prods:
                            col1 = []
                            col1_rows = 0
                            while idx < total_prods:
                                prod = prod_list[idx]
                                prod_rows = len(prod['dates']) + 1
                                if col1 and (col1_rows + prod_rows > MAX_ROWS_PER_COL):
                                    break
                                col1.append(prod)
                                col1_rows += prod_rows
                                idx += 1

                            col2 = []
                            col2_rows = 0
                            while idx < total_prods:
                                prod = prod_list[idx]
                                prod_rows = len(prod['dates']) + 1
                                if col2 and (col2_rows + prod_rows > MAX_ROWS_PER_COL):
                                    break
                                col2.append(prod)
                                col2_rows += prod_rows
                                idx += 1

                            category_pages.append({
                                'categ_id': c_val['categ_id'],
                                'categ_name': c_val['categ_name'],
                                'title': c_val['title'],
                                'products': col1 + col2,
                                'col1': col1,
                                'col2': col2,
                                'total_qty': c_val['total_qty'],
                                'formatted_total_qty': _format_qty(c_val['total_qty']),
                            })

            report_results.append({
                'wizard': wizard,
                'delivery_channel': wizard.delivery_channel,
                'delivery_date_from_str': delivery_date_from_str,
                'delivery_date_to_str': delivery_date_to_str,
                'packing_date_from_str': packing_date_from_str,
                'packing_date_to_str': packing_date_to_str,
                'footer_date_str': footer_date_str,
                'printed_at_str': printed_at_str,
                'categories': category_pages,
                'grand_total_qty': grand_total_qty,
                'formatted_grand_total_qty': _format_qty(grand_total_qty),
            })

        return {
            'doc_ids': docids,
            'doc_model': 'requirement.report.wizard',
            'docs': docs,
            'report_results': report_results,
        }

    # ------------------------------------------------------------------
    # Fast path: builds the PDF directly with ReportLab instead of going
    # through QWeb + wkhtmltopdf. This deliberately reuses _get_report_values()
    # above (which now also explodes BOM components, same as the Prediction
    # Report Wizard) to compute the data, so unlike the Delivery Note Round
    # reports there was no performance reason to duplicate the data prep;
    # only the rendering needed to change. Handles the Regal Van (landscape,
    # 2-column) layout. See ReportRequirementCourier.generate_pdf() below
    # for the Courier (portrait, 1-column) layout, which shares this same
    # data prep.
    # ------------------------------------------------------------------
    def generate_pdf(self, wizard):
        """Returns the finished PDF (bytes) for one Requirement Report wizard
        (Regal Van layout), or None when there is nothing to print."""
        values = self._get_report_values(wizard.ids)
        report_results = values.get('report_results') or []
        if not report_results or not report_results[0].get('categories'):
            return None
        res = report_results[0]

        buffer = io.BytesIO()
        page_size = landscape(A4)
        doc = SimpleDocTemplate(
            buffer, pagesize=page_size,
            leftMargin=12 * mm, rightMargin=12 * mm, topMargin=12 * mm, bottomMargin=18 * mm,
        )
        printable_width = page_size[0] - (24 * mm)

        title_style = ParagraphStyle(
            'ReqVanTitle', fontName='Helvetica-Bold', fontSize=13, leading=16,
        )
        col_header_style = ParagraphStyle(
            'ReqVanColHeader', fontName='Helvetica-Bold', fontSize=9.5, leading=11,
        )
        col_header_right_style = ParagraphStyle(
            'ReqVanColHeaderRight', parent=col_header_style, alignment=2,
        )
        data_style = ParagraphStyle('ReqVanData', fontName='Helvetica', fontSize=8.5, leading=10)
        data_right_style = ParagraphStyle('ReqVanDataRight', parent=data_style, alignment=2)
        subtotal_label_style = ParagraphStyle(
            'ReqVanSubtotalLabel', fontName='Helvetica-Bold', fontSize=8.5, leading=10, alignment=2,
        )
        subtotal_value_style = ParagraphStyle(
            'ReqVanSubtotalValue', parent=subtotal_label_style,
        )

        story = []
        for idx, cat_page in enumerate(res['categories']):
            if idx:
                story.append(PageBreak())

            title_table = Table(
                [[Paragraph(xml_escape(cat_page['title']), title_style)]], colWidths=[printable_width],
            )
            title_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#f0f0f0')),
                ('BOX', (0, 0), (-1, -1), 1, colors.HexColor('#dddddd')),
                ('LEFTPADDING', (0, 0), (-1, -1), 8),
                ('TOPPADDING', (0, 0), (-1, -1), 5),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
            ]))
            story.append(title_table)
            story.append(Spacer(1, 4 * mm))

            col_width = printable_width * 0.485
            col1_flowable = self._build_van_column(
                cat_page.get('col1') or [], col_width, col_header_style, col_header_right_style,
                data_style, data_right_style, subtotal_label_style, subtotal_value_style,
            )
            col2_flowable = self._build_van_column(
                cat_page.get('col2') or [], col_width, col_header_style, col_header_right_style,
                data_style, data_right_style, subtotal_label_style, subtotal_value_style,
            )

            outer = Table(
                [[col1_flowable, col2_flowable]],
                colWidths=[col_width, printable_width - col_width],
            )
            outer.setStyle(TableStyle([
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('LEFTPADDING', (0, 0), (-1, -1), 0),
                ('RIGHTPADDING', (0, 0), (-1, -1), 0),
            ]))
            story.append(outer)

        printed_at_text = xml_escape(res.get('printed_at_str', ''))

        def _draw_footer(canvas_obj, doc_obj):
            canvas_obj.saveState()
            footer_style = ParagraphStyle(
                'ReqVanFooter', fontName='Helvetica', fontSize=8.5, leading=10,
                textColor=colors.HexColor('#444444'),
            )
            p = Paragraph(f"Printed at: {printed_at_text}", footer_style)
            p.wrap(printable_width, 8 * mm)
            p.drawOn(canvas_obj, 12 * mm, 10 * mm)
            canvas_obj.restoreState()

        doc.build(story, onFirstPage=_draw_footer, onLaterPages=_draw_footer)
        pdf_value = buffer.getvalue()
        buffer.close()
        return pdf_value

    def _build_van_column(
        self, products, col_width, header_style, header_right_style,
        data_style, data_right_style, subtotal_label_style, subtotal_value_style,
    ):
        """One 'Del Date / Stock Item / Total Qty' column of the Regal Van
        layout: a header row, then per product a row per delivery date plus a
        bold subtotal row - mirrors the col1/col2 divs of the old QWeb
        template. Returns '' (renders blank) when the column has no products,
        e.g. the right-hand column on a page with an odd number of products."""
        if not products:
            return ''

        date_col = col_width * 0.26
        name_col = col_width * 0.54
        qty_col = col_width - date_col - name_col

        rows = [[
            Paragraph("Del Date", header_style),
            Paragraph("Stock Item", header_style),
            Paragraph("Total Qty", header_right_style),
        ]]
        for prod in products:
            for d_entry in prod['dates']:
                rows.append([
                    Paragraph(xml_escape(d_entry['delivery_date_str']), data_style),
                    Paragraph(xml_escape(prod['product_name']), data_style),
                    Paragraph(xml_escape(d_entry['formatted_qty']), data_right_style),
                ])
            rows.append([
                '',
                Paragraph("Total", subtotal_label_style),
                Paragraph(xml_escape(prod['formatted_total_qty']), subtotal_value_style),
            ])

        table = Table(rows, colWidths=[date_col, name_col, qty_col])
        table.setStyle(TableStyle([
            ('LINEBELOW', (0, 0), (-1, 0), 1.5, colors.black),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('TOPPADDING', (0, 0), (-1, -1), 1.5),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 1.5),
            ('LEFTPADDING', (0, 0), (-1, -1), 0),
            ('RIGHTPADDING', (0, 0), (-1, -1), 4),
        ]))
        return table


class ReportRequirementCourier(models.AbstractModel):
    _name = 'report.tl_rf_reports.report_requirement_courier'
    _description = 'Courier Requirement Report Generator'

    @api.model
    def _get_report_values(self, docids, data=None):
        return self.env['report.tl_rf_reports.report_requirement']._get_report_values(docids, data=data)

    # ------------------------------------------------------------------
    # Fast path: Courier (portrait, 1-column) layout. Shares the exact same
    # data prep as the Regal Van report above (see generate_pdf() there for
    # why _get_report_values() is reused as-is rather than rewritten).
    # ------------------------------------------------------------------
    def generate_pdf(self, wizard):
        """Returns the finished PDF (bytes) for one Requirement Report wizard
        (Courier layout), or None when there is nothing to print."""
        report_requirement = self.env['report.tl_rf_reports.report_requirement']
        values = report_requirement._get_report_values(wizard.ids)
        report_results = values.get('report_results') or []
        if not report_results or not report_results[0].get('categories'):
            return None
        res = report_results[0]

        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer, pagesize=A4,
            leftMargin=12 * mm, rightMargin=12 * mm, topMargin=12 * mm, bottomMargin=18 * mm,
        )
        printable_width = A4[0] - (24 * mm)

        title_style = ParagraphStyle('ReqCourierTitle', fontName='Helvetica-Bold', fontSize=17, leading=20)
        packing_style = ParagraphStyle('ReqCourierPacking', fontName='Helvetica', fontSize=9, leading=12)
        col_header_style = ParagraphStyle('ReqCourierColHeader', fontName='Helvetica-Bold', fontSize=11, leading=13)
        qty_style = ParagraphStyle('ReqCourierQty', fontName='Helvetica', fontSize=10.5, leading=13, alignment=2)
        x_style = ParagraphStyle('ReqCourierX', fontName='Helvetica', fontSize=10.5, leading=13, alignment=1)
        name_style = ParagraphStyle('ReqCourierName', fontName='Helvetica', fontSize=10.5, leading=13)

        packing_from = xml_escape(res.get('packing_date_from_str', ''))
        packing_to = xml_escape(res.get('packing_date_to_str', ''))

        story = []
        for idx, cat_page in enumerate(res['categories']):
            if idx:
                story.append(PageBreak())

            header_table = Table(
                [[
                    Paragraph(xml_escape(cat_page['title']), title_style),
                    Paragraph(f"For Packing between {packing_from} and<br/>{packing_to}", packing_style),
                ]],
                colWidths=[printable_width * 0.62, printable_width * 0.38],
            )
            header_table.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP')]))
            story.append(header_table)
            story.append(Spacer(1, 3 * mm))

            rows = [[
                Paragraph("Total Kg", col_header_style), '',
                Paragraph("Stock Name", col_header_style),
            ]]
            for prod in cat_page['products']:
                rows.append([
                    Paragraph(xml_escape(prod['formatted_total_qty']), qty_style),
                    Paragraph("x", x_style),
                    Paragraph(xml_escape(prod['product_name']), name_style),
                ])
            table = Table(
                rows, colWidths=[printable_width * 0.13, printable_width * 0.07, printable_width * 0.80],
                repeatRows=1,
            )
            table.setStyle(TableStyle([
                ('LINEBELOW', (0, 0), (-1, 0), 2, colors.black),
                ('LINEBELOW', (0, 1), (-1, -1), 0.5, colors.black),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('TOPPADDING', (0, 0), (-1, -1), 4),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ]))
            story.append(table)

        footer_text = xml_escape(res.get('footer_date_str', ''))

        def _draw_footer(canvas_obj, doc_obj):
            canvas_obj.saveState()
            footer_style = ParagraphStyle(
                'ReqCourierFooter', fontName='Helvetica', fontSize=9, leading=11, textColor=colors.black,
            )
            p = Paragraph(footer_text, footer_style)
            p.wrap(printable_width, 8 * mm)
            p.drawOn(canvas_obj, 12 * mm, 10 * mm)
            canvas_obj.restoreState()

        doc.build(story, onFirstPage=_draw_footer, onLaterPages=_draw_footer)
        pdf_value = buffer.getvalue()
        buffer.close()
        return pdf_value

# -*- coding: utf-8 -*-
import io
from xml.sax.saxutils import escape as xml_escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from odoo import api, fields, models, _


def _format_qty(val):
    if val is None:
        return '0'
    formatted = f"{val:.3f}".rstrip('0').rstrip('.')
    return formatted if formatted else '0'


class ReportPrediction(models.AbstractModel):
    _name = 'report.tl_rf_reports.report_prediction'
    _description = 'Prediction Report Generator'

    # ------------------------------------------------------------------
    # BOM helpers
    # ------------------------------------------------------------------
    def _find_bom(self, product):
        """Return the applicable BOM for a product (variant-specific first,
        falling back to a template-level BOM), or an empty recordset if the
        product has no BOM. Both 'Manufacture this product' and 'Kit'
        (phantom) BOM types are considered a BOM for this report.
        """
        BomModel = self.env['mrp.bom']
        company_ids = [self.env.company.id, False]

        bom = BomModel.search([
            ('product_id', '=', product.id),
            ('company_id', 'in', company_ids),
        ], limit=1, order='sequence, id')

        if not bom:
            bom = BomModel.search([
                ('product_tmpl_id', '=', product.product_tmpl_id.id),
                ('product_id', '=', False),
                ('company_id', 'in', company_ids),
            ], limit=1, order='sequence, id')

        return bom

    def _explode_bom(self, product, qty, bom_cache):
        """Given a sold product and its ordered qty, return a list of
        (reporting_product, reporting_qty) tuples to feed into the report.

        - If the product has no BOM: returns [(product, qty)] unchanged.
        - If the product has a BOM (manufacture or kit): returns one entry
          per BOM component, with the component qty scaled to the ordered
          qty of the finished product. The finished product itself is
          NOT included in this case (single-level explosion only - a
          component that itself has a BOM is not exploded further).
        """
        if product.id not in bom_cache:
            bom_cache[product.id] = self._find_bom(product)
        bom = bom_cache[product.id]

        if not bom:
            return [(product, qty)]

        # Qty (in the BOM's own UoM) that the ordered qty corresponds to.
        finished_uom = bom.product_uom_id or product.uom_id
        order_uom = product.uom_id
        try:
            qty_in_bom_uom = order_uom._compute_quantity(qty, finished_uom)
        except Exception:
            qty_in_bom_uom = qty

        bom_produced_qty = bom.product_qty or 1.0

        result = []
        for bom_line in bom.bom_line_ids:
            component = bom_line.product_id
            if not component:
                continue
            # Skip BOM lines that don't apply to this specific variant
            # (attribute-based BOM lines), when the method is available.
            if hasattr(bom_line, '_skip_bom_line') and bom_line._skip_bom_line(product):
                continue

            line_qty = bom_line.product_qty
            if bom_line.product_uom_id and bom_line.product_uom_id != component.uom_id:
                try:
                    line_qty = bom_line.product_uom_id._compute_quantity(line_qty, component.uom_id)
                except Exception:
                    line_qty = bom_line.product_qty

            qty_per_unit = (line_qty / bom_produced_qty) if bom_produced_qty else 0.0
            comp_qty = qty_per_unit * qty_in_bom_uom
            if comp_qty:
                result.append((component, comp_qty))

        # Safety net: a BOM with no usable lines should not make the
        # ordered qty disappear from the report.
        if not result:
            return [(product, qty)]

        return result

    @api.model
    def _get_report_values(self, docids, data=None):
        docs = self.env['prediction.report.wizard'].browse(docids)

        report_results = []
        for wizard in docs:
            # Format display dates
            delivery_date_from_str = wizard.delivery_date_from.strftime('%d/%m/%Y') if wizard.delivery_date_from else ''
            delivery_date_to_str = wizard.delivery_date_to.strftime('%d/%m/%Y') if wizard.delivery_date_to else ''
            date_range_str = f"{delivery_date_from_str} to {delivery_date_to_str}"

            # Footer date display: e.g. "20 August 2026"
            footer_date_str = wizard.delivery_date_from.strftime('%d %B %Y') if wizard.delivery_date_from else ''

            # Fetch matching order lines
            domain = wizard._get_line_domain()
            lines = self.env['sale.order.line'].search(domain, order='product_id, id asc')

            # Group by Stock Item (Product, or BOM component if the product
            # has a BOM) -> Delivery Date -> Depot
            products_map = {}
            grand_total_qty = 0.0
            bom_cache = {}

            for line in lines:
                product = line.product_id
                if not product:
                    continue

                qty = line.product_uom_qty or 0.0

                # Resolve this line to the item(s) that should actually be
                # reported: the product itself (no BOM) or its BOM
                # components (BOM available), with qty scaled accordingly.
                reporting_items = self._explode_bom(product, qty, bom_cache)
                if not reporting_items:
                    continue

                # Delivery date for this line
                d_date = line.order_id.delivery_date or line.delivery_date or wizard.delivery_date_from
                if d_date:
                    date_key = d_date.strftime('%Y-%m-%d')
                    date_display = d_date.strftime('%d %B %Y')
                else:
                    date_key = '9999-99-99'
                    date_display = ''

                # Depot / Delivery Channel
                if wizard.delivery_channel == 'courier' or getattr(line.order_id, 'delivery_channel', False) == 'courier':
                    depot_name = _('Courier')
                    depot_key = 'courier'
                else:
                    depot = line.depot_id or (line.order_id.batch_id.depot_id if hasattr(line.order_id, 'batch_id') and line.order_id.batch_id else False) or line.order_id.warehouse_id
                    depot_name = (depot.name or _('Grimsby')).strip() if depot else _('Grimsby')
                    depot_key = depot.id if depot else 0

                for item_product, item_qty in reporting_items:
                    prod_key = item_product.id
                    prod_name = (item_product.name or item_product.display_name or '').strip()

                    if prod_key not in products_map:
                        products_map[prod_key] = {
                            'product_id': prod_key,
                            'product_name': prod_name,
                            'dates_map': {},
                            'total_qty': 0.0,
                        }

                    prod_item = products_map[prod_key]
                    if date_key not in prod_item['dates_map']:
                        prod_item['dates_map'][date_key] = {
                            'date_key': date_key,
                            'date_display': date_display,
                            'depots_map': {},
                        }

                    date_item = prod_item['dates_map'][date_key]
                    if depot_key not in date_item['depots_map']:
                        date_item['depots_map'][depot_key] = {
                            'depot_key': depot_key,
                            'depot_name': depot_name,
                            'qty': 0.0,
                        }

                    date_item['depots_map'][depot_key]['qty'] += item_qty
                    prod_item['total_qty'] += item_qty
                    grand_total_qty += item_qty

            # Format products and their sub-rows
            products_list = []
            for prod_key, prod_data in sorted(products_map.items(), key=lambda item: item[1]['product_name'].lower()):
                rows = []
                for date_key in sorted(prod_data['dates_map'].keys()):
                    date_data = prod_data['dates_map'][date_key]
                    is_first_depot = True
                    for depot_key, depot_data in sorted(date_data['depots_map'].items(), key=lambda d: d[1]['depot_name'].lower()):
                        rows.append({
                            'is_first_date_row': is_first_depot,
                            'delivery_date_str': date_data['date_display'] if is_first_depot else '',
                            'depot_name': depot_data['depot_name'],
                            'qty': depot_data['qty'],
                            'formatted_qty': _format_qty(depot_data['qty']),
                        })
                        is_first_depot = False

                if rows:
                    products_list.append({
                        'product_id': prod_key,
                        'product_name': prod_data['product_name'],
                        'rows': rows,
                        'total_qty': prod_data['total_qty'],
                        'formatted_total_qty': _format_qty(prod_data['total_qty']),
                    })

            report_results.append({
                'wizard': wizard,
                'delivery_channel': wizard.delivery_channel,
                'delivery_date_from_str': delivery_date_from_str,
                'delivery_date_to_str': delivery_date_to_str,
                'date_range_str': date_range_str,
                'footer_date_str': footer_date_str,
                'products': products_list,
                'grand_total_qty': grand_total_qty,
                'formatted_grand_total_qty': _format_qty(grand_total_qty),
            })

        return {
            'doc_ids': docids,
            'doc_model': 'prediction.report.wizard',
            'docs': docs,
            'report_results': report_results,
        }

    # ------------------------------------------------------------------
    # Fast path: builds the PDF directly with ReportLab, in one pass, in
    # memory. No wkhtmltopdf subprocess, no QWeb rendering. This is a
    # standalone data-fetch for a single wizard (the QWeb path above stays
    # untouched, still used only by the dead report actions kept for
    # parity) - the grouping/BOM-explosion logic here mirrors the per-wizard
    # body of _get_report_values above, so that method can be left
    # completely alone. Unlike _get_report_values, this uses plain ORM
    # .search() + recordset for-loops (no raw SQL): translatable fields are
    # read via dot-notation so the field descriptor handles jsonb vs. plain
    # varchar columns correctly, and BOM explosion is delegated to
    # _find_bom()/_explode_bom() above, cached per product via bom_cache so
    # each product's BOM is looked up at most once even if it appears on
    # multiple order lines.
    # ------------------------------------------------------------------
    def _build_prediction_domain(self, wizard):
        """Sale Order Line search domain shared by every Prediction Report
        variant (main + courier): delivery date range, delivery channel,
        optional depot filter (non-courier only) and optional product
        category filter. Extracted so the courier report's own data-fetch
        can reuse exactly the same filtering rules instead of duplicating
        them and risking the two drifting apart.
        """
        domain = [
            ('order_id.state', 'in', ('sale', 'done')),
            ('order_id.delivery_date', '>=', wizard.delivery_date_from),
            ('order_id.delivery_date', '<=', wizard.delivery_date_to),
            ('display_type', '=', False),
            ('product_id', '!=', False),
            ('product_uom_qty', '>', 0),
        ]

        if wizard.delivery_channel == 'courier':
            domain.append(('order_id.delivery_channel', '=', 'courier'))
        else:
            domain.append(('order_id.delivery_channel', 'in', ('regal_van', False)))
            if wizard.depot_ids:
                depot_ids = wizard.depot_ids.ids
                # sol.depot_id IN depot_ids OR (sol.depot_id IS NULL AND so.warehouse_id IN depot_ids)
                domain += [
                    '|', ('depot_id', 'in', depot_ids),
                    '&', ('depot_id', '=', False), ('order_id.warehouse_id', 'in', depot_ids),
                ]

        if wizard.categ_ids:
            domain.append(('categ_id', 'in', wizard.categ_ids.ids))

        return domain

    def _fetch_prediction_data(self, wizard):
        """Same grouping/BOM-explosion logic as the per-wizard body of
        _get_report_values(), for a single wizard record. Returns a dict with
        the same shape as one 'report_results' entry (minus 'wizard')."""
        delivery_date_from_str = wizard.delivery_date_from.strftime('%d/%m/%Y') if wizard.delivery_date_from else ''
        delivery_date_to_str = wizard.delivery_date_to.strftime('%d/%m/%Y') if wizard.delivery_date_to else ''
        date_range_str = f"{delivery_date_from_str} to {delivery_date_to_str}"
        footer_date_str = wizard.delivery_date_from.strftime('%d %B %Y') if wizard.delivery_date_from else ''

        empty_result = {
            'delivery_channel': wizard.delivery_channel,
            'delivery_date_from_str': delivery_date_from_str,
            'delivery_date_to_str': delivery_date_to_str,
            'date_range_str': date_range_str,
            'footer_date_str': footer_date_str,
            'products': [],
            'grand_total_qty': 0.0,
            'formatted_grand_total_qty': '0',
        }

        domain = self._build_prediction_domain(wizard)
        order_lines = self.env['sale.order.line'].search(domain, order='id')

        if not order_lines:
            return empty_result

        bom_cache = {}
        products_map = {}
        grand_total_qty = 0.0

        for line in order_lines:
            qty = line.product_uom_qty
            product = line.product_id

            # delivery_date on sale.order.line is a stored related field
            # mirroring order_id.delivery_date, so this reproduces the old
            # COALESCE(so.delivery_date, sol.delivery_date) fallback.
            d_date = line.delivery_date or wizard.delivery_date_from
            if d_date:
                date_key = d_date.strftime('%Y-%m-%d')
                date_display = d_date.strftime('%d %B %Y')
            else:
                date_key = '9999-99-99'
                date_display = ''

            if wizard.delivery_channel == 'courier' or line.delivery_channel == 'courier':
                depot_name = _('Courier')
                depot_key = 'courier'
            else:
                depot = line.depot_id or line.order_id.warehouse_id
                depot_name = (depot.name or _('Grimsby')).strip()
                depot_key = depot.id or 0

            for item_product, item_qty in self._explode_bom(product, qty, bom_cache):
                if not item_qty:
                    continue
                item_pid = item_product.id
                item_name = (item_product.name or '').strip()

                if item_pid not in products_map:
                    products_map[item_pid] = {
                        'product_id': item_pid,
                        'product_name': item_name,
                        'dates_map': {},
                        'total_qty': 0.0,
                    }

                prod_item = products_map[item_pid]
                if date_key not in prod_item['dates_map']:
                    prod_item['dates_map'][date_key] = {
                        'date_key': date_key,
                        'date_display': date_display,
                        'depots_map': {},
                    }

                date_item = prod_item['dates_map'][date_key]
                if depot_key not in date_item['depots_map']:
                    date_item['depots_map'][depot_key] = {
                        'depot_key': depot_key,
                        'depot_name': depot_name,
                        'qty': 0.0,
                    }

                date_item['depots_map'][depot_key]['qty'] += item_qty
                prod_item['total_qty'] += item_qty
                grand_total_qty += item_qty

        products_list = []
        for prod_key, prod_data in sorted(products_map.items(), key=lambda item: item[1]['product_name'].lower()):
            rows_list = []
            for date_key in sorted(prod_data['dates_map'].keys()):
                date_data = prod_data['dates_map'][date_key]
                is_first_depot = True
                for depot_key, depot_data in sorted(date_data['depots_map'].items(), key=lambda d: d[1]['depot_name'].lower()):
                    rows_list.append({
                        'is_first_date_row': is_first_depot,
                        'delivery_date_str': date_data['date_display'] if is_first_depot else '',
                        'depot_name': depot_data['depot_name'],
                        'qty': depot_data['qty'],
                        'formatted_qty': _format_qty(depot_data['qty']),
                    })
                    is_first_depot = False

            if rows_list:
                products_list.append({
                    'product_id': prod_key,
                    'product_name': prod_data['product_name'],
                    'rows': rows_list,
                    'total_qty': prod_data['total_qty'],
                    'formatted_total_qty': _format_qty(prod_data['total_qty']),
                })

        empty_result['products'] = products_list
        empty_result['grand_total_qty'] = grand_total_qty
        empty_result['formatted_grand_total_qty'] = _format_qty(grand_total_qty)
        return empty_result

    NAVY = colors.HexColor('#002060')
    GREY = colors.HexColor('#555555')

    def _draw_prediction_footer(self, canvas_obj, doc_obj, footer_date_str):
        """Draws the (constant, per-document) footer date at the bottom-left
        of every page - the only footer content the old QWeb template
        actually rendered (the "Page X of Y" markup there was commented
        out), so there is no need for a two-pass canvas here: nothing drawn
        depends on the eventual total page count."""
        canvas_obj.saveState()
        margin = 12 * mm
        footer_style = ParagraphStyle(
            'PredictionFooterDate', fontName='Helvetica-Oblique', fontSize=9,
            leading=11, textColor=colors.black,
        )
        footer = Paragraph(xml_escape(footer_date_str or ''), footer_style)
        _, h = footer.wrap(A4[0] - (2 * margin), 10 * mm)
        footer.drawOn(canvas_obj, margin, 8 * mm)
        canvas_obj.restoreState()

    def generate_pdf(self, wizard):
        """Returns the finished PDF (bytes) for one Prediction Report wizard
        (either delivery channel), or None when there is nothing to print."""
        data = self._fetch_prediction_data(wizard)

        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer, pagesize=A4,
            leftMargin=12 * mm, rightMargin=12 * mm, topMargin=12 * mm, bottomMargin=15 * mm,
        )
        printable_width = A4[0] - (24 * mm)

        title_style = ParagraphStyle(
            'PredictionTitle', fontName='Times-BoldItalic', fontSize=24, leading=28,
            textColor=self.NAVY, alignment=TA_CENTER,
        )
        subtitle_style = ParagraphStyle(
            'PredictionSubtitle', fontName='Times-BoldItalic', fontSize=16, leading=19,
            textColor=self.NAVY, alignment=TA_CENTER, spaceBefore=2,
        )
        empty_style = ParagraphStyle(
            'PredictionEmpty', fontName='Helvetica', fontSize=15, leading=18,
            textColor=self.GREY, alignment=TA_CENTER,
        )

        story = [
            Paragraph('<u>Prediction Report</u>', title_style),
            Paragraph(f"<u>{xml_escape(data['date_range_str'])}</u>", subtitle_style),
            Spacer(1, 6 * mm),
        ]

        products = data['products']
        if not products:
            story.append(Spacer(1, 10 * mm))
            story.append(Paragraph('No confirmed order lines found for the selected criteria.', empty_style))
        else:
            header_style_left = ParagraphStyle(
                'PredictionHeaderLeft', fontName='Helvetica-BoldOblique', fontSize=11,
                leading=13, textColor=self.NAVY, alignment=TA_LEFT,
            )
            header_style_right = ParagraphStyle(
                'PredictionHeaderRight', fontName='Helvetica-BoldOblique', fontSize=11,
                leading=13, textColor=self.NAVY, alignment=TA_RIGHT,
            )
            name_style = ParagraphStyle(
                'PredictionProductName', fontName='Helvetica-Bold', fontSize=10.5, leading=13, textColor=colors.black,
            )
            date_style = ParagraphStyle(
                'PredictionDate', fontName='Helvetica', fontSize=9.5, leading=12, textColor=colors.black,
            )
            depot_style = ParagraphStyle(
                'PredictionDepot', fontName='Helvetica', fontSize=9.5, leading=12, textColor=colors.black,
            )
            qty_style = ParagraphStyle(
                'PredictionQty', fontName='Helvetica', fontSize=9.5, leading=12, textColor=colors.black, alignment=TA_RIGHT,
            )
            total_style = ParagraphStyle(
                'PredictionTotalQty', fontName='Helvetica-Bold', fontSize=10.5, leading=13, textColor=colors.black,
                alignment=TA_RIGHT,
            )

            table_data = [[
                Paragraph('Stock Name', header_style_left),
                Paragraph('Delivery Date', header_style_left),
                Paragraph('', header_style_left),
                Paragraph('Quantity<br/>Ordered', header_style_right),
            ]]
            style_commands = [
                ('LINEBELOW', (0, 0), (-1, 0), 2, self.NAVY),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('TOPPADDING', (0, 0), (-1, -1), 3),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
                ('LEFTPADDING', (0, 0), (-1, -1), 4),
                ('RIGHTPADDING', (0, 0), (-1, -1), 4),
            ]

            row_idx = 1
            for prod in products:
                first_subrow_idx = row_idx
                for i, r in enumerate(prod['rows']):
                    name_cell = Paragraph(f"<b>{xml_escape(prod['product_name'])}</b>", name_style) if i == 0 else ''
                    date_cell = Paragraph(xml_escape(r['delivery_date_str']), date_style) if r['is_first_date_row'] else ''
                    depot_cell = Paragraph(xml_escape(r['depot_name']), depot_style)
                    qty_cell = Paragraph(xml_escape(r['formatted_qty']), qty_style)
                    table_data.append([name_cell, date_cell, depot_cell, qty_cell])
                    row_idx += 1

                style_commands.append(('LINEABOVE', (0, first_subrow_idx), (-1, first_subrow_idx), 1.5, self.NAVY))

                table_data.append(['', '', '', Paragraph(xml_escape(prod['formatted_total_qty']), total_style)])
                style_commands.append(('LINEABOVE', (0, row_idx), (-1, row_idx), 1, self.NAVY))
                style_commands.append(('LINEBELOW', (0, row_idx), (-1, row_idx), 2.5, self.NAVY))
                row_idx += 1

            col_widths = [printable_width * w for w in (0.46, 0.22, 0.16, 0.16)]
            prediction_table = Table(table_data, colWidths=col_widths, repeatRows=1)
            prediction_table.setStyle(TableStyle(style_commands))
            story.append(prediction_table)

        def _on_page(canvas_obj, doc_obj):
            self._draw_prediction_footer(canvas_obj, doc_obj, data['footer_date_str'])

        doc.build(story, onFirstPage=_on_page, onLaterPages=_on_page)
        pdf_value = buffer.getvalue()
        buffer.close()
        return pdf_value


class ReportPredictionCourier(models.AbstractModel):
    """Courier Prediction Report.

    Structurally different from the main (Regal Van / depot) report: this
    one is grouped by final reported Product/Component, and under each
    product lists one row per matching Sale Order Line - Round/Sale Order,
    Delivery Date, Stock Code and Quantity Ordered (no depot pivot, no
    date-collapsing: every row repeats its own Delivery Date).

    BOM handling here is also intentionally different from the main report:
    - Kit/Component BOM (mrp.bom type == 'phantom') -> product is replaced
      by its components, qty scaled to the Sale Order Line qty.
    - Manufacturing BOM (mrp.bom type == 'normal') -> NOT expanded; the
      finished product is displayed as-is.
    - No BOM -> the product is displayed as-is.
    """

    _name = 'report.tl_rf_reports.report_prediction_courier'
    _description = 'Courier Prediction Report Generator'

    NAVY = colors.HexColor('#002060')
    GREY = colors.HexColor('#555555')

    # ------------------------------------------------------------------
    # BOM helpers (Kit/Component BOM only - Manufacturing BOMs are
    # intentionally left un-expanded for this report)
    # ------------------------------------------------------------------
    def _find_kit_bom(self, product):
        BomModel = self.env['mrp.bom']
        company_ids = [self.env.company.id, False]

        bom = BomModel.search([
            ('product_id', '=', product.id),
            ('type', '=', 'phantom'),
            ('company_id', 'in', company_ids),
        ], limit=1, order='sequence, id')

        if not bom:
            bom = BomModel.search([
                ('product_tmpl_id', '=', product.product_tmpl_id.id),
                ('product_id', '=', False),
                ('type', '=', 'phantom'),
                ('company_id', 'in', company_ids),
            ], limit=1, order='sequence, id')

        return bom

    def _explode_kit_bom(self, product, qty, bom_cache):
        """Return [(reporting_product, reporting_qty), ...] for one Sale
        Order Line. Only Kit/Component (phantom) BOMs are expanded; a
        Manufacturing BOM or no BOM both fall through to the product as-is.
        """
        if product.id not in bom_cache:
            bom_cache[product.id] = self._find_kit_bom(product)
        bom = bom_cache[product.id]

        if not bom:
            return [(product, qty)]

        finished_uom = bom.product_uom_id or product.uom_id
        order_uom = product.uom_id
        try:
            qty_in_bom_uom = order_uom._compute_quantity(qty, finished_uom)
        except Exception:
            qty_in_bom_uom = qty

        bom_produced_qty = bom.product_qty or 1.0

        result = []
        for bom_line in bom.bom_line_ids:
            component = bom_line.product_id
            if not component:
                continue
            if hasattr(bom_line, '_skip_bom_line') and bom_line._skip_bom_line(product):
                continue

            line_qty = bom_line.product_qty
            if bom_line.product_uom_id and bom_line.product_uom_id != component.uom_id:
                try:
                    line_qty = bom_line.product_uom_id._compute_quantity(line_qty, component.uom_id)
                except Exception:
                    line_qty = bom_line.product_qty

            qty_per_unit = (line_qty / bom_produced_qty) if bom_produced_qty else 0.0
            comp_qty = qty_per_unit * qty_in_bom_uom
            if comp_qty:
                result.append((component, comp_qty))

        if not result:
            return [(product, qty)]

        return result

    # ------------------------------------------------------------------
    # QWeb data path - kept only for parity (see the main report's
    # generate_pdf/_fetch_prediction_data comments: ReportLab's
    # generate_pdf() above is what actually renders this report). It
    # reuses _fetch_prediction_data() below as its single source of truth,
    # so the QWeb template (report_prediction_courier) stays consistent
    # with the real PDF instead of drifting out of sync with it.
    # ------------------------------------------------------------------
    @api.model
    def _get_report_values(self, docids, data=None):
        docs = self.env['prediction.report.wizard'].browse(docids)

        report_results = []
        for wizard in docs:
            result = self._fetch_prediction_data(wizard)
            result['wizard'] = wizard
            report_results.append(result)

        return {
            'doc_ids': docids,
            'doc_model': 'prediction.report.wizard',
            'docs': docs,
            'report_results': report_results,
        }

    # ------------------------------------------------------------------
    # Data fetch
    # ------------------------------------------------------------------
    def _fetch_prediction_data(self, wizard):
        """Returns a dict shaped for this report's own template: one entry
        per final reported product, each holding a flat list of rows (one
        per matching Sale Order Line), not the date/depot pivot the main
        report uses.
        """
        delivery_date_from_str = wizard.delivery_date_from.strftime('%d/%m/%Y') if wizard.delivery_date_from else ''
        delivery_date_to_str = wizard.delivery_date_to.strftime('%d/%m/%Y') if wizard.delivery_date_to else ''
        date_range_str = f"{delivery_date_from_str} to {delivery_date_to_str}"

        # Actual system date the report is generated/printed - recomputed
        # every call, never a static value.
        footer_date_str = fields.Date.context_today(self).strftime('%d %B %Y')

        empty_result = {
            'delivery_channel': wizard.delivery_channel,
            'delivery_date_from_str': delivery_date_from_str,
            'delivery_date_to_str': delivery_date_to_str,
            'date_range_str': date_range_str,
            'footer_date_str': footer_date_str,
            'products': [],
            'grand_total_qty': 0.0,
            'formatted_grand_total_qty': '0',
        }

        main_report = self.env['report.tl_rf_reports.report_prediction']
        domain = main_report._build_prediction_domain(wizard)
        order_lines = self.env['sale.order.line'].search(domain, order='id')

        if not order_lines:
            return empty_result

        bom_cache = {}
        products_map = {}
        grand_total_qty = 0.0

        for line in order_lines:
            qty = line.product_uom_qty
            product = line.product_id
            order = line.order_id

            so_name = order.name or ''

            # Round: "Sale Order Number - Round Name", falling back to just
            # the Sale Order Number when no Round is assigned.
            #
            # sale.order.round_id -> round.management.round is the actual
            # "Delivery Round" (e.g. "1077-CHESH CUDDINGTON"), NOT
            # order.batch_id (round.management.batch is the scheduled
            # batch/run of a round on a given date, e.g. "100251 - Sep 15" -
            # a different thing entirely, which is what was wrongly showing
            # up here before).
            #
            # round_id.display_name is reliably "<Round Code>-<Round Name>"
            # (confirmed: "1077-CHESH CUDDINGTON"); only the Round Name
            # portion is wanted, so the leading "<code>-" is stripped off
            # rather than guessing the underlying field's technical name.
            round_obj = order.round_id if hasattr(order, 'round_id') else False
            round_name = False
            if round_obj:
                round_display = (round_obj.display_name or '').strip()
                round_name = round_display.split('-', 1)[1].strip() if '-' in round_display else round_display
            round_so_str = f"{so_name} – {round_name}" if round_name else (so_name or '-')

            # Delivery Date of the Sale Order - shown on every row (no
            # collapsing), and repeated under the Round/SO line too.
            d_date = line.delivery_date or wizard.delivery_date_from
            delivery_date_str = d_date.strftime('%d %B %Y') if d_date else ''
            round_date_str = d_date.strftime('%d/%m/%Y') if d_date else ''
            date_sort_key = d_date.strftime('%Y-%m-%d') if d_date else '9999-99-99'

            for item_product, item_qty in self._explode_kit_bom(product, qty, bom_cache):
                if not item_qty:
                    continue
                item_pid = item_product.id
                item_name = (item_product.name or item_product.display_name or '').strip()
                stock_code = item_product.default_code or ''

                if item_pid not in products_map:
                    products_map[item_pid] = {
                        'product_id': item_pid,
                        'product_name': item_name,
                        'rows': [],
                        'total_qty': 0.0,
                    }

                products_map[item_pid]['rows'].append({
                    'round_so_str': round_so_str,
                    'round_date_str': round_date_str,
                    'delivery_date_str': delivery_date_str,
                    'date_sort_key': date_sort_key,
                    'so_name': so_name,
                    'stock_code': stock_code,
                    'qty': item_qty,
                    'formatted_qty': _format_qty(item_qty),
                })
                products_map[item_pid]['total_qty'] += item_qty
                grand_total_qty += item_qty

        products_list = []
        for prod_key, prod_data in sorted(products_map.items(), key=lambda item: item[1]['product_name'].lower()):
            rows_list = sorted(prod_data['rows'], key=lambda r: (r['date_sort_key'], r['so_name']))
            products_list.append({
                'product_id': prod_key,
                'product_name': prod_data['product_name'],
                'rows': rows_list,
                'total_qty': prod_data['total_qty'],
                'formatted_total_qty': _format_qty(prod_data['total_qty']),
            })

        empty_result['products'] = products_list
        empty_result['grand_total_qty'] = grand_total_qty
        empty_result['formatted_grand_total_qty'] = _format_qty(grand_total_qty)
        return empty_result

    # ------------------------------------------------------------------
    # PDF generation (ReportLab) - this is what actually renders the
    # Courier Prediction Report; the QWeb template of the same name is
    # kept only for parity, same as the main report.
    # ------------------------------------------------------------------
    def _make_numbered_canvas(self, footer_date_str):
        """Returns a reportlab Canvas subclass that stamps a real
        "Page X of Y" (right) alongside the print date (left) on every
        page footer. Reportlab only knows the final page count once the
        whole story has been laid out, so this defers drawing each page's
        footer until save(), after every page has already been counted.
        """
        navy = self.NAVY
        margin = 12 * mm

        class _NumberedCanvas(canvas.Canvas):
            def __init__(self, *args, **kwargs):
                canvas.Canvas.__init__(self, *args, **kwargs)
                self._saved_page_states = []

            def showPage(self):
                self._saved_page_states.append(dict(self.__dict__))
                self._startPage()

            def save(self):
                total_pages = len(self._saved_page_states)
                for state in self._saved_page_states:
                    self.__dict__.update(state)
                    self._draw_footer(total_pages)
                    canvas.Canvas.showPage(self)
                canvas.Canvas.save(self)

            def _draw_footer(self, total_pages):
                self.saveState()
                self.setFont('Helvetica-Oblique', 9)
                self.setFillColor(colors.black)
                self.drawString(margin, 8 * mm, footer_date_str or '')
                self.setFont('Helvetica-BoldOblique', 9)
                self.setFillColor(navy)
                self.drawRightString(A4[0] - margin, 8 * mm, f'Page {self._pageNumber} of {total_pages}')
                self.restoreState()

        return _NumberedCanvas

    def generate_pdf(self, wizard):
        """Returns the finished PDF (bytes) for one Courier Prediction
        Report wizard, or an empty-state page when there is nothing to
        print."""
        data = self._fetch_prediction_data(wizard)

        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer, pagesize=A4,
            leftMargin=12 * mm, rightMargin=12 * mm, topMargin=12 * mm, bottomMargin=15 * mm,
        )
        printable_width = A4[0] - (24 * mm)

        title_style = ParagraphStyle(
            'CourierPredictionTitle', fontName='Times-BoldItalic', fontSize=24, leading=28,
            textColor=self.NAVY, alignment=TA_CENTER,
        )
        subtitle_style = ParagraphStyle(
            'CourierPredictionSubtitle', fontName='Times-BoldItalic', fontSize=16, leading=19,
            textColor=self.NAVY, alignment=TA_CENTER, spaceBefore=2,
        )
        empty_style = ParagraphStyle(
            'CourierPredictionEmpty', fontName='Helvetica', fontSize=15, leading=18,
            textColor=self.GREY, alignment=TA_CENTER,
        )

        story = [
            # Section 11: on-page title stays "Prediction Report" (the
            # "Courier Prediction Report" name only labels the print menu
            # action/report_file, not the printed title).
            Paragraph('<u>Prediction Report</u>', title_style),
            Paragraph(f"<u>{xml_escape(data['date_range_str'])}</u>", subtitle_style),
            Spacer(1, 6 * mm),
        ]

        products = data['products']
        if not products:
            story.append(Spacer(1, 10 * mm))
            story.append(Paragraph('No confirmed order lines found for the selected criteria.', empty_style))
        else:
            header_style_left = ParagraphStyle(
                'CourierHeaderLeft', fontName='Helvetica-BoldOblique', fontSize=10.5,
                leading=12, textColor=self.NAVY, alignment=TA_LEFT,
            )
            header_style_right = ParagraphStyle(
                'CourierHeaderRight', fontName='Helvetica-BoldOblique', fontSize=10.5,
                leading=12, textColor=self.NAVY, alignment=TA_RIGHT,
            )
            name_style = ParagraphStyle(
                'CourierProductName', fontName='Helvetica-Bold', fontSize=10.5, leading=13, textColor=colors.black,
            )
            round_style = ParagraphStyle(
                'CourierRoundSo', fontName='Helvetica', fontSize=9, leading=11.5, textColor=colors.black,
            )
            date_style = ParagraphStyle(
                'CourierDate', fontName='Helvetica', fontSize=9.5, leading=12, textColor=colors.black,
            )
            code_style = ParagraphStyle(
                'CourierStockCode', fontName='Helvetica', fontSize=9.5, leading=12, textColor=colors.black,
            )
            qty_style = ParagraphStyle(
                'CourierQty', fontName='Helvetica', fontSize=9.5, leading=12, textColor=colors.black, alignment=TA_RIGHT,
            )
            total_style = ParagraphStyle(
                'CourierTotalQty', fontName='Helvetica-Bold', fontSize=10.5, leading=13, textColor=colors.black,
                alignment=TA_RIGHT,
            )

            # Columns: Product Name | Round / Sale Order | Delivery Date |
            # Stock Code | Quantity Ordered (section 11).
            table_data = [[
                Paragraph('Product Name', header_style_left),
                Paragraph('Round / Sale Order', header_style_left),
                Paragraph('Delivery Date', header_style_left),
                Paragraph('Stock Code', header_style_left),
                Paragraph('Quantity<br/>Ordered', header_style_right),
            ]]
            style_commands = [
                ('LINEBELOW', (0, 0), (-1, 0), 2, self.NAVY),
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('TOPPADDING', (0, 0), (-1, -1), 3),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
                ('LEFTPADDING', (0, 0), (-1, -1), 4),
                ('RIGHTPADDING', (0, 0), (-1, -1), 4),
            ]

            row_idx = 1
            for prod in products:
                first_subrow_idx = row_idx
                for i, r in enumerate(prod['rows']):
                    name_cell = Paragraph(f"<b>{xml_escape(prod['product_name'])}</b>", name_style) if i == 0 else ''
                    # Round/Sale Order column: "SO Number - Round Name" on
                    # line 1, its Delivery Date repeated on line 2.
                    round_cell = Paragraph(
                        f"{xml_escape(r['round_so_str'])}<br/>{xml_escape(r['round_date_str'])}", round_style,
                    )
                    date_cell = Paragraph(xml_escape(r['delivery_date_str']), date_style)
                    code_cell = Paragraph(xml_escape(r['stock_code']), code_style)
                    qty_cell = Paragraph(xml_escape(r['formatted_qty']), qty_style)
                    table_data.append([name_cell, round_cell, date_cell, code_cell, qty_cell])
                    row_idx += 1

                style_commands.append(('LINEABOVE', (0, first_subrow_idx), (-1, first_subrow_idx), 1.5, self.NAVY))

                table_data.append(['', '', '', '', Paragraph(xml_escape(prod['formatted_total_qty']), total_style)])
                style_commands.append(('LINEABOVE', (0, row_idx), (-1, row_idx), 1, self.NAVY))
                style_commands.append(('LINEBELOW', (0, row_idx), (-1, row_idx), 2.5, self.NAVY))
                row_idx += 1

            col_widths = [printable_width * w for w in (0.28, 0.26, 0.18, 0.14, 0.14)]
            prediction_table = Table(table_data, colWidths=col_widths, repeatRows=1)
            prediction_table.setStyle(TableStyle(style_commands))
            story.append(prediction_table)

        numbered_canvas = self._make_numbered_canvas(data['footer_date_str'])
        doc.build(story, canvasmaker=numbered_canvas)
        pdf_value = buffer.getvalue()
        buffer.close()
        return pdf_value
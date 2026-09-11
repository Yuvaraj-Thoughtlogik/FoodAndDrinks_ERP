# -*- coding: utf-8 -*-
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


class ReportPredictionCourier(models.AbstractModel):
    _name = 'report.tl_rf_reports.report_prediction_courier'
    _description = 'Courier Prediction Report Generator'

    @api.model
    def _get_report_values(self, docids, data=None):
        return self.env['report.tl_rf_reports.report_prediction']._get_report_values(docids, data=data)
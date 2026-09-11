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
        lang = self.env.lang or 'en_US'
        company_ids = tuple(self.env.companies.ids) if self.env.companies else (self.env.company.id,)

        for wizard in docs:
            # Format display dates
            delivery_date_from_str = wizard.delivery_date_from.strftime('%d/%m/%Y') if wizard.delivery_date_from else ''
            delivery_date_to_str = wizard.delivery_date_to.strftime('%d/%m/%Y') if wizard.delivery_date_to else ''
            date_range_str = f"{delivery_date_from_str} to {delivery_date_to_str}"
            footer_date_str = wizard.delivery_date_from.strftime('%d %B %Y') if wizard.delivery_date_from else ''

            params = {
                'date_from': wizard.delivery_date_from,
                'date_to': wizard.delivery_date_to,
                'company_ids': company_ids,
                'lang': lang,
            }

            channel_filter = ""
            if wizard.delivery_channel == 'courier':
                channel_filter = "AND so.delivery_channel = 'courier'"
            else:
                channel_filter = "AND (so.delivery_channel = 'regal_van' OR so.delivery_channel IS NULL)"

            depot_filter = ""
            if wizard.delivery_channel != 'courier' and wizard.depot_ids:
                depot_filter = "AND (sol.depot_id IN %(depot_ids)s OR (sol.depot_id IS NULL AND so.warehouse_id IN %(depot_ids)s))"
                params['depot_ids'] = tuple(wizard.depot_ids.ids)

            categ_filter = ""
            if wizard.categ_ids:
                categ_filter = "AND pt.categ_id IN %(categ_ids)s"
                params['categ_ids'] = tuple(wizard.categ_ids.ids)

            query = f"""
                SELECT 
                    sol.id AS line_id,
                    sol.product_uom_qty AS line_qty,
                    COALESCE(so.delivery_date, sol.delivery_date) AS delivery_date,
                    so.delivery_channel AS delivery_channel,
                    sw.id AS depot_id,
                    COALESCE(sw.name, 'Grimsby') AS depot_name,
                    p.id AS product_id,
                    p.product_tmpl_id AS tmpl_id,
                    COALESCE(pt.name->>%(lang)s, pt.name->>'en_GB', pt.name->>'en_US', pt.name::text) AS product_name
                FROM sale_order_line sol
                JOIN sale_order so ON so.id = sol.order_id
                JOIN product_product p ON p.id = sol.product_id
                JOIN product_template pt ON pt.id = p.product_tmpl_id
                LEFT JOIN stock_warehouse sw ON sw.id = COALESCE(sol.depot_id, so.warehouse_id)
                WHERE so.state IN ('sale', 'done')
                  AND so.delivery_date >= %(date_from)s
                  AND so.delivery_date <= %(date_to)s
                  AND sol.display_type IS NULL
                  AND sol.product_id IS NOT NULL
                  AND sol.product_uom_qty > 0
                  {channel_filter}
                  {depot_filter}
                  {categ_filter}
                  AND (so.company_id IS NULL OR so.company_id IN %(company_ids)s)
                ORDER BY p.id ASC, sol.id ASC
            """
            self.env.cr.execute(query, params)
            rows = self.env.cr.dictfetchall()

            if not rows:
                report_results.append({
                    'wizard': wizard,
                    'delivery_channel': wizard.delivery_channel,
                    'delivery_date_from_str': delivery_date_from_str,
                    'delivery_date_to_str': delivery_date_to_str,
                    'date_range_str': date_range_str,
                    'footer_date_str': footer_date_str,
                    'products': [],
                    'grand_total_qty': 0.0,
                    'formatted_grand_total_qty': '0',
                })
                continue

            product_ids = tuple({r['product_id'] for r in rows})
            tmpl_ids = tuple({r['tmpl_id'] for r in rows})

            bom_query = """
                SELECT 
                    mb.id AS bom_id,
                    mb.product_id AS bom_product_id,
                    mb.product_tmpl_id AS bom_tmpl_id,
                    COALESCE(mb.product_qty, 1.0) AS bom_qty,
                    mb.sequence AS bom_sequence,
                    mbl.product_id AS comp_product_id,
                    mbl.product_qty AS comp_line_qty,
                    COALESCE(pt_comp.name->>%(lang)s, pt_comp.name->>'en_GB', pt_comp.name->>'en_US', pt_comp.name::text) AS comp_product_name
                FROM mrp_bom mb
                JOIN mrp_bom_line mbl ON mbl.bom_id = mb.id
                JOIN product_product p_comp ON p_comp.id = mbl.product_id
                JOIN product_template pt_comp ON pt_comp.id = p_comp.product_tmpl_id
                WHERE mb.active = true
                  AND (mb.company_id IS NULL OR mb.company_id IN %(company_ids)s)
                  AND (mb.product_id IN %(product_ids)s OR (mb.product_id IS NULL AND mb.product_tmpl_id IN %(tmpl_ids)s))
                ORDER BY mb.sequence ASC, mb.id ASC
            """
            self.env.cr.execute(bom_query, {
                'product_ids': product_ids,
                'tmpl_ids': tmpl_ids,
                'company_ids': company_ids,
                'lang': lang,
            })
            bom_rows = self.env.cr.dictfetchall()

            variant_boms = {}
            tmpl_boms = {}
            for br in bom_rows:
                if br['bom_product_id']:
                    if br['bom_product_id'] not in variant_boms:
                        variant_boms[br['bom_product_id']] = {'qty': br['bom_qty'], 'lines': []}
                    variant_boms[br['bom_product_id']]['lines'].append(br)
                elif br['bom_tmpl_id']:
                    if br['bom_tmpl_id'] not in tmpl_boms:
                        tmpl_boms[br['bom_tmpl_id']] = {'qty': br['bom_qty'], 'lines': []}
                    tmpl_boms[br['bom_tmpl_id']]['lines'].append(br)

            products_map = {}
            grand_total_qty = 0.0

            for r in rows:
                qty = float(r['line_qty'] or 0.0)
                pid = r['product_id']
                tid = r['tmpl_id']

                d_date = r['delivery_date'] or wizard.delivery_date_from
                if d_date:
                    date_key = d_date.strftime('%Y-%m-%d')
                    date_display = d_date.strftime('%d %B %Y')
                else:
                    date_key = '9999-99-99'
                    date_display = ''

                if wizard.delivery_channel == 'courier' or r['delivery_channel'] == 'courier':
                    depot_name = _('Courier')
                    depot_key = 'courier'
                else:
                    depot_name = (r['depot_name'] or _('Grimsby')).strip()
                    depot_key = r['depot_id'] or 0

                bom_info = variant_boms.get(pid) or tmpl_boms.get(tid)
                if bom_info and bom_info['lines']:
                    bom_produced_qty = bom_info['qty'] or 1.0
                    items = [
                        (comp['comp_product_id'], comp['comp_product_name'], (comp['comp_line_qty'] / bom_produced_qty) * qty)
                        for comp in bom_info['lines']
                    ]
                else:
                    items = [(pid, r['product_name'], qty)]

                for item_pid, item_name, item_qty in items:
                    if not item_qty:
                        continue
                    if item_pid not in products_map:
                        products_map[item_pid] = {
                            'product_id': item_pid,
                            'product_name': (item_name or '').strip(),
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
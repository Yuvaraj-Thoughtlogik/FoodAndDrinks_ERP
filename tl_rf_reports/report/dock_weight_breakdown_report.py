# -*- coding: utf-8 -*-
import datetime
import re
from odoo import api, fields, models, _


def _format_weight_display(val):
    if val is None:
        return '0'
    formatted = f"{val:.2f}"
    if '.' in formatted:
        formatted = formatted.rstrip('0').rstrip('.')
    return formatted


class ReportDockWeightBreakdown(models.AbstractModel):
    _name = 'report.tl_rf_reports.report_dock_weight_breakdown'
    _description = 'Dock Weight Breakdown Report Generator'

    @api.model
    def _extract_unit_weight_from_vals(self, uom_name, weight, gross_net_weight, min_weight, product_name):
        """Calculates or extracts unit weight in kg from record values."""
        # 1. If UoM is already in kg, unit weight ratio is 1.0
        uom_n = (uom_name or '').strip().lower()
        if uom_n in ('kg', 'kgs', 'kilogram', 'kilograms'):
            return 1.0

        # 2. Product standard weight field
        if weight and weight > 0:
            return float(weight)

        # 3. Check gross_net_weight or min_weight string attributes
        weight_str = gross_net_weight or min_weight
        if weight_str:
            weight_clean = str(weight_str).strip().lower()
            match = re.search(r"[-+]?\d*\.?\d+", weight_clean)
            if match:
                try:
                    num_val = float(match.group())
                    if 'g' in weight_clean and 'kg' not in weight_clean:
                        return num_val / 1000.0
                    return num_val
                except ValueError:
                    pass

        # 4. Fallback: Parse weight from product name (e.g., '125-140G', '1-1.2kg')
        if product_name:
            g_range = re.search(r"(\d+)\s*-\s*(\d+)\s*g\b", product_name, re.IGNORECASE)
            if g_range:
                avg_g = (float(g_range.group(1)) + float(g_range.group(2))) / 2.0
                return avg_g / 1000.0
            g_single = re.search(r"(\d+(?:\.\d+)?)\s*g\b", product_name, re.IGNORECASE)
            if g_single:
                return float(g_single.group(1)) / 1000.0
            kg_range = re.search(r"(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)\s*kg\b", product_name, re.IGNORECASE)
            if kg_range:
                avg_kg = (float(kg_range.group(1)) + float(kg_range.group(2))) / 2.0
                return avg_kg
            kg_single = re.search(r"(\d+(?:\.\d+)?)\s*kg\b", product_name, re.IGNORECASE)
            if kg_single:
                return float(kg_single.group(1))

        return 0.0

    @api.model
    def _extract_unit_weight(self, product, line=None):
        """Preserved for backwards-compatibility."""
        uom = (line.product_uom_id if line and hasattr(line, 'product_uom_id') and line.product_uom_id else (product.uom_id if product else False))
        uom_name = (uom.name or '') if uom else ''
        weight = product.weight if product else 0.0
        gnw = (line.gross_net_weight if line and getattr(line, 'gross_net_weight', False) else getattr(product, 'gross_net_weight', False))
        mw = (line.min_weight if line and getattr(line, 'min_weight', False) else getattr(product, 'min_weight', False))
        pname = (product.name or '') if product else ''
        return self._extract_unit_weight_from_vals(uom_name, weight, gnw, mw, pname)

    @api.model
    def _get_report_values(self, docids, data=None):
        docs = self.env['batch.report.wizard'].browse(docids)

        report_results = []
        lang = self.env.lang or 'en_US'
        company_ids = tuple(self.env.companies.ids) if self.env.companies else (self.env.company.id,)

        for wizard in docs:
            # Format display date
            if wizard.delivery_date_from == wizard.delivery_date_to:
                formatted_date = wizard.delivery_date_from.strftime('%A %d/%m/%Y')
                delivery_date_str = wizard.delivery_date_from.strftime('%d/%m/%Y')
            else:
                formatted_date = f"{wizard.delivery_date_from.strftime('%A %d/%m/%Y')} - {wizard.delivery_date_to.strftime('%A %d/%m/%Y')}"
                delivery_date_str = f"{wizard.delivery_date_from.strftime('%d/%m/%Y')} - {wizard.delivery_date_to.strftime('%d/%m/%Y')}"

            # Calculate packing dates (1 day before delivery date)
            packing_date_from = wizard.delivery_date_from - datetime.timedelta(days=1)
            packing_date_to = wizard.delivery_date_to - datetime.timedelta(days=1)
            packing_date_from_str = packing_date_from.strftime('%d/%m/%Y')
            packing_date_to_str = packing_date_to.strftime('%d/%m/%Y')
            delivery_date_from_str = wizard.delivery_date_from.strftime('%d/%m/%Y')
            delivery_date_to_str = wizard.delivery_date_to.strftime('%d/%m/%Y')

            # Footer date display: e.g. "10 August 2026"
            print_date_str = packing_date_from.strftime('%d %B %Y')

            # Current timestamp in user timezone for "Printed at ..."
            current_dt = fields.Datetime.context_timestamp(self, fields.Datetime.now())
            printed_at_str = current_dt.strftime('%d/%m/%Y %H:%M:%S')

            # Courier Delivery Flow
            if getattr(wizard, 'delivery_channel', 'regal_van') == 'courier':
                courier_query = """
                    SELECT 
                        so.id AS order_id,
                        sol.id AS line_id,
                        sol.product_uom_qty AS line_qty,
                        p.id AS product_id,
                        p.default_code AS product_code,
                        COALESCE(pt.name->>%(lang)s, pt.name->>'en_GB', pt.name->>'en_US', pt.name::text) AS product_name,
                        COALESCE(p.weight, pt.weight, 0.0) AS weight,
                        COALESCE(sol.gross_net_weight, pt.gross_net_weight) AS gross_net_weight,
                        sol.min_weight AS min_weight,
                        COALESCE(uom.name->>%(lang)s, uom.name->>'en_GB', uom.name->>'en_US', uom.name::text) AS uom_name,
                        pc.id AS categ_id,
                        COALESCE(pc.name->>%(lang)s, pc.name->>'en_GB', pc.name->>'en_US', pc.name::text) AS categ_name
                    FROM sale_order so
                    JOIN sale_order_line sol ON sol.order_id = so.id 
                        AND sol.display_type IS NULL 
                        AND sol.product_id IS NOT NULL 
                        AND sol.product_uom_qty > 0
                    JOIN product_product p ON p.id = sol.product_id
                    JOIN product_template pt ON pt.id = p.product_tmpl_id
                    LEFT JOIN uom_uom uom ON uom.id = COALESCE(sol.product_uom, p.uom_id, pt.uom_id)
                    LEFT JOIN product_category pc ON pc.id = pt.categ_id
                    WHERE so.delivery_channel = 'courier'
                      AND so.state IN ('sale', 'done')
                      AND so.delivery_date >= %(date_from)s
                      AND so.delivery_date <= %(date_to)s
                      AND COALESCE(so.is_late_order, false) = %(is_late)s
                      AND (so.company_id IS NULL OR so.company_id IN %(company_ids)s)
                    ORDER BY so.delivery_date ASC, so.name ASC, sol.id ASC
                """
                params = {
                    'date_from': wizard.delivery_date_from,
                    'date_to': wizard.delivery_date_to,
                    'is_late': bool(wizard.include_late_orders),
                    'company_ids': company_ids,
                    'lang': lang,
                }
                self.env.cr.execute(courier_query, params)
                c_rows = self.env.cr.dictfetchall()

                categories_map = {}
                grand_total_qty = 0.0
                grand_total_weight = 0.0
                unique_orders = set()

                for r in c_rows:
                    unique_orders.add(r['order_id'])
                    categ_key = r['categ_id'] or 0
                    categ_name = (r['categ_name'] or _('Fresh')).strip()

                    if categ_key not in categories_map:
                        categories_map[categ_key] = {
                            'categ_id': categ_key,
                            'categ_name': categ_name,
                            'products': {},
                            'total_qty': 0.0,
                            'total_weight': 0.0,
                        }

                    prod_key = r['product_id']
                    if prod_key not in categories_map[categ_key]['products']:
                        unit_weight = self._extract_unit_weight_from_vals(
                            r['uom_name'], r['weight'], r['gross_net_weight'], r['min_weight'], r['product_name']
                        )
                        categories_map[categ_key]['products'][prod_key] = {
                            'product_id': prod_key,
                            'product_code': r['product_code'] or '',
                            'product_name': r['product_name'] or '',
                            'uom_name': r['uom_name'] or '',
                            'unit_weight': unit_weight,
                            'total_qty': 0.0,
                            'total_weight': 0.0,
                        }

                    qty = float(r['line_qty'] or 0.0)
                    prod_info = categories_map[categ_key]['products'][prod_key]
                    line_weight = (prod_info['unit_weight'] * qty) if prod_info['unit_weight'] > 0 else qty

                    prod_info['total_qty'] += qty
                    prod_info['total_weight'] += line_weight

                    categ_map = categories_map[categ_key]
                    categ_map['total_qty'] += qty
                    categ_map['total_weight'] += line_weight

                    grand_total_qty += qty
                    grand_total_weight += line_weight

                category_pages = []
                for c_key, c_val in sorted(categories_map.items(), key=lambda item: item[1]['categ_name']):
                    prod_list = sorted(
                        c_val['products'].values(),
                        key=lambda item: item['product_name']
                    )
                    for prod_item in prod_list:
                        prod_item['formatted_weight'] = _format_weight_display(prod_item['total_weight'])
                    if prod_list:
                        category_pages.append({
                            'categ_name': c_val['categ_name'],
                            'title': f"Courier {c_val['categ_name'].upper()} Filleters Weights",
                            'product_list': prod_list,
                            'total_weight': c_val['total_weight'],
                            'total_qty': c_val['total_qty'],
                        })

                report_results.append({
                    'wizard': wizard,
                    'delivery_channel': 'courier',
                    'formatted_date': formatted_date,
                    'delivery_date_str': delivery_date_str,
                    'packing_date_from_str': packing_date_from_str,
                    'packing_date_to_str': packing_date_to_str,
                    'delivery_date_from_str': delivery_date_from_str,
                    'delivery_date_to_str': delivery_date_to_str,
                    'print_date_str': print_date_str,
                    'printed_at_str': printed_at_str,
                    'categories': category_pages,
                    'grand_total_qty': grand_total_qty,
                    'grand_total_weight': grand_total_weight,
                    'total_orders_count': len(unique_orders),
                })
                continue

            # Regal Van Delivery Flow (Batch-based)
            depot_filter = ""
            params = {
                'date_from': wizard.delivery_date_from,
                'date_to': wizard.delivery_date_to,
                'is_late': bool(wizard.include_late_orders),
                'company_ids': company_ids,
                'lang': lang,
            }
            if wizard.depot_ids:
                depot_filter = "AND b.depot_id IN %(depot_ids)s"
                params['depot_ids'] = tuple(wizard.depot_ids.ids)
            elif hasattr(wizard, 'depot_id') and wizard.depot_id:
                depot_filter = "AND b.depot_id = %(depot_id)s"
                params['depot_id'] = wizard.depot_id.id

            van_query = f"""
                SELECT 
                    b.id AS batch_id,
                    sw.id AS depot_id,
                    COALESCE(sw.name, 'Grimsby') AS depot_name,
                    COALESCE(sw.code, 'N/A') AS depot_code,
                    so.id AS order_id,
                    sol.id AS line_id,
                    sol.product_uom_qty AS line_qty,
                    p.id AS product_id,
                    p.default_code AS product_code,
                    COALESCE(pt.name->>%(lang)s, pt.name->>'en_GB', pt.name->>'en_US', pt.name::text) AS product_name,
                    COALESCE(p.weight, pt.weight, 0.0) AS weight,
                    COALESCE(sol.gross_net_weight, pt.gross_net_weight) AS gross_net_weight,
                    sol.min_weight AS min_weight,
                    COALESCE(uom.name->>%(lang)s, uom.name->>'en_GB', uom.name->>'en_US', uom.name::text) AS uom_name,
                    pc.id AS categ_id,
                    COALESCE(pc.name->>%(lang)s, pc.name->>'en_GB', pc.name->>'en_US', pc.name::text) AS categ_name
                FROM round_management_batch b
                LEFT JOIN stock_warehouse sw ON sw.id = b.depot_id
                JOIN sale_order so ON so.batch_id = b.id 
                    AND so.state IN ('sale', 'done') 
                    AND (so.delivery_channel = 'regal_van' OR so.delivery_channel IS NULL)
                    AND COALESCE(so.is_late_order, false) = %(is_late)s
                JOIN sale_order_line sol ON sol.order_id = so.id 
                    AND sol.display_type IS NULL 
                    AND sol.product_id IS NOT NULL 
                    AND sol.product_uom_qty > 0
                JOIN product_product p ON p.id = sol.product_id
                JOIN product_template pt ON pt.id = p.product_tmpl_id
                LEFT JOIN uom_uom uom ON uom.id = COALESCE(sol.product_uom, p.uom_id, pt.uom_id)
                LEFT JOIN product_category pc ON pc.id = pt.categ_id
                WHERE b.delivery_date >= %(date_from)s 
                  AND b.delivery_date <= %(date_to)s
                  {depot_filter}
                  AND (b.company_id IS NULL OR b.company_id IN %(company_ids)s)
                ORDER BY sw.name ASC, b.delivery_date ASC, b.code ASC, sol.id ASC
            """
            self.env.cr.execute(van_query, params)
            v_rows = self.env.cr.dictfetchall()

            depots_map = {}
            grand_total_qty = 0.0
            grand_total_weight = 0.0
            unique_batches = set()
            unique_orders = set()

            for r in v_rows:
                unique_batches.add(r['batch_id'])
                unique_orders.add(r['order_id'])

                depot_key = r['depot_id'] or 0
                depot_name = r['depot_name'] or _('Grimsby')
                depot_code = r['depot_code'] or 'N/A'

                if depot_key not in depots_map:
                    depots_map[depot_key] = {
                        'depot_id': depot_key,
                        'depot_name': depot_name,
                        'depot_code': depot_code,
                        'categories': {},
                        'total_qty': 0.0,
                        'total_weight': 0.0,
                    }

                categ_key = r['categ_id'] or 0
                categ_name = (r['categ_name'] or _('FRESH')).upper()

                if categ_key not in depots_map[depot_key]['categories']:
                    depots_map[depot_key]['categories'][categ_key] = {
                        'categ_id': categ_key,
                        'categ_name': categ_name,
                        'products': {},
                        'total_qty': 0.0,
                        'total_weight': 0.0,
                    }

                prod_key = r['product_id']
                if prod_key not in depots_map[depot_key]['categories'][categ_key]['products']:
                    unit_weight = self._extract_unit_weight_from_vals(
                        r['uom_name'], r['weight'], r['gross_net_weight'], r['min_weight'], r['product_name']
                    )
                    depots_map[depot_key]['categories'][categ_key]['products'][prod_key] = {
                        'product_id': prod_key,
                        'product_code': r['product_code'] or '',
                        'product_name': r['product_name'] or '',
                        'uom_name': r['uom_name'] or '',
                        'unit_weight': unit_weight,
                        'total_qty': 0.0,
                        'total_weight': 0.0,
                    }

                qty = float(r['line_qty'] or 0.0)
                prod_info = depots_map[depot_key]['categories'][categ_key]['products'][prod_key]
                line_weight = (prod_info['unit_weight'] * qty) if prod_info['unit_weight'] > 0 else qty

                prod_info['total_qty'] += qty
                prod_info['total_weight'] += line_weight

                categ_map = depots_map[depot_key]['categories'][categ_key]
                categ_map['total_qty'] += qty
                categ_map['total_weight'] += line_weight

                depots_map[depot_key]['total_qty'] += qty
                depots_map[depot_key]['total_weight'] += line_weight

                grand_total_qty += qty
                grand_total_weight += line_weight

            combo_pages = []
            for d_key, d_val in sorted(depots_map.items(), key=lambda item: item[1]['depot_name']):
                for c_key, c_val in sorted(d_val['categories'].items(), key=lambda item: item[1]['categ_name']):
                    prod_list = sorted(
                        c_val['products'].values(),
                        key=lambda item: item['product_name']
                    )
                    if prod_list:
                        combo_pages.append({
                            'depot_name': d_val['depot_name'],
                            'depot_code': d_val['depot_code'],
                            'categ_name': c_val['categ_name'],
                            'product_list': prod_list,
                            'total_weight': c_val['total_weight'],
                            'total_qty': c_val['total_qty'],
                        })

            report_results.append({
                'wizard': wizard,
                'delivery_channel': 'regal_van',
                'formatted_date': formatted_date,
                'delivery_date_str': delivery_date_str,
                'print_date_str': print_date_str,
                'printed_at_str': printed_at_str,
                'pages': combo_pages,
                'grand_total_qty': grand_total_qty,
                'grand_total_weight': grand_total_weight,
                'total_batches_count': len(unique_batches),
                'total_orders_count': len(unique_orders),
            })

        return {
            'doc_ids': docids,
            'doc_model': 'batch.report.wizard',
            'docs': docs,
            'report_results': report_results,
        }

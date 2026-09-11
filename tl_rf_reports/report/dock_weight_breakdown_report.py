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
    def _extract_unit_weight(self, product, line=None):
        """Calculates or extracts unit weight in kg for a given product/line."""
        # 1. If UoM is already in kg, unit weight ratio is 1.0
        uom = (line.product_uom_id if line and hasattr(line, 'product_uom_id') and line.product_uom_id else (product.uom_id if product else False))
        uom_name = (uom.name or '').strip().lower() if uom else ''
        if uom_name in ('kg', 'kgs', 'kilogram', 'kilograms'):
            return 1.0

        # 2. Product standard weight field
        if product.weight and product.weight > 0:
            return product.weight

        # 3. Check gross_net_weight or min_weight string attributes
        weight_str = False
        if line and getattr(line, 'gross_net_weight', False):
            weight_str = line.gross_net_weight
        elif getattr(product, 'gross_net_weight', False):
            weight_str = product.gross_net_weight
        elif line and getattr(line, 'min_weight', False):
            weight_str = line.min_weight
        elif getattr(product, 'min_weight', False):
            weight_str = product.min_weight

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
        if product.name:
            g_range = re.search(r"(\d+)\s*-\s*(\d+)\s*g\b", product.name, re.IGNORECASE)
            if g_range:
                avg_g = (float(g_range.group(1)) + float(g_range.group(2))) / 2.0
                return avg_g / 1000.0
            g_single = re.search(r"(\d+(?:\.\d+)?)\s*g\b", product.name, re.IGNORECASE)
            if g_single:
                return float(g_single.group(1)) / 1000.0
            kg_range = re.search(r"(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)\s*kg\b", product.name, re.IGNORECASE)
            if kg_range:
                avg_kg = (float(kg_range.group(1)) + float(kg_range.group(2))) / 2.0
                return avg_kg
            kg_single = re.search(r"(\d+(?:\.\d+)?)\s*kg\b", product.name, re.IGNORECASE)
            if kg_single:
                return float(kg_single.group(1))

        return 0.0

    @api.model
    def _get_report_values(self, docids, data=None):
        docs = self.env['batch.report.wizard'].browse(docids)

        report_results = []
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
                order_domain = [
                    ('delivery_channel', '=', 'courier'),
                    ('state', 'in', ['sale', 'done']),
                    ('delivery_date', '>=', wizard.delivery_date_from),
                    ('delivery_date', '<=', wizard.delivery_date_to),
                ]
                if not wizard.include_late_orders:
                    order_domain.append(('is_late_order', '=', False))
                else:
                    order_domain.append(('is_late_order', '=', True))

                applicable_orders = self.env['sale.order'].search(order_domain, order='delivery_date asc, name asc')

                categories_map = {}
                grand_total_qty = 0.0
                grand_total_weight = 0.0

                for order in applicable_orders:
                    for line in order.order_line.filtered(lambda l: not l.display_type and l.product_id):
                        product = line.product_id
                        categ = product.categ_id
                        categ_key = categ.id if categ else 0
                        categ_name = (categ.name or _('Fresh')).strip() if categ else 'Fresh'

                        if categ_key not in categories_map:
                            categories_map[categ_key] = {
                                'categ_id': categ_key,
                                'categ_name': categ_name,
                                'products': {},
                                'total_qty': 0.0,
                                'total_weight': 0.0,
                            }

                        prod_key = product.id
                        if prod_key not in categories_map[categ_key]['products']:
                            unit_weight = self._extract_unit_weight(product, line)
                            uom_name = (line.product_uom_id.name if hasattr(line, 'product_uom_id') and line.product_uom_id else (product.uom_id.name if product.uom_id else ''))
                            product_name = line.product_id.name or product.name

                            categories_map[categ_key]['products'][prod_key] = {
                                'product_id': prod_key,
                                'product_code': product.default_code or '',
                                'product_name': product_name,
                                'uom_name': uom_name,
                                'unit_weight': unit_weight,
                                'total_qty': 0.0,
                                'total_weight': 0.0,
                            }

                        qty = line.product_uom_qty
                        prod_info = categories_map[categ_key]['products'][prod_key]

                        if prod_info['unit_weight'] > 0:
                            line_weight = prod_info['unit_weight'] * qty
                        else:
                            line_weight = qty

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
                    'total_orders_count': len(applicable_orders),
                })
                continue

            # Regal Van Delivery Flow (Batch-based)
            # Step 1: Find eligible batches
            batch_domain = [
                ('delivery_date', '>=', wizard.delivery_date_from),
                ('delivery_date', '<=', wizard.delivery_date_to),
            ]
            if wizard.depot_ids:
                batch_domain.append(('depot_id', 'in', wizard.depot_ids.ids))
            elif hasattr(wizard, 'depot_id') and wizard.depot_id:
                batch_domain.append(('depot_id', '=', wizard.depot_id.id))

            batches = self.env['round.management.batch'].search(batch_domain, order='delivery_date asc, code asc')

            # Step 2: Retrieve and filter Sale Orders
            all_orders = batches.mapped('order_ids').filtered(
                lambda so: so.state in ('sale', 'done') and getattr(so, 'delivery_channel', False) in ('regal_van', False)
            )

            if not wizard.include_late_orders:
                applicable_orders = all_orders.filtered(lambda so: not getattr(so, 'is_late_order', False))
            else:
                applicable_orders = all_orders.filtered(lambda so: getattr(so, 'is_late_order', False))

            # Step 3: Group by Depot -> Category -> Product
            depots_map = {}
            grand_total_qty = 0.0
            grand_total_weight = 0.0

            for order in applicable_orders:
                batch = order.batch_id
                depot = batch.depot_id if (batch and batch.depot_id) else False
                depot_key = depot.id if depot else 0
                depot_name = depot.name if depot else _('Grimsby')
                depot_code = depot.code if depot else 'N/A'

                if depot_key not in depots_map:
                    depots_map[depot_key] = {
                        'depot_id': depot_key,
                        'depot_name': depot_name,
                        'depot_code': depot_code,
                        'categories': {},
                        'total_qty': 0.0,
                        'total_weight': 0.0,
                    }

                for line in order.order_line.filtered(lambda l: not l.display_type and l.product_id):
                    product = line.product_id
                    categ = product.categ_id
                    categ_key = categ.id if categ else 0
                    categ_name = (categ.name or _('FRESH')).upper() if categ else 'FRESH'

                    if categ_key not in depots_map[depot_key]['categories']:
                        depots_map[depot_key]['categories'][categ_key] = {
                            'categ_id': categ_key,
                            'categ_name': categ_name,
                            'products': {},
                            'total_qty': 0.0,
                            'total_weight': 0.0,
                        }

                    prod_key = product.id
                    if prod_key not in depots_map[depot_key]['categories'][categ_key]['products']:
                        unit_weight = self._extract_unit_weight(product, line)
                        uom_name = (line.product_uom_id.name if hasattr(line, 'product_uom_id') and line.product_uom_id else (product.uom_id.name if product.uom_id else ''))

                        depots_map[depot_key]['categories'][categ_key]['products'][prod_key] = {
                            'product_id': prod_key,
                            'product_code': product.default_code or '',
                            'product_name': product.name,
                            'uom_name': uom_name,
                            'unit_weight': unit_weight,
                            'total_qty': 0.0,
                            'total_weight': 0.0,
                        }

                    qty = line.product_uom_qty
                    prod_info = depots_map[depot_key]['categories'][categ_key]['products'][prod_key]
                    
                    if prod_info['unit_weight'] > 0:
                        line_weight = prod_info['unit_weight'] * qty
                    else:
                        line_weight = qty

                    prod_info['total_qty'] += qty
                    prod_info['total_weight'] += line_weight

                    categ_map = depots_map[depot_key]['categories'][categ_key]
                    categ_map['total_qty'] += qty
                    categ_map['total_weight'] += line_weight

                    depots_map[depot_key]['total_qty'] += qty
                    depots_map[depot_key]['total_weight'] += line_weight

                    grand_total_qty += qty
                    grand_total_weight += line_weight

            # Build list of distinct pages: 1 page per (Depot + Product Category) combo
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
                'total_batches_count': len(batches),
                'total_orders_count': len(applicable_orders),
            })

        return {
            'doc_ids': docids,
            'doc_model': 'batch.report.wizard',
            'docs': docs,
            'report_results': report_results,
        }

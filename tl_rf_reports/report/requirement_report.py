# -*- coding: utf-8 -*-
import datetime
import math
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

            # Fetch matching order lines
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


class ReportRequirementCourier(models.AbstractModel):
    _name = 'report.tl_rf_reports.report_requirement_courier'
    _description = 'Courier Requirement Report Generator'

    @api.model
    def _get_report_values(self, docids, data=None):
        return self.env['report.tl_rf_reports.report_requirement']._get_report_values(docids, data=data)
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

            # Group by Category -> Product -> Delivery Date
            categories_map = {}
            grand_total_qty = 0.0

            for line in lines:
                product = line.product_id
                if not product:
                    continue

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

                # Delivery date for this line
                d_date = line.order_id.delivery_date or wizard.delivery_date_from
                d_date_str = d_date.strftime('%d/%m/%Y') if d_date else delivery_date_from_str

                qty = line.product_uom_qty

                prod_item = categories_map[categ_key]['products'][prod_key]
                if d_date_str not in prod_item['dates_map']:
                    prod_item['dates_map'][d_date_str] = 0.0
                prod_item['dates_map'][d_date_str] += qty
                prod_item['total_qty'] += qty

                categories_map[categ_key]['total_qty'] += qty
                grand_total_qty += qty

            # Format category pages and split products into 2 columns (for Regal Van)
            category_pages = []
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
                    # Split into 2 columns
                    half = math.ceil(len(prod_list) / 2.0)
                    col1 = prod_list[:half]
                    col2 = prod_list[half:]

                    category_pages.append({
                        'categ_id': c_val['categ_id'],
                        'categ_name': c_val['categ_name'],
                        'title': c_val['title'],
                        'products': prod_list,
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

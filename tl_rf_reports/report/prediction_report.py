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

            # Group by Product -> Delivery Date -> Depot
            products_map = {}
            grand_total_qty = 0.0

            for line in lines:
                product = line.product_id
                if not product:
                    continue

                prod_key = product.id
                prod_name = (product.name or product.display_name or '').strip()

                if prod_key not in products_map:
                    products_map[prod_key] = {
                        'product_id': prod_key,
                        'product_name': prod_name,
                        'dates_map': {},
                        'total_qty': 0.0,
                    }

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

                qty = line.product_uom_qty or 0.0

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

                date_item['depots_map'][depot_key]['qty'] += qty
                prod_item['total_qty'] += qty
                grand_total_qty += qty

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

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

    # -------------------------------------------------------------------------
    # BOM HELPER
    # -------------------------------------------------------------------------
    def _get_product_bom(self, product):
        """
        Find the applicable BOM for the product.

        Priority:
        1. Variant-specific BOM
        2. Product-template BOM

        Only active BOMs are considered.
        """
        if not product:
            return self.env['mrp.bom']

        Bom = self.env['mrp.bom']

        # First look for a BOM specifically created for this product variant.
        bom = Bom.search([
            ('product_id', '=', product.id),
            ('active', '=', True),
            ('company_id', 'in', [False, product.company_id.id]),
        ], order='sequence, id', limit=1)

        if bom:
            return bom

        # If there is no variant-specific BOM, use the product template BOM.
        bom = Bom.search([
            ('product_tmpl_id', '=', product.product_tmpl_id.id),
            ('product_id', '=', False),
            ('active', '=', True),
            ('company_id', 'in', [False, product.company_id.id]),
        ], order='sequence, id', limit=1)

        return bom

    # -------------------------------------------------------------------------
    # GET BOM COMPONENTS
    # -------------------------------------------------------------------------
    def _get_bom_components(self, product, ordered_qty):
        """
        Return BOM components required for the given ordered quantity.

        Example:
            Finished Product = 2 Qty

            BOM:
                Component A = 2
                Component B = 2

            Result:
                Component A = 4
                Component B = 4

        The returned values are converted to the component's normal product
        UoM so that the report can display the component quantity correctly.
        """

        bom = self._get_product_bom(product)

        if not bom:
            return []

        if not bom.product_qty:
            return []

        # Convert the Sale Order quantity into the BOM's finished-product UoM.
        bom_finished_qty = ordered_qty

        if product.uom_id and bom.product_uom_id:
            bom_finished_qty = product.uom_id._compute_quantity(
                ordered_qty,
                bom.product_uom_id,
            )

        # Calculate how many BOMs are required.
        bom_multiplier = bom_finished_qty / bom.product_qty

        components = []

        for bom_line in bom.bom_line_ids:
            component = bom_line.product_id

            if not component:
                continue

            component_qty = bom_line.product_qty * bom_multiplier

            # Convert BOM component UoM to the component's normal UoM.
            if bom_line.product_uom_id and component.uom_id:
                component_qty = bom_line.product_uom_id._compute_quantity(
                    component_qty,
                    component.uom_id,
                )

            components.append({
                'product': component,
                'qty': component_qty,
            })

        return components

    # -------------------------------------------------------------------------
    # REPORT
    # -------------------------------------------------------------------------
    @api.model
    def _get_report_values(self, docids, data=None):
        docs = self.env['prediction.report.wizard'].browse(docids)

        report_results = []

        for wizard in docs:

            # -----------------------------------------------------------------
            # Format display dates
            # -----------------------------------------------------------------
            delivery_date_from_str = (
                wizard.delivery_date_from.strftime('%d/%m/%Y')
                if wizard.delivery_date_from
                else ''
            )

            delivery_date_to_str = (
                wizard.delivery_date_to.strftime('%d/%m/%Y')
                if wizard.delivery_date_to
                else ''
            )

            date_range_str = (
                f"{delivery_date_from_str} to {delivery_date_to_str}"
            )

            # Footer date display
            footer_date_str = (
                wizard.delivery_date_from.strftime('%d %B %Y')
                if wizard.delivery_date_from
                else ''
            )

            # -----------------------------------------------------------------
            # Fetch matching Sale Order Lines
            #
            # IMPORTANT:
            # The existing wizard filtering logic is unchanged.
            # -----------------------------------------------------------------
            domain = wizard._get_line_domain()

            lines = self.env['sale.order.line'].search(
                domain,
                order='product_id, id asc'
            )

            # -----------------------------------------------------------------
            # FIRST STEP
            #
            # Consolidate Sale Order Lines by finished product + date + depot.
            #
            # This gives us the actual ordered quantity of each finished
            # product before checking its BOM.
            # -----------------------------------------------------------------
            finished_products_map = {}

            for line in lines:

                product = line.product_id

                if not product:
                    continue

                # -------------------------------------------------------------
                # Delivery date
                # -------------------------------------------------------------
                d_date = (
                    line.order_id.delivery_date
                    or line.delivery_date
                    or wizard.delivery_date_from
                )

                if d_date:
                    date_key = d_date.strftime('%Y-%m-%d')
                    date_display = d_date.strftime('%d %B %Y')
                else:
                    date_key = '9999-99-99'
                    date_display = ''

                # -------------------------------------------------------------
                # Depot / Delivery Channel
                # -------------------------------------------------------------
                if (
                    wizard.delivery_channel == 'courier'
                    or getattr(
                        line.order_id,
                        'delivery_channel',
                        False
                    ) == 'courier'
                ):
                    depot_name = _('Courier')
                    depot_key = 'courier'

                else:
                    depot = (
                        line.depot_id
                        or (
                            line.order_id.batch_id.depot_id
                            if hasattr(line.order_id, 'batch_id')
                            and line.order_id.batch_id
                            else False
                        )
                        or line.order_id.warehouse_id
                    )

                    depot_name = (
                        (depot.name or _('Grimsby')).strip()
                        if depot
                        else _('Grimsby')
                    )

                    depot_key = depot.id if depot else 0

                # -------------------------------------------------------------
                # Ordered quantity
                # -------------------------------------------------------------
                qty = line.product_uom_qty or 0.0

                # -------------------------------------------------------------
                # Finished product map
                # -------------------------------------------------------------
                prod_key = product.id

                if prod_key not in finished_products_map:
                    finished_products_map[prod_key] = {
                        'product': product,
                        'product_id': product.id,
                        'product_name': (
                            product.name
                            or product.display_name
                            or ''
                        ).strip(),
                        'dates_map': {},
                        'total_qty': 0.0,
                    }

                prod_item = finished_products_map[prod_key]

                # -------------------------------------------------------------
                # Date map
                # -------------------------------------------------------------
                if date_key not in prod_item['dates_map']:
                    prod_item['dates_map'][date_key] = {
                        'date_key': date_key,
                        'date_display': date_display,
                        'depots_map': {},
                    }

                date_item = prod_item['dates_map'][date_key]

                # -------------------------------------------------------------
                # Depot map
                # -------------------------------------------------------------
                if depot_key not in date_item['depots_map']:
                    date_item['depots_map'][depot_key] = {
                        'depot_key': depot_key,
                        'depot_name': depot_name,
                        'qty': 0.0,
                    }

                date_item['depots_map'][depot_key]['qty'] += qty
                prod_item['total_qty'] += qty

            # -----------------------------------------------------------------
            # SECOND STEP
            #
            # Check every consolidated finished product for BOM.
            #
            # No BOM:
            #     Keep the original product.
            #
            # BOM:
            #     Replace the finished product with its components.
            #
            # Components are consolidated by component product.
            # -----------------------------------------------------------------
            products_map = {}

            for prod_key, prod_data in finished_products_map.items():

                product = prod_data['product']
                total_finished_qty = prod_data['total_qty']

                # -------------------------------------------------------------
                # Check BOM
                # -------------------------------------------------------------
                bom = self._get_product_bom(product)

                # =============================================================
                # CASE 1: NO BOM
                # =============================================================
                if not bom:

                    output_key = product.id

                    if output_key not in products_map:
                        products_map[output_key] = {
                            'product_id': product.id,
                            'product_name': (
                                product.name
                                or product.display_name
                                or ''
                            ).strip(),
                            'dates_map': {},
                            'total_qty': 0.0,
                        }

                    output_product = products_map[output_key]

                    # Copy existing date/depot breakdown.
                    for date_key, date_data in prod_data['dates_map'].items():

                        if date_key not in output_product['dates_map']:
                            output_product['dates_map'][date_key] = {
                                'date_key': date_key,
                                'date_display': date_data['date_display'],
                                'depots_map': {},
                            }

                        output_date = output_product['dates_map'][date_key]

                        for depot_key, depot_data in date_data['depots_map'].items():

                            if depot_key not in output_date['depots_map']:
                                output_date['depots_map'][depot_key] = {
                                    'depot_key': depot_key,
                                    'depot_name': depot_data['depot_name'],
                                    'qty': 0.0,
                                }

                            output_date['depots_map'][depot_key]['qty'] += (
                                depot_data['qty']
                            )

                    output_product['total_qty'] += total_finished_qty

                # =============================================================
                # CASE 2: BOM EXISTS
                # =============================================================
                else:

                    # ---------------------------------------------------------
                    # Process each date/depot separately.
                    #
                    # This preserves the existing report structure.
                    # ---------------------------------------------------------
                    for date_key, date_data in prod_data['dates_map'].items():

                        for depot_key, depot_data in date_data['depots_map'].items():

                            finished_qty = depot_data['qty']

                            # -------------------------------------------------
                            # Get components for this quantity.
                            # -------------------------------------------------
                            components = self._get_bom_components(
                                product,
                                finished_qty,
                            )

                            for component_data in components:

                                component = component_data['product']
                                component_qty = component_data['qty']

                                if not component:
                                    continue

                                component_key = component.id

                                # -------------------------------------------------
                                # Create consolidated component entry.
                                # -------------------------------------------------
                                if component_key not in products_map:
                                    products_map[component_key] = {
                                        'product_id': component.id,
                                        'product_name': (
                                            component.name
                                            or component.display_name
                                            or ''
                                        ).strip(),
                                        'dates_map': {},
                                        'total_qty': 0.0,
                                    }

                                component_product = products_map[component_key]

                                # -------------------------------------------------
                                # Date
                                # -------------------------------------------------
                                if date_key not in component_product['dates_map']:
                                    component_product['dates_map'][date_key] = {
                                        'date_key': date_key,
                                        'date_display': date_data['date_display'],
                                        'depots_map': {},
                                    }

                                component_date = (
                                    component_product['dates_map'][date_key]
                                )

                                # -------------------------------------------------
                                # Depot
                                # -------------------------------------------------
                                if depot_key not in component_date['depots_map']:
                                    component_date['depots_map'][depot_key] = {
                                        'depot_key': depot_key,
                                        'depot_name': depot_data['depot_name'],
                                        'qty': 0.0,
                                    }

                                component_date['depots_map'][depot_key]['qty'] += (
                                    component_qty
                                )

                                # -------------------------------------------------
                                # Consolidated component total
                                # -------------------------------------------------
                                component_product['total_qty'] += component_qty

            # -----------------------------------------------------------------
            # THIRD STEP
            #
            # Format products and their sub-rows for QWeb.
            # -----------------------------------------------------------------
            products_list = []

            for prod_key, prod_data in sorted(
                products_map.items(),
                key=lambda item: item[1]['product_name'].lower()
            ):

                rows = []

                for date_key in sorted(prod_data['dates_map'].keys()):

                    date_data = prod_data['dates_map'][date_key]

                    is_first_depot = True

                    for depot_key, depot_data in sorted(
                        date_data['depots_map'].items(),
                        key=lambda d: d[1]['depot_name'].lower()
                    ):

                        rows.append({
                            'is_first_date_row': is_first_depot,
                            'delivery_date_str': (
                                date_data['date_display']
                                if is_first_depot
                                else ''
                            ),
                            'depot_name': depot_data['depot_name'],
                            'qty': depot_data['qty'],
                            'formatted_qty': _format_qty(
                                depot_data['qty']
                            ),
                        })

                        is_first_depot = False

                if rows:
                    products_list.append({
                        'product_id': prod_key,
                        'product_name': prod_data['product_name'],
                        'rows': rows,
                        'total_qty': prod_data['total_qty'],
                        'formatted_total_qty': _format_qty(
                            prod_data['total_qty']
                        ),
                    })

            # -----------------------------------------------------------------
            # GRAND TOTAL
            # -----------------------------------------------------------------
            grand_total_qty = sum(
                product_data['total_qty']
                for product_data in products_map.values()
            )

            # -----------------------------------------------------------------
            # Final report result
            # -----------------------------------------------------------------
            report_results.append({
                'wizard': wizard,
                'delivery_channel': wizard.delivery_channel,
                'delivery_date_from_str': delivery_date_from_str,
                'delivery_date_to_str': delivery_date_to_str,
                'date_range_str': date_range_str,
                'footer_date_str': footer_date_str,
                'products': products_list,
                'grand_total_qty': grand_total_qty,
                'formatted_grand_total_qty': _format_qty(
                    grand_total_qty
                ),
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
        return self.env[
            'report.tl_rf_reports.report_prediction'
        ]._get_report_values(
            docids,
            data=data
        )
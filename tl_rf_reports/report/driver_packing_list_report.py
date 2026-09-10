# -*- coding: utf-8 -*-

from odoo import api, fields, models, _


class ReportDriverPackingList(models.AbstractModel):
    _name = 'report.tl_rf_reports.report_driver_packing_list_document'
    _description = 'Driver Packing List Report Generator'

    # ------------------------------------------------------------------
    # BOM helpers
    #
    # Lookup pattern (variant-specific BOM first, then template-level
    # fallback) matches report.tl_rf_reports.report_prediction._find_bom.
    #
    # Unlike the Prediction report (which explodes ANY BOM it finds),
    # the Driver Packing List is type-aware per the functional spec:
    #   - No BOM                          -> product + ordered qty, unchanged.
    #   - BOM type 'normal'
    #     ("Manufacture this product")    -> product + ordered qty, unchanged
    #                                         (NOT exploded).
    #   - BOM type 'phantom' ("Kit")      -> exploded into components, one
    #                                         level only, qty scaled to the
    #                                         ordered qty of the finished
    #                                         product.
    # ------------------------------------------------------------------
    @api.model
    def _find_bom(self, product):
        """Return the applicable BOM for a product (variant-specific first,
        falling back to a template-level BOM), or an empty recordset if the
        product has no BOM."""
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

    @api.model
    def _explode_bom(self, product, qty, bom_cache):
        """Resolve a sold product + ordered qty to the item(s) that should
        actually be printed on the Driver Packing List.

        Returns a list of (reporting_product, reporting_qty) tuples:
        - No BOM, or BOM type 'normal' (Manufacture this product):
          [(product, qty)] - unchanged, not exploded.
        - BOM type 'phantom' (Kit): one entry per BOM component, with the
          component qty scaled to the ordered qty of the finished product
          (single-level explosion only - a component that itself has a BOM
          is NOT exploded further):
              component_qty = (bom_line_qty / bom_produced_qty) * ordered_qty
        """
        if product.id not in bom_cache:
            bom_cache[product.id] = self._find_bom(product)
        bom = bom_cache[product.id]

        if not bom or bom.type != 'phantom':
            # No BOM, or a "Manufacture this product" BOM (Case 1 / Case 3):
            # show the original finished product with the ordered quantity.
            return [(product, qty)]

        # Kit BOM (Case 2): explode into components.
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

        # Safety net: a Kit BOM with no usable lines should not make the
        # ordered qty disappear from the report.
        if not result:
            return [(product, qty)]

        return result

    # ------------------------------------------------------------------
    # Sorting helpers - same conventions as report.tl_rf_reports.report_packing_list:
    # Frozen first, Fresh second, everything else alphabetically; products
    # within a category ordered by their Product Master sort number.
    # ------------------------------------------------------------------
    @api.model
    def _get_sort_key(self, product_item):
        sort_num = product_item.get('sort_num')
        product_name = (product_item.get('product_name') or '').strip().lower()

        if not sort_num or sort_num <= 0:
            return (0, 0, product_name)

        return (1, sort_num, product_name)

    @api.model
    def _extract_sort_number(self, product):
        """Product-level sort number only. A Kit's component can differ from
        the product actually sold, so (unlike the standard Packing List) we
        deliberately don't fall back to the sale order line's sort_seq here
        - that would apply the sold product's sort position to a different,
        substituted component.
        """
        sort_val = 0

        if product:
            if hasattr(product, 'sort_seq') and product.sort_seq:
                sort_val = product.sort_seq
            elif (
                hasattr(product, 'product_tmpl_id')
                and hasattr(product.product_tmpl_id, 'sort_seq')
                and product.product_tmpl_id.sort_seq
            ):
                sort_val = product.product_tmpl_id.sort_seq

        try:
            sort_int = int(sort_val)
            return sort_int if sort_int > 0 else None
        except (ValueError, TypeError):
            return None

    @api.model
    def _get_category_sort_key(self, categ_name):
        name = (categ_name or '').strip().upper()

        if 'FROZEN' in name:
            return (0, name)
        if 'FRESH' in name:
            return (1, name)

        return (2, name)

    # ------------------------------------------------------------------
    # Pagination - same MAX_PAGE_WEIGHT convention as the Factory Only
    # Packing List (report.tl_rf_reports.report_packing_list). Tune against
    # real print output if pages still break too early or too late.
    # ------------------------------------------------------------------
    @api.model
    def _paginate_batch_categories(self, category_list):
        MAX_PAGE_WEIGHT = 38

        pages = []
        current_page_categories = []
        current_weight = 0

        for cat in category_list:
            cat_name = cat['categ_name']
            products = cat['products']
            total_boxes = cat['total_boxes']

            prod_idx = 0
            total_prods = len(products)

            while prod_idx < total_prods:
                cat_header_cost = 2.5

                if (
                    current_page_categories
                    and (current_weight + cat_header_cost + 1 > MAX_PAGE_WEIGHT)
                ):
                    pages.append({
                        'categories': current_page_categories,
                        'is_last_page': False,
                    })
                    current_page_categories = []
                    current_weight = 0

                available_weight = MAX_PAGE_WEIGHT - current_weight - cat_header_cost
                if available_weight < 1:
                    available_weight = 1

                num_to_take = min(int(available_weight), total_prods - prod_idx)
                chunk_prods = products[prod_idx:prod_idx + num_to_take]
                prod_idx += num_to_take

                is_cat_complete = prod_idx >= total_prods

                current_page_categories.append({
                    'categ_name': cat_name,
                    'products': chunk_prods,
                    'is_complete': is_cat_complete,
                    'total_boxes': total_boxes if is_cat_complete else False,
                })

                current_weight += (
                    cat_header_cost
                    + len(chunk_prods)
                    + (1.5 if is_cat_complete else 0)
                )

                if prod_idx < total_prods:
                    pages.append({
                        'categories': current_page_categories,
                        'is_last_page': False,
                    })
                    current_page_categories = []
                    current_weight = 0

        if current_page_categories:
            pages.append({
                'categories': current_page_categories,
                'is_last_page': True,
            })
        elif pages:
            pages[-1]['is_last_page'] = True

        return pages

    @api.model
    def _number_pages_continuously(self, groups):
        flat_pages = [pg for g in groups for pg in g['pages']]
        total_pages = len(flat_pages)

        for idx, pg in enumerate(flat_pages, start=1):
            pg['page_number'] = idx
            pg['total_pages'] = total_pages

        return groups

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------
    @api.model
    def _get_report_values(self, docids, data=None):
        docs = self.env['packing.list.wizard'].browse(docids)

        now_utc = fields.Datetime.now()
        now_local = fields.Datetime.context_timestamp(self, now_utc)
        printed_at_str = now_local.strftime('%d/%m/%Y %H:%M:%S')

        all_batch_groups = []
        bom_cache = {}

        for wizard in docs:

            batch_domain = [
                ('delivery_date', '>=', wizard.delivery_date_from),
                ('delivery_date', '<=', wizard.delivery_date_to),
            ]
            if wizard.depot_ids:
                batch_domain.append(('depot_id', 'in', wizard.depot_ids.ids))

            batches = self.env['round.management.batch'].search(
                batch_domain, order='delivery_date asc, code asc'
            )

            for batch in batches:

                # Driver Packing List: Regal Van Delivery only. Both Normal
                # and Late orders are included - no is_late_order filter.
                orders = batch.order_ids.filtered(
                    lambda so: so.state in ('sale', 'done')
                    and getattr(so, 'delivery_channel', False) in ('regal_van', False)
                )

                if not orders:
                    continue

                categories_map = {}

                for order in orders:

                    for line in order.order_line.filtered(
                        lambda l: not l.display_type and l.product_id
                    ):
                        product = line.product_id
                        qty = line.product_uom_qty or 0.0
                        if not qty:
                            continue

                        # BOM Product Logic (functional spec section 4):
                        # No BOM / Manufacture-type -> product unchanged.
                        # Kit-type -> exploded into components.
                        reporting_items = self._explode_bom(product, qty, bom_cache)

                        for item_product, item_qty in reporting_items:

                            categ = item_product.categ_id
                            categ_name = (
                                (categ.name or _('Other')).strip().upper()
                                if categ else 'OTHER'
                            )
                            categ_key = categ.id if categ else 0

                            if categ_key not in categories_map:
                                categories_map[categ_key] = {
                                    'categ_name': categ_name,
                                    'products': {},
                                }

                            prod_key = item_product.id

                            # Quantity Consolidation (functional spec
                            # section 5): same product/component across
                            # multiple order lines within this batch is
                            # summed into a single row.
                            if prod_key not in categories_map[categ_key]['products']:
                                sort_num = self._extract_sort_number(item_product)
                                categories_map[categ_key]['products'][prod_key] = {
                                    'product_id': prod_key,
                                    'product_name': item_product.name,
                                    'box_qty': 0.0,
                                    'sort_num': sort_num,
                                    'sort_str': str(sort_num) if sort_num else '',
                                }

                            categories_map[categ_key]['products'][prod_key]['box_qty'] += item_qty

                category_list = []
                batch_total_boxes = 0

                for c_key, c_val in sorted(
                    categories_map.items(),
                    key=lambda item: self._get_category_sort_key(item[1]['categ_name'])
                ):
                    sorted_prods = sorted(c_val['products'].values(), key=self._get_sort_key)

                    for p in sorted_prods:
                        # Always shown with 2 decimal places (e.g. "4.00",
                        # "11.00"), matching the expected Driver Packing
                        # List output - unlike the standard Packing List,
                        # which prints whole numbers without decimals.
                        p['qty_display'] = f"{p['box_qty']:.2f}"

                    cat_total = int(round(sum(p['box_qty'] for p in sorted_prods)))
                    batch_total_boxes += cat_total

                    if sorted_prods:
                        category_list.append({
                            'categ_name': c_val['categ_name'],
                            'products': sorted_prods,
                            'total_boxes': cat_total,
                        })

                if category_list:
                    depot_name = batch.depot_id.name if batch.depot_id else 'Grimsby'
                    delivery_date_str = (
                        batch.delivery_date.strftime('%d/%m/%Y') if batch.delivery_date else ''
                    )
                    batch_code = batch.code or ''
                    batch_name = (
                        batch.round_id.name
                        if (batch.round_id and batch.round_id.name)
                        else (batch.reference or '')
                    )

                    batch_pages = self._paginate_batch_categories(category_list)

                    all_batch_groups.append({
                        'delivery_date': delivery_date_str,
                        'depot_name': depot_name,
                        'batch_code': batch_code,
                        'batch_name': batch_name,
                        'pages': batch_pages,
                        'total_boxes': batch_total_boxes,
                    })

        all_batch_groups = self._number_pages_continuously(all_batch_groups)

        return {
            'doc_ids': docids,
            'doc_model': 'packing.list.wizard',
            'docs': docs,
            'printed_at': printed_at_str,
            'batch_groups': all_batch_groups,
        }
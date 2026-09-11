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
        lang = self.env.lang or 'en_US'
        company_ids = tuple(self.env.companies.ids) if self.env.companies else (self.env.company.id,)

        for wizard in docs:
            depot_filter = ""
            params = {
                'date_from': wizard.delivery_date_from,
                'date_to': wizard.delivery_date_to,
                'company_ids': company_ids,
                'lang': lang,
            }
            if wizard.depot_ids:
                depot_filter = "AND b.depot_id IN %(depot_ids)s"
                params['depot_ids'] = tuple(wizard.depot_ids.ids)

            query = f"""
                SELECT 
                    b.id AS batch_id,
                    b.code AS batch_code,
                    b.reference AS batch_reference,
                    b.delivery_date AS batch_delivery_date,
                    sw.id AS depot_id,
                    sw.name AS depot_name,
                    rmr.id AS round_id,
                    rmr.name AS round_name,
                    so.id AS order_id,
                    sol.id AS line_id,
                    sol.product_uom_qty AS line_qty,
                    p.id AS product_id,
                    p.product_tmpl_id AS tmpl_id,
                    COALESCE(pt.name->>%(lang)s, pt.name->>'en_GB', pt.name->>'en_US', pt.name::text) AS product_name,
                    COALESCE(p.sort_seq, pt.sort_seq, 0) AS sort_num,
                    pc.id AS categ_id,
                    COALESCE(pc.name->>%(lang)s, pc.name->>'en_GB', pc.name->>'en_US', pc.name::text) AS categ_name
                FROM round_management_batch b
                LEFT JOIN stock_warehouse sw ON sw.id = b.depot_id
                LEFT JOIN round_management_round rmr ON rmr.id = b.round_id
                JOIN sale_order so ON so.batch_id = b.id 
                    AND so.state IN ('sale', 'done') 
                    AND (so.delivery_channel = 'regal_van' OR so.delivery_channel IS NULL)
                JOIN sale_order_line sol ON sol.order_id = so.id 
                    AND sol.display_type IS NULL 
                    AND sol.product_id IS NOT NULL 
                    AND sol.product_uom_qty > 0
                JOIN product_product p ON p.id = sol.product_id
                JOIN product_template pt ON pt.id = p.product_tmpl_id
                LEFT JOIN product_category pc ON pc.id = pt.categ_id
                WHERE b.delivery_date >= %(date_from)s 
                  AND b.delivery_date <= %(date_to)s
                  {depot_filter}
                  AND (b.company_id IS NULL OR b.company_id IN %(company_ids)s)
                ORDER BY b.delivery_date ASC, b.code ASC, b.id ASC
            """
            self.env.cr.execute(query, params)
            rows = self.env.cr.dictfetchall()

            if not rows:
                continue

            # Gather all unique product & template IDs to pre-fetch phantom BOMs in bulk
            product_ids = tuple({r['product_id'] for r in rows})
            tmpl_ids = tuple({r['tmpl_id'] for r in rows})

            bom_query = """
                SELECT 
                    mb.id AS bom_id,
                    mb.product_id AS bom_product_id,
                    mb.product_tmpl_id AS bom_tmpl_id,
                    COALESCE(mb.product_qty, 1.0) AS bom_qty,
                    mb.sequence AS bom_sequence,
                    mbl.id AS bom_line_id,
                    mbl.product_id AS comp_product_id,
                    mbl.product_qty AS comp_line_qty,
                    p_comp.product_tmpl_id AS comp_tmpl_id,
                    COALESCE(pt_comp.name->>%(lang)s, pt_comp.name->>'en_GB', pt_comp.name->>'en_US', pt_comp.name::text) AS comp_product_name,
                    COALESCE(p_comp.sort_seq, pt_comp.sort_seq, 0) AS comp_sort_num,
                    pc_comp.id AS comp_categ_id,
                    COALESCE(pc_comp.name->>%(lang)s, pc_comp.name->>'en_GB', pc_comp.name->>'en_US', pc_comp.name::text) AS comp_categ_name
                FROM mrp_bom mb
                JOIN mrp_bom_line mbl ON mbl.bom_id = mb.id
                JOIN product_product p_comp ON p_comp.id = mbl.product_id
                JOIN product_template pt_comp ON pt_comp.id = p_comp.product_tmpl_id
                LEFT JOIN product_category pc_comp ON pc_comp.id = pt_comp.categ_id
                WHERE mb.type = 'phantom'
                  AND mb.active = true
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

            # Map BOMs: variant-specific first, fallback to template
            variant_boms = {}
            tmpl_boms = {}
            for br in bom_rows:
                b_id = br['bom_id']
                if br['bom_product_id']:
                    if br['bom_product_id'] not in variant_boms:
                        variant_boms[br['bom_product_id']] = {'qty': br['bom_qty'], 'lines': []}
                    variant_boms[br['bom_product_id']]['lines'].append(br)
                elif br['bom_tmpl_id']:
                    if br['bom_tmpl_id'] not in tmpl_boms:
                        tmpl_boms[br['bom_tmpl_id']] = {'qty': br['bom_qty'], 'lines': []}
                    tmpl_boms[br['bom_tmpl_id']]['lines'].append(br)

            # Group rows by batch
            batches_map = {}
            for r in rows:
                batch_id = r['batch_id']
                if batch_id not in batches_map:
                    batches_map[batch_id] = {
                        'batch_info': r,
                        'categories_map': {},
                    }

                b_map = batches_map[batch_id]
                qty = float(r['line_qty'] or 0.0)
                pid = r['product_id']
                tid = r['tmpl_id']

                # Check for phantom BOM explosion
                bom_info = variant_boms.get(pid) or tmpl_boms.get(tid)
                if bom_info and bom_info['lines']:
                    bom_produced_qty = bom_info['qty'] or 1.0
                    for comp in bom_info['lines']:
                        comp_qty = (comp['comp_line_qty'] / bom_produced_qty) * qty
                        if not comp_qty:
                            continue
                        categ_key = comp['comp_categ_id'] or 0
                        categ_name = (comp['comp_categ_name'] or _('Other')).strip().upper()
                        if categ_key not in b_map['categories_map']:
                            b_map['categories_map'][categ_key] = {
                                'categ_name': categ_name,
                                'products': {},
                            }
                        c_prods = b_map['categories_map'][categ_key]['products']
                        c_pid = comp['comp_product_id']
                        if c_pid not in c_prods:
                            sort_n = int(comp['comp_sort_num']) if comp['comp_sort_num'] and int(comp['comp_sort_num']) > 0 else None
                            c_prods[c_pid] = {
                                'product_id': c_pid,
                                'product_name': comp['comp_product_name'],
                                'box_qty': 0.0,
                                'sort_num': sort_n,
                                'sort_str': str(sort_n) if sort_n else '',
                            }
                        c_prods[c_pid]['box_qty'] += comp_qty
                else:
                    # Direct product
                    categ_key = r['categ_id'] or 0
                    categ_name = (r['categ_name'] or _('Other')).strip().upper()
                    if categ_key not in b_map['categories_map']:
                        b_map['categories_map'][categ_key] = {
                            'categ_name': categ_name,
                            'products': {},
                        }
                    c_prods = b_map['categories_map'][categ_key]['products']
                    if pid not in c_prods:
                        sort_n = int(r['sort_num']) if r['sort_num'] and int(r['sort_num']) > 0 else None
                        c_prods[pid] = {
                            'product_id': pid,
                            'product_name': r['product_name'],
                            'box_qty': 0.0,
                            'sort_num': sort_n,
                            'sort_str': str(sort_n) if sort_n else '',
                        }
                    c_prods[pid]['box_qty'] += qty

            # Format batches into output structure
            for batch_id, b_data in batches_map.items():
                categories_map = b_data['categories_map']
                category_list = []
                batch_total_boxes = 0

                for c_key, c_val in sorted(
                    categories_map.items(),
                    key=lambda item: self._get_category_sort_key(item[1]['categ_name'])
                ):
                    sorted_prods = sorted(c_val['products'].values(), key=self._get_sort_key)
                    for p in sorted_prods:
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
                    b_info = b_data['batch_info']
                    depot_name = b_info['depot_name'] or 'Grimsby'
                    delivery_date_str = (
                        b_info['batch_delivery_date'].strftime('%d/%m/%Y')
                        if b_info['batch_delivery_date']
                        else ''
                    )
                    batch_code = b_info['batch_code'] or ''
                    batch_name = b_info['round_name'] or b_info['batch_reference'] or ''

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
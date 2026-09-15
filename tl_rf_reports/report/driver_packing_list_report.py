# -*- coding: utf-8 -*-

import io
from xml.sax.saxutils import escape as xml_escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    Flowable, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

from odoo import api, fields, models, _


class _DriverPackingListHeaderMarker(Flowable):
    """Same technique as _PackingListHeaderMarker in packing_list_report.py -
    see report_delivery_note_round_van.py for the full explanation."""

    def __init__(self, header_text):
        super().__init__()
        self.header_text = header_text
        self.width = 0
        self.height = 0

    def wrap(self, availWidth, availHeight):
        return (0, 0)

    def draw(self):
        self.canv.current_header = self.header_text


class _DriverPackingListCanvas(canvas.Canvas):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []
        self.current_header = None

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self._draw_header()
            super().showPage()
        super().save()

    def _draw_header(self):
        if not self.current_header:
            return
        self.saveState()
        margin = 12 * mm
        width = A4[0] - (2 * margin)
        style = ParagraphStyle('DriverPackingListHeaderBand', fontName='Helvetica', fontSize=10, leading=13)
        p = Paragraph(self.current_header, style)
        _, h = p.wrap(width, 40 * mm)
        p.drawOn(self, margin, A4[1] - margin - h)
        self.restoreState()


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
                    pc.name AS categ_name
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
                    pc_comp.name AS comp_categ_name
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

    # ------------------------------------------------------------------
    # Fast path: builds the PDF directly with ReportLab instead of QWeb+
    # wkhtmltopdf. The raw-SQL + BOM-explosion data layer above is reused
    # as-is (already fast); only the *rendering* step changes. See
    # report_delivery_note_round_courier.py for the general approach and
    # report_delivery_note_round_van.py for the repeating-header-per-group
    # technique (_DriverPackingListHeaderMarker / _DriverPackingListCanvas
    # above are the same idea, renamed for this file).
    # ------------------------------------------------------------------
    PRINTABLE_WIDTH = A4[0] - (24 * mm)

    def _pdf_styles(self):
        return {
            'category': ParagraphStyle('DPLCategory', fontName='Helvetica-Bold', fontSize=12, leading=15),
            'col_header': ParagraphStyle('DPLColHeader', fontName='Helvetica-BoldOblique', fontSize=9, leading=11),
            'cell': ParagraphStyle('DPLCell', fontName='Helvetica', fontSize=10, leading=13),
            'cell_bold': ParagraphStyle('DPLCellBold', fontName='Helvetica-Bold', fontSize=10, leading=13),
            'total': ParagraphStyle('DPLTotal', fontName='Helvetica-Bold', fontSize=10, leading=13, alignment=2),
        }

    def generate_pdf(self, wizard):
        """Returns the finished PDF (bytes) for one Driver Packing List
        wizard, or None when there is nothing to print.

        Uses plain ORM search() + recordset iteration rather than raw SQL,
        reusing this class's own _find_bom/_explode_bom helpers (defined
        above) for the Kit-BOM explosion instead of a hand-written bulk BOM
        query - the ORM already knows how each field is actually translated/
        stored, so there's no risk of the "assumed jsonb, column is actually
        varchar" class of bug a hand-written query can hit."""
        batch_domain = [
            ('delivery_date', '>=', wizard.delivery_date_from),
            ('delivery_date', '<=', wizard.delivery_date_to),
        ]
        if wizard.depot_ids:
            batch_domain.append(('depot_id', 'in', wizard.depot_ids.ids))

        batches = self.env['round.management.batch'].search(
            batch_domain, order='delivery_date asc, code asc, id asc'
        )
        if not batches:
            return None

        bom_cache = {}
        batches_map = {}
        for batch in batches:
            orders = batch.order_ids.filtered(
                lambda so: so.state in ('sale', 'done')
                and getattr(so, 'delivery_channel', False) in ('regal_van', False)
            )
            if not orders:
                continue

            b_map = batches_map[batch.id] = {'batch': batch, 'categories_map': {}}
            for order in orders:
                lines = order.order_line.filtered(
                    lambda l: not l.display_type and l.product_id and l.product_uom_qty > 0
                )
                for line in lines:
                    for item_product, item_qty in self._explode_bom(line.product_id, line.product_uom_qty, bom_cache):
                        if not item_qty:
                            continue
                        categ_name = (item_product.categ_id.name or _('Other')).strip().upper()
                        categ_key = item_product.categ_id.id or 0
                        b_map['categories_map'].setdefault(categ_key, {'categ_name': categ_name, 'products': {}})
                        c_prods = b_map['categories_map'][categ_key]['products']
                        pid = item_product.id
                        if pid not in c_prods:
                            sort_num = self._extract_sort_number(item_product)
                            c_prods[pid] = {
                                'product_id': pid, 'product_name': item_product.name, 'box_qty': 0.0,
                                'sort_num': sort_num, 'sort_str': str(sort_num) if sort_num else '',
                            }
                        c_prods[pid]['box_qty'] += item_qty

        if not batches_map:
            return None

        styles = self._pdf_styles()
        width = self.PRINTABLE_WIDTH
        story = []
        printed_batches = 0

        for batch_id, b_data in batches_map.items():
            category_list = []
            batch_total_boxes = 0
            for c_key, c_val in sorted(
                b_data['categories_map'].items(), key=lambda item: self._get_category_sort_key(item[1]['categ_name'])
            ):
                sorted_prods = sorted(c_val['products'].values(), key=self._get_sort_key)
                for p in sorted_prods:
                    p['qty_display'] = f"{p['box_qty']:.2f}"
                cat_total = int(round(sum(p['box_qty'] for p in sorted_prods)))
                batch_total_boxes += cat_total
                if sorted_prods:
                    category_list.append({'categ_name': c_val['categ_name'], 'products': sorted_prods, 'total_boxes': cat_total})
            if not category_list:
                continue

            if printed_batches:
                story.append(PageBreak())
            printed_batches += 1

            batch = b_data['batch']
            depot_name = batch.depot_id.name or 'Grimsby'
            delivery_date_str = batch.delivery_date.strftime('%d/%m/%Y') if batch.delivery_date else ''
            batch_code = batch.code or ''
            batch_name = (batch.round_id.name if batch.round_id else False) or batch.reference or ''

            header_text = (
                f"<b>Drivers Packing List : Customer</b>&nbsp;&nbsp;&nbsp;{xml_escape(batch_code)}  {xml_escape(batch_name)}"
                f"<br/>Delivery On: {xml_escape(delivery_date_str)}"
                + (f"&nbsp;&nbsp;&nbsp;{xml_escape(depot_name)}" if depot_name else '')
            )
            story.append(_DriverPackingListHeaderMarker(header_text))
            story.append(Spacer(1, 14 * mm))

            for cat in category_list:
                header_row = Table(
                    [[Paragraph("Quantity", styles['col_header']), Paragraph("Product / Box Contents", styles['col_header']),
                      Paragraph("Sort", styles['col_header'])]],
                    colWidths=[width * 0.12, width * 0.76, width * 0.12],
                )
                header_row.setStyle(TableStyle([('LINEBELOW', (0, 0), (-1, 0), 1.5, colors.black)]))

                rows_ = [[
                    Paragraph(xml_escape(p['qty_display']), styles['cell_bold']),
                    Paragraph(xml_escape(p['product_name'] or ''), styles['cell']),
                    Paragraph(xml_escape(p['sort_str']), styles['cell']),
                ] for p in cat['products']]
                table = Table(rows_, colWidths=[width * 0.12, width * 0.76, width * 0.12])
                table.setStyle(TableStyle([
                    ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                    ('ALIGN', (0, 0), (0, -1), 'CENTER'),
                    ('ALIGN', (2, 0), (2, -1), 'RIGHT'),
                    ('LINEBELOW', (0, 0), (-1, -1), 0.5, colors.black),
                    ('TOPPADDING', (0, 0), (-1, -1), 2), ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
                ]))

                story.append(KeepTogether([
                    Paragraph(xml_escape(cat['categ_name']), styles['category']),
                    Spacer(1, 2 * mm), header_row, table,
                    Paragraph(f"{cat['total_boxes']} Boxes", styles['total']),
                    Spacer(1, 5 * mm),
                ]))

            story.append(Spacer(1, 8 * mm))
            story.append(Paragraph("Checked By _____________________", styles['total']))

        if not printed_batches:
            return None

        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer, pagesize=A4,
            leftMargin=12 * mm, rightMargin=12 * mm, topMargin=32 * mm, bottomMargin=12 * mm,
        )
        doc.build(story, canvasmaker=_DriverPackingListCanvas)
        pdf_value = buffer.getvalue()
        buffer.close()
        return pdf_value
import math
import re
from odoo import models, fields, api, _
from odoo.exceptions import UserError


class StockFreshBoxHistory(models.Model):
    _name = 'stock.fresh.box.history'
    _description = 'Pack Box Execution History Header'
    _order = 'wizard_date desc, id desc'

    wizard_date = fields.Datetime(string="Execution Date", default=fields.Datetime.now, required=True)
    user_id = fields.Many2one('res.users', string="User", default=lambda self: self.env.user)
    start_date = fields.Date(string="Start Date")
    end_date = fields.Date(string="End Date")
    delivery_channel = fields.Selection([
        ('courier', 'Courier Delivery'),
        ('regal_van', 'Regal Van Delivery')
    ], string="Delivery Channel")
    include_late_orders = fields.Boolean(string="Include Late Orders")
    total_analyzed_lines = fields.Integer(string="Total Lines")
    total_fresh_mos_created = fields.Integer(string="Fresh MOs Created")
    note = fields.Text(string="Execution Note")

    line_ids = fields.One2many('stock.fresh.box.history.line', 'history_id', string="History Lines")


class StockFreshBoxHistoryLine(models.Model):
    _name = 'stock.fresh.box.history.line'
    _description = 'Pack Box Detailed History Line'

    history_id = fields.Many2one('stock.fresh.box.history', string="History Record", ondelete='cascade')
    sale_order_id = fields.Many2one('sale.order', string="Sales Order", store=True)
    sale_line_id = fields.Many2one('sale.order.line', string="Sales Order Line", store=True)
    
    special_requirements_notes_id = fields.Many2one('sale.order.special.note', string="Special Notes", store=True)
    
    order_number = fields.Char(string="Order Number", store=True)
    customer_code = fields.Char(string="Customer Code", store=True)
    round_batch_id = fields.Many2one('round.management.batch', string="Round Batch", store=True)
    round_id = fields.Many2one('round.management.round', string="Delivery Round", store=True)
    delivery_date = fields.Date(string="Delivery Date", store=True)
    delivery_channel = fields.Selection([
        ('courier', 'Courier Delivery'),
        ('regal_van', 'Regal Van Delivery')
    ], string="Delivery Channel", store=True)
    depot = fields.Char(string="Depot", store=True)
    is_late_order = fields.Boolean(string="Late Order", store=True)
    late_status = fields.Char(string="Late Status", store=True)

    product_id = fields.Many2one('product.product', string="Product", store=True)
    product_code = fields.Char(string="Product Code", store=True)
    product_name = fields.Char(string="Product Name", store=True)
    product_desc = fields.Char(string="Description", store=True)
    is_assembly = fields.Char(string="Assembly / Component (A/C)", store=True)
    uom_id = fields.Many2one('uom.uom', string="UOM", store=True)
    box_id = fields.Char(string="Box ID", store=True)
    category_id = fields.Many2one('product.category', string="Category", store=True)

    box_number = fields.Char(string="Box Label", store=True)
    box_weight = fields.Float(string="Box Weight / Qty", digits=(16, 3), store=True)


class StockFreshBoxWizard(models.TransientModel):
    _name = 'stock.fresh.box.wizard'
    _description = 'Pack Box and MO Generator Wizard'

    start_date = fields.Date(string="Delivery Start Date", required=True, default=fields.Date.context_today)
    end_date = fields.Date(string="Delivery End Date", required=True, default=fields.Date.context_today)
    delivery_channel = fields.Selection([
        ('regal_van', 'Regal Van Delivery'),
        ('courier', 'Courier Delivery'),
    ], string="Delivery Channel", required=True, default='regal_van')

    is_late_order = fields.Boolean(string="Late Order", default=False)
    line_ids = fields.One2many('stock.fresh.box.wizard.line', 'wizard_id', string="Analysis Lines")

    def _is_weight_uom(self, uom):
        if not uom:
            return False
        
        category = getattr(uom, 'category_id', False) or getattr(uom, 'uom_category_id', False)
        if category:
            category_name = (getattr(category, 'name', '') or '').lower()
            measure_type = getattr(category, 'measure_type', '') or getattr(category, 'uom_type', '')
            if 'weight' in category_name or measure_type == 'weight':
                return True
        
        uom_name = (getattr(uom, 'name', '') or '').strip().lower()
        uom_symbol = (getattr(uom, 'symbol', '') or '').strip().lower()
        
        weight_keywords = {'kg', 'kgs', 'kg(s)', 'kilo', 'kilogram', 'kilograms', 'g', 'gram', 'grams', 'lb', 'lbs', 'pound', 'pounds'}
    
        return uom_name in weight_keywords or uom_symbol in weight_keywords

    def _is_chilled_category(self, product):
        """Helper to check if a product belongs to the 'Chilled' category hierarchy."""
        category_name = (product.categ_id.complete_name or product.categ_id.name or '').lower() if product.categ_id else ''
        return 'chilled' in category_name

    def _get_line_effective_weight(self, line, ordered_qty=None):
        product = line.product_id
        if ordered_qty is None:
            ordered_qty = line.product_uom_qty

        match_pack_kg = re.search(r'(\d+(?:\.\d+)?)\s*(?:KG|Kilo)', product.name or '', re.IGNORECASE)
        if match_pack_kg:
            return ordered_qty * float(match_pack_kg.group(1))
        
        note_rel = getattr(line, 'special_requirements_notes_id', False)
        note_text_val = note_rel.display_name or note_rel.name if note_rel else ''

        notes_to_check = [
            note_text_val,
            line.name or ''
        ]

        for note_text in notes_to_check:
            match_note_kg = re.search(r'SPLIT\s+WITH\s+(\d+(?:\.\d+)?)\s*KG', note_text, re.IGNORECASE)
            if match_note_kg:
                return float(match_note_kg.group(1))

        return ordered_qty

    def action_analyze_orders(self):
        self.ensure_one()
        self.line_ids.unlink()

        domain = [
            ('order_id.state', 'in', ['sale', 'done']),
            ('order_id.delivery_channel', '=', self.delivery_channel),
        ]

        domain.extend([
            ('order_id.delivery_date', '>=', self.start_date),
            ('order_id.delivery_date', '<=', self.end_date),
        ])
        if self.is_late_order:
            domain.append(('is_late_order', '=', self.is_late_order))

        order_lines = self.env['sale.order.line'].search(domain)
        if not order_lines:
            raise UserError(_("No order lines found matching the selected criteria."))

        invalid_batches_info = []
        validated_batches = set()

        for line in order_lines:
            order = line.order_id
            batch = getattr(order, 'batch_id', False) or getattr(order, 'round_batch_id', False)

            if not batch or batch.id in validated_batches:
                continue

            is_late = getattr(order, 'is_late_order', False)
            batch_state = batch.state

            state_field = batch._fields.get('state')
            state_label = dict(state_field.selection).get(batch_state, batch_state) if hasattr(state_field, 'selection') else batch_state

            if batch_state != 'prt':
                invalid_batches_info.append(
                    f"• Batch '{batch.display_name}' (Order: {order.name}) is in '{state_label}' state. Required: Printed."
                )
            # if not is_late and batch_state != 'prt':
            #     invalid_batches_info.append(
            #         f"• Batch '{batch.display_name}' (Order: {order.name}) is in '{state_label}' state. Required: Printed."
            #     )
            # elif is_late and batch_state not in ['com', 'done', 'completed']:
            #     invalid_batches_info.append(
            #         f"• Batch '{batch.display_name}' [Late Order: {order.name}] is in '{state_label}' state. Required: Completed."
            #     )

            validated_batches.add(batch.id)

        if invalid_batches_info:
            error_msg = _(
                "Pack Box Validation Failed!\n"
                "The following batches do not meet the required batch status criteria:\n\n"
                "%(batches)s\n\n"
                "Please update the batch statuses before proceeding.",
                batches="\n".join(invalid_batches_info)
            )
            raise UserError(error_msg)

        mrp_bom_obj = self.env['mrp.bom']
        unique_products = order_lines.mapped('product_id')
        boms_per_product = mrp_bom_obj._bom_find(unique_products)

        wizard_line_vals = []

        for line in order_lines:
            order = line.order_id
            product = line.product_id

            partner = order.partner_id
            customer_code_val = getattr(partner, 'customer_code', False) or partner.ref or partner.name or ''
            round_batch = getattr(order, 'batch_id', False) or getattr(order, 'round_batch_id', False)
            round_obj = getattr(order, 'round_id', False)
            depot_val = getattr(order, 'depot', False) or (order.warehouse_id.name if order.warehouse_id else '')
            box_id = getattr(line, 'box_id', False) or getattr(order, 'box_id', False)

            raw_assembly = (
                getattr(product, 'assembly_type', False) or 
                getattr(product.product_tmpl_id, 'assembly_type', False) or 
                getattr(line, 'is_assembly', False) or 
                getattr(line, 'assembly_type', False) or 
                ''
            )
            raw_assembly = str(raw_assembly).strip().upper()
            assembly_val = raw_assembly if raw_assembly in ['A', 'B', 'C'] else ''

            line_uom = getattr(line, 'product_uom_id', False) or line.product_id.uom_id
            note_rel = getattr(line, 'special_requirements_notes_id', False)

            base_vals = {
                'wizard_id': self.id,
                'sale_order_id': order.id,
                'sale_line_id': line.id,
                'order_number': order.name,
                'customer_code': customer_code_val,
                'special_requirements_notes_id': note_rel.id if note_rel else False,
                'round_batch_id': round_batch.id if round_batch else False,
                'round_id': round_obj.id if round_obj else False,
                'delivery_date': getattr(order, 'delivery_date', False),
                'depot': depot_val,
                'late_status': getattr(order, 'late_status', ''),
                'product_id': product.id,
                'product_code': product.default_code or '',
                'product_name': product.name,
                'product_desc': line.name,
                'is_assembly': assembly_val,
                'uom_id': line_uom.id,
                'box_id': str(box_id) if box_id else '',
                'category_id': product.categ_id.id if product.categ_id else False,
            }

            has_bom = bool(boms_per_product.get(product))
            is_kg_uom = self._is_weight_uom(line_uom)

            # late_qty_delta says how much of product_uom_qty is a late
            # addition made after confirmed_qty was locked in - e.g. qty=4,
            # late_qty_delta=1.5 means 2.5 is the normal (already-confirmed)
            # portion and 1.5 is the late one. The two portions are boxed
            # SEPARATELY below so a fractional boundary (2.5 -> 1/1/0.5)
            # doesn't get swallowed into uniform 1kg/1-unit boxes cut from
            # the combined total.
            late_qty_delta = line.late_qty_delta or 0.0

            if self.is_late_order:
                # Wizard is filtering Late Orders only - the normal portion
                # was already boxed in an earlier (non-late) run, so only
                # the added/late quantity itself should be packed here.
                normal_qty = 0.0
                late_qty = late_qty_delta
            else:
                late_qty = late_qty_delta if late_qty_delta > 0 else 0.0
                normal_qty = max(0.0, line.product_uom_qty - late_qty)

            # 1. ONLY KG/Weight UOM items with BoM get split
            if has_bom and is_kg_uom:
                total_qty = normal_qty + late_qty
                total_weight = self._get_line_effective_weight(line, total_qty)
                if total_weight <= 0:
                    continue

                # Split the effective weight proportionally between the
                # normal and late portions, then box each portion on its
                # own (up to 1kg per box).
                late_weight = (total_weight * (late_qty / total_qty)) if total_qty > 0 else 0.0
                normal_weight = total_weight - late_weight

                max_box_capacity = 1.0
                box_specs = []
                for portion_weight, is_late in ((normal_weight, False), (late_weight, True)):
                    remaining_weight = portion_weight
                    n_boxes = math.ceil(portion_weight / max_box_capacity) if portion_weight > 0 else 0
                    for _box_idx in range(n_boxes):
                        box_weight = min(remaining_weight, max_box_capacity)
                        remaining_weight = max(0.0, remaining_weight - box_weight)
                        box_specs.append((box_weight, is_late))

                number_of_boxes = len(box_specs)
                for box_no, (box_weight, is_late) in enumerate(box_specs, start=1):
                    line_dict = base_vals.copy()
                    line_dict.update({
                        'box_number': f"Box {box_no}/{number_of_boxes}",
                        'box_weight': round(box_weight, 3),
                        'is_late_order': is_late,
                    })
                    wizard_line_vals.append(line_dict)

            # 2. Non-KG UOMs (EACH/Units, etc.) or items without BoM stay whole
            else:
                for portion_qty, is_late in ((normal_qty, False), (late_qty, True)):
                    if portion_qty <= 0:
                        continue
                    line_dict = base_vals.copy()
                    line_dict.update({
                        'box_number': "Full Bulk",
                        'box_weight': round(portion_qty, 3),
                        'is_late_order': is_late,
                    })
                    wizard_line_vals.append(line_dict)

        if wizard_line_vals:
            self.env['stock.fresh.box.wizard.line'].create(wizard_line_vals)

        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_generate_mo(self):
        self.ensure_one()
        if not self.line_ids:
            raise UserError(_("No lines available to analyze or generate Manufacturing Orders."))

        mrp_bom_obj = self.env['mrp.bom']
        mrp_production_obj = self.env['mrp.production']

        unique_products = self.line_ids.mapped('product_id')
        boms_per_product = mrp_bom_obj._bom_find(unique_products)

        # Accepts lines that have a BoM AND are either KG UOM OR in the Chilled category
        lines_to_generate_mo = self.line_ids.filtered(
            lambda l: boms_per_product.get(l.product_id) and (
                self._is_weight_uom(l.uom_id) or self._is_chilled_category(l.product_id)
            )
        )

        if not lines_to_generate_mo:
            raise UserError(_("No items with a valid BoM (KG Weight or Chilled Category) were found to generate MOs."))

        domain = [
            ('delivery_date', '>=', self.start_date),
            ('delivery_date', '<=', self.end_date),
            ('delivery_channel', '=', self.delivery_channel),
            ('state', 'in', ['draft', 'confirmed']),
            # Scoped to the sale lines this run is actually processing, not
            # is_late_order - a Late-Order-only run only recomputes a
            # line's late boxes, but every MO of that SAME line (its
            # pre-existing normal ones included) shares one running
            # "Box N/M" total, so all of them need to be seen and kept in
            # sync below. Restricting to these lines (rather than fetching
            # every MO in the date/channel/state range) keeps unrelated
            # lines' MOs - which this run never touches - out of the purge
            # step further down.
            ('production_sale_line_id', 'in', lines_to_generate_mo.mapped('sale_line_id').ids),
        ]
        existing_mos = mrp_production_obj.search(domain)

        # Grouped by the sale order line they were generated for -
        # production_sale_line_id is a stable relation, unlike matching the
        # "Box N/M" text in origin (which is what changes across runs).
        existing_mos_by_line = {}
        for mo in existing_mos:
            if mo.production_sale_line_id:
                existing_mos_by_line.setdefault(mo.production_sale_line_id.id, mrp_production_obj)
                existing_mos_by_line[mo.production_sale_line_id.id] |= mo

        lines_by_sale_line = {}
        for line in lines_to_generate_mo:
            lines_by_sale_line.setdefault(line.sale_line_id.id, self.env['stock.fresh.box.wizard.line'])
            lines_by_sale_line[line.sale_line_id.id] |= line

        processed_mos = self.env['mrp.production']

        def _reconcile(wiz_subset, pool):
            """Reuses/updates as many of `pool`'s MOs as `wiz_subset` has
            lines (oldest first), creating extras when there are more
            lines than MOs. Origin is set/refreshed by the caller once the
            line's full (normal + late) box order is known."""
            result = []
            for line in wiz_subset:
                if pool:
                    mo = pool.pop(0)
                    mo_vals = {}
                    if mo.is_late_order != line.is_late_order:
                        mo_vals['is_late_order'] = line.is_late_order
                    if mo.product_qty != line.box_weight:
                        mo_vals['product_qty'] = line.box_weight
                    if mo_vals:
                        mo.write(mo_vals)
                    result.append(mo)
                else:
                    bom = boms_per_product.get(line.product_id)
                    new_mo = mrp_production_obj.create({
                        'product_id': line.product_id.id,
                        'product_qty': line.box_weight,
                        'product_uom_id': line.uom_id.id,
                        'production_sale_line_id': line.sale_line_id.id,
                        'bom_id': bom.id if bom else False,
                        'is_late_order': line.is_late_order,
                    })
                    result.append(new_mo)
            return result

        for sale_line_id, wiz_lines in lines_by_sale_line.items():
            line_mos = existing_mos_by_line.get(sale_line_id, mrp_production_obj).sorted('id')
            normal_pool = list(line_mos.filtered(lambda m: not m.is_late_order))
            late_pool = list(line_mos.filtered(lambda m: m.is_late_order))

            wiz_normal = wiz_lines.filtered(lambda l: not l.is_late_order)
            wiz_late = wiz_lines.filtered(lambda l: l.is_late_order)

            # A category this run didn't touch (e.g. the normal boxes
            # during a Late-Order-only run) keeps its existing MOs as-is,
            # aside from the origin renumbering below - they must NOT be
            # left out of processed_mos or they'd be purged as "obsolete".
            final_normal = _reconcile(wiz_normal, normal_pool) if wiz_normal else normal_pool
            final_late = _reconcile(wiz_late, late_pool) if wiz_late else late_pool

            sample_line = wiz_lines[0]
            cat_prefix = f"[{sample_line.category_id.name}] " if sample_line.category_id else ""
            is_boxed_line = sample_line.box_number.startswith('Box ')
            ordered_mos = final_normal + final_late
            total_boxes = len(ordered_mos)

            for box_no, mo in enumerate(ordered_mos, start=1):
                box_label = f"Box {box_no}/{total_boxes}" if is_boxed_line else "Full Bulk"
                late_suffix = ' - late order' if mo.is_late_order else ''
                origin_ref = f"{cat_prefix}{sample_line.order_number} (Line {sale_line_id}) - {box_label}{late_suffix}"
                if mo.origin != origin_ref:
                    mo.write({'origin': origin_ref})
                processed_mos |= mo

        mo_to_purge = existing_mos - processed_mos
        for old_mo in mo_to_purge:
            if old_mo.state == 'draft':
                old_mo.action_cancel()
                old_mo.unlink()
            elif old_mo.state == 'confirmed':
                old_mo.action_cancel()

        history_rec = self.env['stock.fresh.box.history'].create({
            'start_date': self.start_date,
            'end_date': self.end_date,
            'delivery_channel': self.delivery_channel,
            'include_late_orders': self.is_late_order,
            'total_analyzed_lines': len(self.line_ids),
            'total_fresh_mos_created': len(processed_mos),
            'note': f"Processed {len(self.line_ids)} lines. Created/Updated {len(processed_mos)} MOs. Purged {len(mo_to_purge)} obsolete MOs."
        })

        history_line_vals = [
            {
                'history_id': history_rec.id,
                'sale_order_id': line.sale_order_id.id,
                'sale_line_id': line.sale_line_id.id,
                'order_number': line.order_number,
                'customer_code': line.customer_code,
                'round_batch_id': line.round_batch_id.id if line.round_batch_id else False,
                'round_id': line.round_id.id if line.round_id else False,
                'delivery_date': line.delivery_date or self.start_date,
                'delivery_channel': self.delivery_channel,
                'depot': line.depot or (line.sale_order_id.warehouse_id.name if line.sale_order_id and line.sale_order_id.warehouse_id else ''),
                'is_late_order': line.is_late_order,
                'late_status': line.late_status,

                'product_id': line.product_id.id,
                'product_code': line.product_code,
                'product_name': line.product_name,
                'product_desc': line.product_desc,
                'is_assembly': line.is_assembly,
                'uom_id': line.uom_id.id,
                'box_id': line.box_id,
                'category_id': line.category_id.id if line.category_id else False,
                'box_number': line.box_number,
                'box_weight': line.box_weight,
                'special_requirements_notes_id': line.special_requirements_notes_id.id if line.special_requirements_notes_id else False,
            } for line in self.line_ids
        ]

        if history_line_vals:
            self.env['stock.fresh.box.history.line'].create(history_line_vals)

        return {
            'name': _('Pack Box Split MOs'),
            'type': 'ir.actions.act_window',
            'res_model': 'mrp.production',
            'view_mode': 'list,form',
            'domain': [('id', 'in', processed_mos.ids)],
            'context': {
                'search_default_groupby_delivery_date': 1,
                'search_default_groupby_product_category': 1,
                'search_default_groupby_delivery_channel': 1,
            },
            'target': 'current',
        }


class StockFreshBoxWizardLine(models.TransientModel):
    _name = 'stock.fresh.box.wizard.line'
    _description = 'Pack Box Wizard Analysis Line'

    wizard_id = fields.Many2one('stock.fresh.box.wizard', string="Wizard Reference", ondelete='cascade')
    sale_order_id = fields.Many2one('sale.order', string="Sales Order")
    sale_line_id = fields.Many2one('sale.order.line', string="Order Line")
    
    special_requirements_notes_id = fields.Many2one('sale.order.special.note', string="Special Notes")

    # Header Info
    order_number = fields.Char(string="Order Number")
    customer_code = fields.Char(string="Customer Code")
    round_id = fields.Many2one('round.management.round', string="Delivery Round")
    round_batch_id = fields.Many2one('round.management.batch', string="Round Batch")
    delivery_date = fields.Date(string="Delivery Date")
    depot = fields.Char(string="Depot")
    is_late_order = fields.Boolean(string="Late Order")
    late_status = fields.Char(string="Late Status")

    # Product & Line Info
    product_id = fields.Many2one('product.product', string="Product")
    product_code = fields.Char(string="Product Code")
    product_name = fields.Char(string="Product Name")
    product_desc = fields.Char(string="Description")
    
    is_assembly = fields.Char(string="Assembly / Component (A/C)")
    
    uom_id = fields.Many2one('uom.uom', string="UOM")
    box_id = fields.Char(string="Box ID")
    category_id = fields.Many2one('product.category', string="Category")

    box_number = fields.Char(string="Box Label")
    box_weight = fields.Float(string="Box Weight / Qty", digits=(16, 3))


class MrpProduction(models.Model):
    _inherit = 'mrp.production'

    product_category_id = fields.Many2one(
        'product.category',
        string="Product Category",
        related='product_id.categ_id',
        store=True,
        readonly=True
    )

    delivery_date = fields.Date(
        string="Delivery Date",
        compute="_compute_delivery_info",
        store=True,
        readonly=True
    )

    delivery_channel = fields.Selection([
        ('regal_van', 'Regal Van Delivery'),
        ('courier', 'Courier Delivery'),
    ], string="Delivery Channel", compute="_compute_delivery_info", store=True, readonly=True)

    round_batch_id = fields.Many2one(
        'round.management.batch',
        string="Round Batch",
        compute="_compute_delivery_info",
        store=True,
        readonly=True
    )

    is_late_order = fields.Boolean(
        string="Late Order",
        # compute="_compute_delivery_info",
        store=True,
        readonly=True
    )
    production_sale_line_id = fields.Many2one(
        'sale.order.line',
        string='Sale Order Line',
        # compute='_compute_production_sale_line_id',
        store=True,
        readonly=True,
    )

    # Distinct from is_late_order above: that one is recomputed from the
    # resolved sale order's CURRENT is_late_order whenever origin changes,
    # so it can drift after the MO/its boxes already exist. late_order is a
    # plain, wizard-set flag - StockFreshBoxWizard.action_generate_mo simply
    # writes it to whatever "Include Late Orders" was checked to on that
    # generation run, so it stays a stable snapshot of how this MO was
    # generated.
    # late_order = fields.Boolean(string="Late Order (Generated As)")
    #
    @api.depends('origin')
    def _compute_delivery_info(self):
        for mo in self:
            so = False
            if mo.origin:
                match = re.search(r'\b[A-Za-z]{1,3}\d+\b', mo.origin)
                if match:
                    so_name = match.group(0)
                    so = self.env['sale.order'].search([('name', '=', so_name)], limit=1)

            if so:
                mo.delivery_date = getattr(so, 'delivery_date', False)
                mo.delivery_channel = getattr(so, 'delivery_channel', False)
                mo.round_batch_id = getattr(so, 'batch_id', False) or getattr(so, 'round_batch_id', False)
                # mo.is_late_order = getattr(so, 'is_late_order', False)
            else:
                mo.delivery_date = False
                mo.delivery_channel = False
                mo.round_batch_id = False
                # mo.is_late_order = False

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
        ('courier', 'Courier Delivery'),
        ('regal_van', 'Regal Van Delivery')
    ], string="Delivery Channel", required=True, default='courier')

    include_late_orders = fields.Boolean(string="Include Late Orders", default=False)
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

    def _is_chilled_or_each(self, product, uom):
        """Helper to detect discrete unit items (EACH/Units) or products under 'Chilled' category hierarchy."""
        category_name = (product.categ_id.complete_name or product.categ_id.name or '').lower() if product.categ_id else ''
        uom_name = (getattr(uom, 'name', '') or '').strip().lower()
        
        is_chilled_category = 'chilled' in category_name
        is_each_uom = uom_name in {'unit', 'units', 'each', 'pc', 'pcs', 'piece', 'pieces'}
        
        return is_chilled_category or is_each_uom

    def _get_line_effective_weight(self, line):
        product = line.product_id
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

        if self.include_late_orders:
            domain.extend([
                '|',
                ('order_id.is_late_order', '=', True),
                '&',
                ('order_id.delivery_date', '>=', self.start_date),
                ('order_id.delivery_date', '<=', self.end_date)
            ])
        else:
            domain.extend([
                ('order_id.delivery_date', '>=', self.start_date),
                ('order_id.delivery_date', '<=', self.end_date),
                ('order_id.is_late_order', '=', False)
            ])

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

            if not is_late and batch_state != 'prt':
                invalid_batches_info.append(
                    f"• Batch '{batch.display_name}' (Order: {order.name}) is in '{state_label}' state. Required: Printed."
                )
            elif is_late and batch_state not in ['com', 'done', 'completed']:
                invalid_batches_info.append(
                    f"• Batch '{batch.display_name}' [Late Order: {order.name}] is in '{state_label}' state. Required: Completed."
                )

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

            line_uom = line.product_uom_id if hasattr(line, 'product_uom_id') else product.uom_id
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
                'is_late_order': getattr(order, 'is_late_order', False),
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
            line_uom = getattr(line, 'product_uom_id', False) or line.product_id.uom_id
            is_kg_uom = self._is_weight_uom(line_uom)
            is_chilled_or_each = self._is_chilled_or_each(product, line_uom)

            # 1. Existing KG Weight Splitting (Unchanged)
            if has_bom and is_kg_uom:
                total_weight = self._get_line_effective_weight(line)
                if total_weight <= 0:
                    continue
                max_box_capacity = 1.0
                number_of_boxes = math.ceil(total_weight / max_box_capacity)
                remaining_weight = total_weight

                for box_no in range(1, number_of_boxes + 1):
                    box_weight = min(remaining_weight, max_box_capacity)
                    remaining_weight = max(0.0, remaining_weight - box_weight)

                    line_dict = base_vals.copy()
                    line_dict.update({
                        'box_number': f"Box {box_no}/{number_of_boxes}",
                        'box_weight': round(box_weight, 3),
                    })
                    wizard_line_vals.append(line_dict)

            # 2. Added: Chilled / EACH Category Unit Splitting for BoM Items
            elif has_bom and is_chilled_or_each:
                ordered_units = int(line.product_uom_qty) if line.product_uom_qty > 0 else 1
                for unit_no in range(1, ordered_units + 1):
                    line_dict = base_vals.copy()
                    line_dict.update({
                        'box_number': f"Unit {unit_no}/{ordered_units}" if ordered_units > 1 else "Single Unit",
                        'box_weight': 1.0,
                    })
                    wizard_line_vals.append(line_dict)

            # 3. Non-BoM / Bulk Products (Unchanged)
            else:
                total_qty = line.product_uom_qty
                if total_qty <= 0:
                    continue
                line_dict = base_vals.copy()
                line_dict.update({
                    'box_number': "Full Bulk",
                    'box_weight': round(total_qty, 3),
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

        # Updated filter: Accepts lines that have a BoM AND (are KG Weight OR are Chilled/EACH UOM)
        lines_to_generate_mo = self.line_ids.filtered(
            lambda l: boms_per_product.get(l.product_id) and (
                self._is_weight_uom(l.uom_id) or self._is_chilled_or_each(l.product_id, l.uom_id)
            )
        )

        if not lines_to_generate_mo:
            raise UserError(_("No items with a valid BoM (KG Weight or Chilled/EACH UOM) were found to generate MOs."))

        existing_mos = mrp_production_obj.search([
            ('delivery_date', '>=', self.start_date),
            ('delivery_date', '<=', self.end_date),
            ('delivery_channel', '=', self.delivery_channel),
            ('state', 'in', ['draft', 'confirmed'])
        ])

        existing_mo_map = {mo.origin: mo for mo in existing_mos if mo.origin}
        processed_mos = self.env['mrp.production']

        for line in lines_to_generate_mo:
            cat_prefix = f"[{line.category_id.name}] " if line.category_id else ""
            origin_ref = f"{cat_prefix}{line.order_number} (Line {line.sale_line_id.id}) - {line.box_number}"

            if origin_ref in existing_mo_map:
                existing_mo = existing_mo_map[origin_ref]
                if existing_mo.product_qty != line.box_weight:
                    existing_mo.write({'product_qty': line.box_weight})
                processed_mos |= existing_mo
            else:
                bom = boms_per_product.get(line.product_id)
                new_mo = mrp_production_obj.create({
                    'product_id': line.product_id.id,
                    'product_qty': line.box_weight,
                    'product_uom_id': line.uom_id.id,
                    'bom_id': bom.id if bom else False,
                    'origin': origin_ref,
                })
                processed_mos |= new_mo

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
            'include_late_orders': self.include_late_orders,
            'total_analyzed_lines': len(self.line_ids),
            'total_fresh_mos_created': len(processed_mos),
            'note': f"Processed {len(self.line_ids)} lines. Created/Updated {len(processed_mos)} MOs for BoM (KG & Chilled/EACH) items. Purged {len(mo_to_purge)} obsolete MOs."
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
        ('courier', 'Courier Delivery'),
        ('regal_van', 'Regal Van Delivery')
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
        compute="_compute_delivery_info",
        store=True,
        readonly=True
    )

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
                mo.is_late_order = getattr(so, 'is_late_order', False)
            else:
                mo.delivery_date = False
                mo.delivery_channel = False
                mo.round_batch_id = False
                mo.is_late_order = False

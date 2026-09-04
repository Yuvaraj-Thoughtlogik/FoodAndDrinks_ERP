import math
import re
from odoo import models, fields, api, _
from odoo.exceptions import UserError


class StockFreshBoxWizard(models.TransientModel):
    _name = 'stock.fresh.box.wizard'
    _description = 'Pack Box and MO Generator Wizard'

    start_date = fields.Date(string="Delivery Start Date", required=True, default=fields.Date.context_today)
    end_date = fields.Date(string="Delivery End Date", required=True, default=fields.Date.context_today)
    delivery_channel = fields.Selection([
        ('courier', 'Courier Delivery'),
        ('regal_van', 'Regal Van Delivery')
    ], string="Delivery Channel", required=True, default='courier')

    include_late_orders = fields.Boolean(
        string="Include Late Orders",
        default=False,
        help="If checked, explicitly fetches orders marked as Late Orders (is_late_order = True)."
    )

    line_ids = fields.One2many(
        'stock.fresh.box.wizard.line',
        'wizard_id',
        string="Box Breakdown Analysis"
    )

    def _get_line_effective_weight(self, line):
        product = line.product_id
        ordered_qty = line.product_uom_qty

        # Detect Pack weight in name (e.g., "2 Kilo Pack", "2 KG Pack")
        match_pack_kg = re.search(r'(\d+(?:\.\d+)?)\s*(?:KG|Kilo)', product.name or '', re.IGNORECASE)
        if match_pack_kg:
            return ordered_qty * float(match_pack_kg.group(1))

        # Detect Pack weight in special notes
        special_notes = getattr(line, 'special_notes', '') or getattr(line, 'name', '') or ''
        match_note_kg = re.search(r'SPLIT\s+WITH\s+(\d+(?:\.\d+)?)\s*KG', str(special_notes), re.IGNORECASE)
        if match_note_kg:
            return float(match_note_kg.group(1))

        return ordered_qty

    def action_analyze_orders(self):
        """Analyzes order lines across ALL product categories, properly filtering Late Orders from Sale Order."""
        self.ensure_one()
        self.line_ids.unlink()

        domain = [
            ('order_id.state', 'in', ['sale', 'done']),
            ('order_id.delivery_channel', '=', self.delivery_channel),
        ]

        if self.include_late_orders:
            # Include late orders regardless of date OR orders within date range
            domain.extend([
                '|',
                ('order_id.is_late_order', '=', True),
                '&',
                ('order_id.delivery_date', '>=', self.start_date),
                ('order_id.delivery_date', '<=', self.end_date)
            ])
        else:
            # Strictly filter within date range AND exclude late orders
            domain.extend([
                ('order_id.delivery_date', '>=', self.start_date),
                ('order_id.delivery_date', '<=', self.end_date),
                ('order_id.is_late_order', '=', False)
            ])

        order_lines = self.env['sale.order.line'].search(domain)
        wizard_line_vals = []

        for line in order_lines:
            total_weight = self._get_line_effective_weight(line)
            if total_weight <= 0:
                continue

            max_box_capacity = 1.0
            number_of_boxes = math.ceil(total_weight / max_box_capacity)
            remaining_weight = total_weight

            for box_no in range(1, number_of_boxes + 1):
                box_weight = max_box_capacity if remaining_weight >= max_box_capacity else remaining_weight
                remaining_weight -= box_weight

                wizard_line_vals.append({
                    'wizard_id': self.id,
                    'sale_order_id': line.order_id.id,
                    'sale_line_id': line.id,
                    'product_id': line.product_id.id,
                    'box_number': f"Box {box_no}/{number_of_boxes}",
                    'box_weight': round(box_weight, 3),
                    'category_id': line.product_id.categ_id.id,
                })

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
        """Generates Fresh MOs and saves detailed box breakdown lines to History."""
        self.ensure_one()
        if not self.line_ids:
            raise UserError(_("No lines available to analyze or generate Manufacturing Orders."))

        fresh_lines = self.line_ids.filtered(
            lambda l: l.category_id and 'fresh' in l.category_id.name.lower()
        )

        if not fresh_lines:
            raise UserError(_("No items under 'Fresh' categories were found to generate MOs."))

        mrp_production_obj = self.env['mrp.production']

        existing_mos = mrp_production_obj.search([
            ('delivery_date', '>=', self.start_date),
            ('delivery_date', '<=', self.end_date),
            ('delivery_channel', '=', self.delivery_channel),
            ('state', 'in', ['draft', 'confirmed'])
        ])

        existing_mo_map = {mo.origin: mo for mo in existing_mos if mo.origin}
        processed_mos = self.env['mrp.production']

        # Pre-fetch BOMs to prevent N+1 queries in the loop
        unique_products = fresh_lines.mapped('product_id')
        boms_per_product = self.env['mrp.bom']._bom_find(unique_products)

        for line in fresh_lines:
            origin_ref = f"[{line.category_id.name}] {line.sale_order_id.name} - {line.box_number}"

            if origin_ref in existing_mo_map:
                existing_mo = existing_mo_map[origin_ref]
                if existing_mo.product_qty != line.box_weight:
                    existing_mo.write({'product_qty': line.box_weight})
                processed_mos |= existing_mo
            else:
                bom = boms_per_product.get(line.product_id)
                mo_vals = {
                    'product_id': line.product_id.id,
                    'product_qty': line.box_weight,
                    'product_uom_id': line.product_id.uom_id.id,
                    'bom_id': bom.id if bom else False,
                    'origin': origin_ref,
                }
                new_mo = mrp_production_obj.create(mo_vals)
                processed_mos |= new_mo

        # Purge old obsolete draft MOs
        mo_to_purge = existing_mos - processed_mos
        for old_mo in mo_to_purge:
            if old_mo.state == 'draft':
                old_mo.action_cancel()
                old_mo.unlink()
            elif old_mo.state == 'confirmed':
                old_mo.action_cancel()

        # Create History Master Record
        history_vals = {
            'start_date': self.start_date,
            'end_date': self.end_date,
            'delivery_channel': self.delivery_channel,
            'include_late_orders': self.include_late_orders,
            'total_analyzed_lines': len(self.line_ids),
            'total_fresh_mos_created': len(processed_mos),
            'note': f"Processed {len(self.line_ids)} breakdown lines. Created {len(processed_mos)} Fresh MOs."
        }
        history_rec = self.env['stock.fresh.box.history'].create(history_vals)

        # Bulk insert history lines
        history_line_vals = [
            {
                'history_id': history_rec.id,
                'sale_order_id': line.sale_order_id.id,
                'product_id': line.product_id.id,
                'category_id': line.category_id.id,
                'box_number': line.box_number,
                'box_weight': line.box_weight,
                'delivery_date': getattr(line.sale_order_id, 'delivery_date', False) or self.start_date,
                'delivery_channel': self.delivery_channel,
            } for line in self.line_ids
        ]
        if history_line_vals:
            self.env['stock.fresh.box.history.line'].create(history_line_vals)

        return {
            'name': _('Pack Box Split Fresh MOs'),
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
    product_id = fields.Many2one('product.product', string="Product")
    category_id = fields.Many2one('product.category', string="Category")
    box_number = fields.Char(string="Box Label")
    box_weight = fields.Float(string="Box Weight (kg)", digits=(16, 3))


class StockFreshBoxHistory(models.Model):
    _name = 'stock.fresh.box.history'
    _description = 'Pack Box Execution History'
    _order = 'create_date desc'

    wizard_date = fields.Datetime(string="Run Date", default=fields.Datetime.now, readonly=True)
    user_id = fields.Many2one('res.users', string="User", default=lambda self: self.env.user, readonly=True)
    start_date = fields.Date(string="Start Date", readonly=True)
    end_date = fields.Date(string="End Date", readonly=True)
    delivery_channel = fields.Selection([
        ('courier', 'Courier Delivery'),
        ('regal_van', 'Regal Van Delivery')
    ], string="Delivery Channel", readonly=True)
    include_late_orders = fields.Boolean(string="Include Late Orders", readonly=True)
    total_analyzed_lines = fields.Integer(string="Total Lines Analyzed", readonly=True)
    total_fresh_mos_created = fields.Integer(string="Fresh MOs Created", readonly=True)
    note = fields.Text(string="Summary", readonly=True)

    line_ids = fields.One2many(
        'stock.fresh.box.history.line',
        'history_id',
        string="Box Breakdown Lines"
    )


class StockFreshBoxHistoryLine(models.Model):
    _name = 'stock.fresh.box.history.line'
    _description = 'Pack Box History Line Detail'

    history_id = fields.Many2one('stock.fresh.box.history', string="History Record", ondelete='cascade')
    sale_order_id = fields.Many2one('sale.order', string="Sales Order")
    product_id = fields.Many2one('product.product', string="Product")
    category_id = fields.Many2one(
        'product.category', 
        string="Product Category", 
        related='product_id.categ_id', 
        store=True, 
        readonly=True
    )
    box_number = fields.Char(string="Box Label")
    box_weight = fields.Float(string="Box Weight (kg)", digits=(16, 3))

    delivery_date = fields.Date(string="Delivery Date", store=True)
    delivery_channel = fields.Selection([
        ('courier', 'Courier Delivery'),
        ('regal_van', 'Regal Van Delivery')
    ], string="Delivery Channel", store=True)
    is_late_order = fields.Boolean(
        string="Late Order", 
        related='sale_order_id.is_late_order', 
        store=True
    )


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
                mo.round_batch_id = getattr(so, 'round_batch_id', False) or getattr(so, 'batch_id', False)
                # FIX: Read the actual is_late_order field directly from the sale order!
                mo.is_late_order = getattr(so, 'is_late_order', False)
            else:
                mo.delivery_date = False
                mo.delivery_channel = False
                mo.round_batch_id = False
                mo.is_late_order = False

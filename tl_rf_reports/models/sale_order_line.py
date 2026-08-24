# -*- coding: utf-8 -*-
import math
import re
from odoo import api, fields, models


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    box_qty = fields.Float(
        string="Box Qty",
        compute='_compute_box_qty',
        store=True,
        readonly=False,
        digits=(16, 0),
        help="Auto-calculated box quantity based on 1kg box capacity per unit multiplied by line quantity."
    )
    weight = fields.Float(
        string="Weight (Kg)",
        compute='_compute_weight',
        digits=(16, 2),
        help="Calculated weight in Kg based on unit weight and product quantity."
    )
    categ_id = fields.Many2one(
        'product.category',
        related='product_id.categ_id',
        string="Product Category",
        readonly=True,
    )
    depot_id = fields.Many2one(
        'stock.warehouse',
        related='order_id.batch_id.depot_id',
        string="Depot",
        readonly=True,
    )
    delivery_date = fields.Date(
        related='order_id.delivery_date',
        string="Delivery Date",
        readonly=True,
    )
    delivery_channel = fields.Selection(
        related='order_id.delivery_channel',
        string="Delivery Channel",
        readonly=True,
    )
    is_late_order = fields.Boolean(
        related='order_id.is_late_order',
        string="Late Order",
        readonly=True,
    )

    def _get_product_unit_weight_in_kg(self):
        """Extracts or calculates unit weight in kg for the order line's product."""
        self.ensure_one()
        product = self.product_id
        if not product:
            return 0.0

        # 0. Check if UoM is kg
        uom = self.product_uom_id if hasattr(self, 'product_uom_id') and self.product_uom_id else (product.uom_id if product else False)
        uom_name = (uom.name or '').strip().lower() if uom else ''
        if uom_name in ('kg', 'kgs', 'kilogram', 'kilograms'):
            return 1.0

        # 1. Product standard weight field
        if product.weight and product.weight > 0:
            return product.weight

        # 2. Check gross_net_weight or min_weight string attributes
        weight_str = False
        if getattr(self, 'gross_net_weight', False):
            weight_str = self.gross_net_weight
        elif getattr(product, 'gross_net_weight', False):
            weight_str = product.gross_net_weight
        elif getattr(self, 'min_weight', False):
            weight_str = self.min_weight
        elif getattr(product, 'min_weight', False):
            weight_str = product.min_weight

        if weight_str:
            weight_clean = str(weight_str).strip().lower()
            match = re.search(r"[-+]?\d*\.?\d+", weight_clean)
            if match:
                try:
                    num_val = float(match.group())
                    if 'g' in weight_clean and 'kg' not in weight_clean:
                        return num_val / 1000.0
                    return num_val
                except ValueError:
                    pass

        # 3. Fallback: Parse weight from product name (e.g. '125-140G', '1-1.2kg', '500g', '2kg')
        if product.name:
            g_range = re.search(r"(\d+)\s*-\s*(\d+)\s*g\b", product.name, re.IGNORECASE)
            if g_range:
                avg_g = (float(g_range.group(1)) + float(g_range.group(2))) / 2.0
                return avg_g / 1000.0
            g_single = re.search(r"(\d+(?:\.\d+)?)\s*g\b", product.name, re.IGNORECASE)
            if g_single:
                return float(g_single.group(1)) / 1000.0
            kg_range = re.search(r"(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)\s*kg\b", product.name, re.IGNORECASE)
            if kg_range:
                avg_kg = (float(kg_range.group(1)) + float(kg_range.group(2))) / 2.0
                return avg_kg
            kg_single = re.search(r"(\d+(?:\.\d+)?)\s*kg\b", product.name, re.IGNORECASE)
            if kg_single:
                return float(kg_single.group(1))

        return 0.0

    @api.depends('product_id', 'product_uom_qty', 'product_id.weight', 'product_uom_id')
    def _compute_weight(self):
        """Calculate total weight in kg for the order line."""
        for line in self:
            if not line.product_id or line.product_uom_qty <= 0:
                line.weight = 0.0
                continue
            unit_weight = line._get_product_unit_weight_in_kg()
            if unit_weight > 0:
                line.weight = round(unit_weight * line.product_uom_qty, 2)
            else:
                line.weight = round(line.product_uom_qty, 2)

    @api.depends('product_id', 'product_uom_qty', 'product_id.weight')
    def _compute_box_qty(self):
        """Calculate box qty by splitting total line weight into 1kg boxes.

        Formula:
            total_weight = product_unit_weight (kg) × line_qty
            box_qty      = ceil(total_weight / 1.0)

        Examples:
            Fillet Fish 2kg, qty=1  → 2 × 1 = 2kg  → 2 boxes
            Fillet Fish 2kg, qty=2  → 2 × 2 = 4kg  → 4 boxes
            Salmon 500g,     qty=3  → 0.5 × 3 = 1.5kg → 2 boxes
        """
        for line in self:
            if not line.product_id or line.product_uom_qty <= 0:
                line.box_qty = 0.0
                continue

            unit_weight = line._get_product_unit_weight_in_kg()

            if unit_weight <= 0:
                # Unknown weight — default to 1 box per unit
                line.box_qty = line.product_uom_qty
            else:
                total_weight_kg = unit_weight * line.product_uom_qty
                line.box_qty = math.ceil(total_weight_kg / 1.0)

    @api.onchange('product_id', 'product_uom_qty')
    def _onchange_product_compute_box_qty(self):
        """Immediately auto-fills box_qty and weight on user input in UI before saving."""
        for line in self:
            if line.product_id and line.product_uom_qty > 0:
                unit_weight = line._get_product_unit_weight_in_kg()
                if unit_weight > 0:
                    total_weight_kg = unit_weight * line.product_uom_qty
                    line.box_qty = math.ceil(total_weight_kg / 1.0)
                    line.weight = round(total_weight_kg, 2)
                else:
                    line.box_qty = line.product_uom_qty
                    line.weight = round(line.product_uom_qty, 2)

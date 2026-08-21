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

    def _get_product_unit_weight_in_kg(self):
        """Extracts or calculates unit weight in kg for the order line's product."""
        self.ensure_one()
        product = self.product_id
        if not product:
            return 0.0

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

        # 3. Fallback: Parse weight from product name (e.g. '2kg', '1-1.2kg', '500g')
        if product.name:
            kg_match = re.search(r"(\d+(?:\.\d+)?)\s*kg\b", product.name, re.IGNORECASE)
            if kg_match:
                return float(kg_match.group(1))
            g_match = re.search(r"(\d+(?:\.\d+)?)\s*g\b", product.name, re.IGNORECASE)
            if g_match:
                return float(g_match.group(1)) / 1000.0

        return 0.0

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
        """Immediately auto-fills box_qty on user input in UI before saving."""
        for line in self:
            if line.product_id and line.product_uom_qty > 0:
                unit_weight = line._get_product_unit_weight_in_kg()
                if unit_weight > 0:
                    total_weight_kg = unit_weight * line.product_uom_qty
                    line.box_qty = math.ceil(total_weight_kg / 1.0)
                else:
                    line.box_qty = line.product_uom_qty

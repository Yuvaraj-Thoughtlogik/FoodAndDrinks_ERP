# -*- coding: utf-8 -*-
import logging
import math
from odoo import api, fields, models

_logger = logging.getLogger(__name__)

class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    box_qty = fields.Float(
        string="Box Qty",
        compute='_compute_box_qty',
        store=True,
        readonly=False,
        digits=(16, 0),
        #help="Auto-calculated box quantity based on 1kg box capacity per unit multiplied by line quantity."
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
        store=True,
    )
    depot_id = fields.Many2one(
        'stock.warehouse',
        related='order_id.batch_id.depot_id',
        string="Depot",
        readonly=True,
        store=True,
    )
    delivery_date = fields.Date(
        related='order_id.delivery_date',
        string="Delivery Date",
        readonly=True,
        store=True,
    )
    delivery_channel = fields.Selection(
        related='order_id.delivery_channel',
        string="Delivery Channel",
        readonly=True,
        store=True,
    )
    is_late_order = fields.Boolean(
        related='order_id.is_late_order',
        string="Late Order",
        readonly=True,
        store=True,
    )

    def _get_product_unit_weight_in_kg(self):
        """Extracts unit weight in kg directly from the product."""
        self.ensure_one()
        return self.product_id.weight or 0.0

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

    @api.depends('product_id', 'product_uom_qty', 'product_id.weight','product_uom_id')
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
            uom_name = (line.product_uom_id.name or '').strip().lower() if line.product_uom_id else ''
            #_logger.info("[_compute_box_qty] Line %s: product=%s, qty=%s, uom=%s", line.id, line.product_id.display_name, line.product_uom_qty, uom_name)
            if uom_name == 'each':
                line.box_qty = line.product_uom_qty
                #_logger.info("[_compute_box_qty] Line %s (UoM 'each') -> box_qty: %s", line.id, line.box_qty)
                continue
            elif not line.product_id or line.product_uom_qty <= 0:
                line.box_qty = 0.0
                continue

            unit_weight = line._get_product_unit_weight_in_kg()
            #_logger.info("[_compute_box_qty] Line %s: unit_weight=%s, uom_name=%s", line.id, unit_weight, uom_name)

            if unit_weight <= 0:
                # Unknown weight — default to 1 box per unit
                line.box_qty = line.product_uom_qty
            elif uom_name == 'each':
                line.box_qty = line.product_uom_qty
            else:
                total_weight_kg = unit_weight * line.product_uom_qty
                line.box_qty = math.ceil(total_weight_kg / 1.0)
            #_logger.info("[_compute_box_qty] Line %s: final box_qty=%s", line.id, line.box_qty)

    @api.onchange('product_id', 'product_uom_qty', 'product_uom_id')
    def _onchange_product_compute_box_qty(self):
        """Immediately auto-fills box_qty and weight on user input in UI before saving."""
        for line in self:
            uom_name = (line.product_uom_id.name or '').strip().lower() if line.product_uom_id else ''
            #_logger.info("[_onchange_box_qty] Line %s: product=%s, qty=%s, uom=%s", line.id, line.product_id.display_name, line.product_uom_qty, uom_name)
            if uom_name == 'each':
                line.box_qty = line.product_uom_qty
                #_logger.info("[_onchange_box_qty] Line %s (UoM 'each') -> box_qty: %s", line.id, line.box_qty)
                continue
            elif line.product_id and line.product_uom_qty > 0:
                unit_weight = line._get_product_unit_weight_in_kg()
                #_logger.info("[_onchange_box_qty] Line %s: unit_weight=%s", line.id, unit_weight)
                if unit_weight > 0:
                    total_weight_kg = unit_weight * line.product_uom_qty
                    line.box_qty = math.ceil(total_weight_kg / 1.0)
                    line.weight = round(total_weight_kg, 2)
                else:
                    line.box_qty = line.product_uom_qty
                    line.weight = round(line.product_uom_qty, 2)
                #_logger.info("[_onchange_box_qty] Line %s: final box_qty=%s, weight=%s", line.id, line.box_qty, line.weight)


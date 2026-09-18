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
    confirmed_qty = fields.Float(
        string="Confirmed Qty",
        default=0.0,
        copy=False,
        compute="_compute_confirmed_qty",
        store=True,
        digits='Product Unit of Measure',
        help="Snapshot of the ordered quantity taken when the sale order was confirmed. "
             "Used to detect quantity changes made after confirmation.",
    )
    late_qty_delta = fields.Float(
        string="Late Qty Delta",
        compute='_compute_late_order',
        store=True,
        copy=False,
        digits='Product Unit of Measure',
        help="Current quantity minus the quantity confirmed at order confirmation. "
             "Only populated while the order is late (confirmed and its batch is Printed).",
    )
    late_order = fields.Boolean(
        string="Late Order",
        store=True,
        compute='_compute_late_order',
        copy=False,
        help="True when the order is confirmed and its batch is in Printed status.",
    )
    batch_id = fields.Many2one(
        comodel_name='round.management.batch',
        related='order_id.batch_id',
        store=True,
    )
    lock_line = fields.Boolean()

    @api.model_create_multi
    def create(self, vals_list):

        for val in vals_list:
            order_id = self.env['sale.order'].browse(val['order_id'])
            val['lock_line'] = (order_id.state == 'sale' and order_id.batch_id.state == 'prt') or order_id.is_late_order

        return super().create(vals_list)

    @api.depends('product_uom_qty','confirmed_qty')
    def _compute_late_order(self):
        for line in self:
            if line.lock_line:
                line.late_order = True
                line.late_qty_delta = line.product_uom_qty

            elif line.batch_id.state == 'prt' and line.order_id.state == 'sale' and line.product_uom_qty != line.confirmed_qty:
                line.late_order = True
                line.late_qty_delta = line.product_uom_qty - line.confirmed_qty
            else:
                line.late_qty_delta = 0.0
                line.late_order = False


    @api.depends('order_id.state','batch_id.state')
    def _compute_confirmed_qty(self):
        for rec in self:
            if rec.batch_id.state == 'prt' and rec.order_id.state == 'sale':
                rec.confirmed_qty = rec.product_uom_qty
            else:
                rec.confirmed_qty = 0.0


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

    @api.depends('product_uom_qty')
    def _compute_box_qty(self):
        """Box qty is simply the order quantity rounded up to the next
        whole box - 1 box per unit of qty, regardless of weight or UoM.

        Examples:
            qty=1   → 1 box
            qty=1.5 → 2 boxes
            qty=2.8 → 3 boxes
        """
        for line in self:
            line.box_qty = math.ceil(line.product_uom_qty) if line.product_uom_qty > 0 else 0.0


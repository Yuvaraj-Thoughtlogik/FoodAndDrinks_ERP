# -*- coding: utf-8 -*-
from odoo import fields, models


class SaleOrderLineReportLines(models.Model):
    _name = 'sale.order.line.report_lines'
    _description = 'Sale Order Line Report Line'

    sale_order_line_id = fields.Many2one(
        'sale.order.line',
        string='Sale Order Line',
        required=True,
        ondelete='cascade',
        index=True,
    )
    name = fields.Char(string='Name')
    product_id = fields.Many2one('product.product', string='Product')
    box_content = fields.Char(string='Box Content')
    qty = fields.Float(
        string='Quantity',
        digits='Product Unit of Measure',
        help="Raw numeric quantity this row represents (kg or units, "
             "depending on the source line/component) - box_content is "
             "the same value pre-formatted for display; this one is for "
             "reports that need to sum/group numerically.",
    )
    notes = fields.Char(string='Notes')
    late_order = fields.Boolean(
        string='Late Order',
        help="True for the extra row representing a line's late_qty_delta "
             "(quantity added after confirmed_qty was locked in) - the "
             "regular row(s) built from confirmed_qty/the line's MOs stay "
             "False.",
    )
    from_bom = fields.Boolean(
        string='From BoM',
        help="True when this row is one Manufacturing Order's raw-material "
             "component (qty is that MO's own consumption, so rows for the "
             "same product/notes are COUNTED - one row is one physical "
             "box). False for a plain non-BoM line's row, where qty IS the "
             "line's own quantity/delta and rows are SUMMED, not counted.",
    )

    # Related fields mirrored from the source sale order line, stored so
    # the Packing List report can filter/group directly on this model
    # (by depot, channel, delivery date, category, batch...) instead of
    # joining back through sale_order_line_id for every read.
    sale_order_id = fields.Many2one(
        'sale.order',
        string='Sales Order',
        related='sale_order_line_id.order_id',
        store=True,
        index=True,
    )
    order_partner_id = fields.Many2one(
        'res.partner',
        string='Customer',
        related='sale_order_line_id.order_id.partner_id',
        store=True,
    )
    delivery_channel = fields.Selection(
        related='sale_order_line_id.delivery_channel',
        string='Delivery Channel',
        store=True,
    )
    delivery_date = fields.Date(
        related='sale_order_line_id.delivery_date',
        string='Delivery Date',
        store=True,
    )
    depot_id = fields.Many2one(
        'stock.warehouse',
        string='Depot',
        related='sale_order_line_id.depot_id',
        store=True,
    )
    categ_id = fields.Many2one(
        'product.category',
        string='Product Category',
        related='product_id.categ_id',
        store=True,
    )
    batch_id = fields.Many2one(
        'round.management.batch',
        string='Round Batch',
        related='sale_order_line_id.batch_id',
        store=True,
    )

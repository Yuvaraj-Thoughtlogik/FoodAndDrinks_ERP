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
    notes = fields.Char(string='Notes')
    late_order = fields.Boolean(
        string='Late Order',
        help="True for the extra row representing a line's late_qty_delta "
             "(quantity added after confirmed_qty was locked in) - the "
             "regular row(s) built from confirmed_qty/the line's MOs stay "
             "False.",
    )

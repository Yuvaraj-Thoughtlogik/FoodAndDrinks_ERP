# requirement.report.line now tracks every PO line it created
# (purchase_line_ids) instead of a single purchase_order_id, so a quantity
# increase after the PO can be ordered as a balance instead of a duplicate
# line. Link the existing lines to the PO line of their product on the PO
# they already point to; the ORM write recomputes Purchased Qty / Balance /
# Purchase Order.
from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    lines = env['requirement.report.line'].search([('purchase_order_id', '!=', False), ('purchase_line_ids', '=', False)])
    for line in lines:
        po_lines = line.purchase_order_id.order_line.filtered(lambda pl: pl.product_id == line.product_id)
        if po_lines:
            line.purchase_line_ids = [(6, 0, po_lines.ids)]

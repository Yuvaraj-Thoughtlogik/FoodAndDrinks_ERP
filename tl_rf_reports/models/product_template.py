from odoo import models


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    def action_requirement_vendor_done(self):
        """'Save' of the Create Vendor pop-up opened from a Requirement Report
        line. The form is saved before this runs, so the new vendor is already
        on the product: assign it to the originating line when that line has
        no vendor yet (or its vendor is no longer one of the product's), so
        the user doesn't have to pick it again."""
        line_id = self.env.context.get('requirement_line_id')
        line = self.env['requirement.report.line'].browse(line_id).exists() if line_id else False
        if line and not line.purchase_order_id:
            product = line.product_id
            sellers = (product.seller_ids or product.product_tmpl_id.seller_ids).filtered(
                lambda s: not s.product_id or s.product_id == product
            )
            if sellers and line.vendor_id not in sellers.mapped('partner_id'):
                line.write({
                    'vendor_id': sellers[0].partner_id.id,
                    'price_unit': sellers[0].price or product.standard_price or 0.0,
                })
        # Reload the whole Requirement Lines list, not just the one record:
        # the line may move to another Vendor group, and a plain dialog close
        # would leave the old group (e.g. "No Vendor (0)") and a stale copy
        # of the row on screen until a manual refresh.
        return {'type': 'ir.actions.client', 'tag': 'soft_reload'}

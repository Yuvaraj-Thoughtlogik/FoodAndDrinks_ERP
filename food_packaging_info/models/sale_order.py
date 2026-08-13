from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


def _as_date(value):
    """commitment_date is a Datetime field; available_from/to_date are Date
    fields. Normalize to a plain date for comparison."""
    if not value:
        return value
    return value.date() if hasattr(value, 'date') else value


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    def _get_availability_conflict_message(self, product, delivery_date):
        """Returns an error message string if `product` is not available on
        `delivery_date`, otherwise False."""
        if product.available_from_date and delivery_date < product.available_from_date:
            return _(
                "'%(product)s' is only available for sale from %(from_date)s. "
                "The order's Delivery Date is %(delivery_date)s."
            ) % {
                'product': product.display_name,
                'from_date': product.available_from_date,
                'delivery_date': delivery_date,
            }
        if product.available_to_date and delivery_date > product.available_to_date:
            return _(
                "'%(product)s' is only available for sale until %(to_date)s. "
                "The order's Delivery Date is %(delivery_date)s."
            ) % {
                'product': product.display_name,
                'to_date': product.available_to_date,
                'delivery_date': delivery_date,
            }
        return False

    @api.onchange('product_id')
    def _onchange_product_id_check_availability(self):
        """Immediate UI feedback: if the order already has a Delivery Date
        selected, block adding a product that isn't available on that date."""
        for line in self:
            if not line.product_id or not line.order_id.commitment_date:
                continue
            delivery_date = _as_date(line.order_id.commitment_date)
            product = line.product_id.product_tmpl_id
            message = line._get_availability_conflict_message(product, delivery_date)
            if message:
                line.product_id = False
                return {
                    'warning': {
                        'title': _("Product Not Available"),
                        'message': message,
                    }
                }

    @api.constrains('product_id', 'order_id')
    def _check_product_availability_dates(self):
        """Server-side enforcement so the rule also holds for imports, API
        calls, or any path that bypasses the onchange."""
        for line in self:
            if not line.product_id or not line.order_id.commitment_date:
                continue
            delivery_date = _as_date(line.order_id.commitment_date)
            product = line.product_id.product_tmpl_id
            message = line._get_availability_conflict_message(product, delivery_date)
            if message:
                raise ValidationError(message)


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    @api.onchange('commitment_date')
    def _onchange_commitment_date_check_lines(self):
        """If the Delivery Date is changed/set after products were already
        added, warn immediately and flag which lines are now invalid."""
        if not self.commitment_date:
            return
        delivery_date = _as_date(self.commitment_date)
        invalid_products = []
        for line in self.order_line:
            if not line.product_id:
                continue
            message = line._get_availability_conflict_message(
                line.product_id.product_tmpl_id, delivery_date
            )
            if message:
                invalid_products.append(line.product_id.display_name)
        if invalid_products:
            return {
                'warning': {
                    'title': _("Delivery Date Conflict"),
                    'message': _(
                        "The following product(s) are not available for the "
                        "selected Delivery Date: %s"
                    ) % ", ".join(invalid_products),
                }
            }

    def write(self, vals):
        res = super().write(vals)
        if 'commitment_date' in vals:
            # Re-run the line-level constraint so saving a new Delivery Date
            # on an order that already has out-of-range products is blocked
            # too (not just the interactive onchange).
            for order in self:
                order.order_line._check_product_availability_dates()
        return res
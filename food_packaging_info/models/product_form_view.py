from odoo import api, fields, models, _
from odoo.exceptions import ValidationError


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    available_from_date = fields.Date(
        string="Available From Date",
        help="Product is available for sale starting from this date."
    )
    available_to_date = fields.Date(
        string="Available To Date",
        help="Product is available for sale until this date."
    )
    available_for_b2b = fields.Boolean(
        string="Available for B2B",
        default=True,
        help="Flag indicating whether this product is available for B2B sales."
    )
    available_for_staff = fields.Boolean(
        string="Available for Staff",
        default=True,
        help="Flag indicating whether this product is available for staff purchases."
    )

    @api.constrains('available_from_date', 'available_to_date')
    def _check_availability_dates(self):
        for record in self:
            if record.available_from_date and record.available_to_date:
                if record.available_to_date < record.available_from_date:
                    raise ValidationError(
                        _("'Available To Date' (%s) cannot be earlier than 'Available From Date' (%s).") %
                        (record.available_to_date, record.available_from_date)
                    )

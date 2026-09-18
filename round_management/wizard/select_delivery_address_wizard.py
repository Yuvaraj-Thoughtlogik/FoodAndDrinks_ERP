from odoo import models, fields, api, _
from odoo.exceptions import UserError


class SelectDeliveryAddressWizard(models.TransientModel):
    _name = 'select.delivery.address.wizard'
    _description = 'Select Alternative Delivery Address'

    sale_order_id = fields.Many2one('sale.order', string="Sales Order", required=True)
    partner_id = fields.Many2one('res.partner', string="Customer", related='sale_order_id.partner_id')

    delivery_address_id = fields.Many2one(
        'res.partner',
        string="Select Delivery Address",
        required=True,
        domain="['|', ('id', '=', partner_id), ('parent_id', 'child_of', partner_id)]"
    )

    def action_apply_address(self):
        self.ensure_one()
        if self.sale_order_id and self.delivery_address_id:
            self.sale_order_id.write({
                'partner_shipping_id': self.delivery_address_id.id
            })

            return {
                'type': 'ir.actions.act_window',
                'res_model': 'sale.order',
                'res_id': self.sale_order_id.id,
                'view_mode': 'form',
                'target': 'main',
            }
        return {'type': 'ir.actions.act_window_close'}

    def action_create_new_delivery_address(self):
        self.ensure_one()
        if not self.partner_id:
            raise UserError(_("No customer selected."))

        return {
            'name': _('Create New Delivery Address'),
            'type': 'ir.actions.act_window',
            'res_model': 'res.partner',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_parent_id': self.partner_id.id,
                'default_type': 'delivery',
                'default_street': self.partner_id.street,
                'default_street2': self.partner_id.street2,
                'default_city': self.partner_id.city,
                'default_state_id': self.partner_id.state_id.id,
                'default_zip': self.partner_id.zip,
                'default_country_id': self.partner_id.country_id.id,
            }
        }

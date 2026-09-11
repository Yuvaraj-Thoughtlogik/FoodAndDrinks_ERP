from odoo import api, fields, models, tools

class SaleOrder(models.Model):
    _inherit = "sale.order"

    order_channel_id = fields.Many2one(
        comodel_name='utm.source',
        string='Order Channel',
    )
    customer_source_id = fields.Many2one(
        comodel_name='res.partner.customer.source',
        string='Customer Source',
        # store=True,
        compute='_compute_customer_source_id',
    )
    delivery_channel = fields.Selection(
        selection=[
            ('regal_van', 'Regal Van Delivery'),
            ('courier', 'Courier Delivery'),
        ],
        string='Delivery Channel',
        # compute='_compute_delivery_channel',
        store=True,
        readonly=False,
        help="Automatically mapped based on the selected Round Batch."
    )

    # @api.onchange('partner_id')
    # def _onchange_partner_id_for_utm(self):
    #     for rec in self:
    #         rec.source_id = rec.partner_id.customer_source_id.id

    @api.depends('partner_id', 'partner_id.partner_customer_source_id')
    def _compute_customer_source_id(self):
        for order in self:
            order.customer_source_id = order.partner_id.partner_customer_source_id

    # @api.model_create_multi
    # def create(self, vals_list):
    #     orders = super().create(vals_list)
    #
    #     for order in orders:
    #         if order.partner_id and order.source_id:
    #             order.partner_id.with_context(
    #                 active_model=order._name,
    #                 active_id=order.id,
    #             ).write({
    #                 "order_channel_id": order.order_channel_id.id,
    #             })
    #
    #     return orders
    #
    # def write(self, vals):
    #     res = super().write(vals)
    #
    #     if "order_channel_id" in vals:
    #         for order in self:
    #             if order.partner_id:
    #                 order.partner_id.with_context(
    #                     active_model=order._name,
    #                     active_id=order.id,
    #                 ).write({
    #                     "order_channel_id": order.order_channel_id.id,
    #                 })
    #
    #     return res

    def action_confirm(self):
        res = super().action_confirm()
        for order in self:
            if order.partner_id and order.order_channel_id:
                order.partner_id.with_context(
                    active_model=order._name,
                    active_id=order.id,
                ).write({
                    "order_channel_id": order.order_channel_id.id,
                })
        return res
        
        
    # @api.depends('batch_id', 'batch_id.delivery_channel')
    # def _compute_delivery_channel(self):
    #     for order in self:
    #         if order.batch_id and order.batch_id.delivery_channel:
    #             order.delivery_channel = order.batch_id.delivery_channel
    #         elif not order.delivery_channel:
    #             order.delivery_channel = False

    # @api.onchange('batch_id')
    # def _onchange_batch_id_set_delivery_channel(self):
    #     if self.batch_id and self.batch_id.delivery_channel:
    #         self.delivery_channel = self.batch_id.delivery_channel

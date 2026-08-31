from odoo import models, fields, api


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    batch_id = fields.Many2one(
        'round.management.batch', 
        string='Round Batch', 
        compute='_compute_batch_id',
        store=True,
        readonly=False,
        ondelete='set null',
        index=True,
        domain="[('round_id', '=?', round_id), ('state', 'in', ['act', 'prt'])]",
    )
    delivery_date = fields.Datetime(
        string='Delivery Date',
        compute='_compute_delivery_date',
        store=True,
        readonly=False
    )
    delivery_channel = fields.Selection(
        selection=[
            ('regal_van', 'Regal Van Delivery'),
            ('courier', 'Courier Delivery'),
        ],
        string='Delivery Channel',
        compute='_compute_delivery_channel',
        store=True,
        readonly=False,
        default='regal_van',
        index=True,
    )

    @api.depends('sale_id.batch_id', 'origin')
    def _compute_batch_id(self):
        for picking in self:
            if picking.sale_id and picking.sale_id.batch_id:
                picking.batch_id = picking.sale_id.batch_id
            elif picking.origin:
                sale_order = self.env['sale.order'].search([('name', '=', picking.origin)], limit=1)
                if sale_order and sale_order.batch_id:
                    picking.batch_id = sale_order.batch_id
                elif not picking.batch_id:
                    picking.batch_id = False
            elif not picking.batch_id:
                picking.batch_id = False

    @api.depends('sale_id.delivery_channel', 'origin')
    def _compute_delivery_channel(self):
        for picking in self:
            if picking.sale_id and picking.sale_id.delivery_channel:
                picking.delivery_channel = picking.sale_id.delivery_channel
            elif picking.origin:
                sale_order = self.env['sale.order'].search([('name', '=', picking.origin)], limit=1)
                if sale_order and sale_order.delivery_channel:
                    picking.delivery_channel = sale_order.delivery_channel
                elif not picking.delivery_channel:
                    picking.delivery_channel = 'regal_van'
            elif not picking.delivery_channel:
                picking.delivery_channel = 'regal_van'

    @api.depends('sale_id.commitment_date', 'sale_id.delivery_date', 'origin', 'scheduled_date')
    def _compute_delivery_date(self):
        for picking in self:
            if picking.sale_id and picking.sale_id.commitment_date:
                picking.delivery_date = picking.sale_id.commitment_date
            elif picking.origin:
                sale_order = self.env['sale.order'].search([('name', '=', picking.origin)], limit=1)
                picking.delivery_date = sale_order.commitment_date if sale_order and sale_order.commitment_date else (picking.scheduled_date or fields.Datetime.now())
            else:
                picking.delivery_date = picking.scheduled_date or fields.Datetime.now()
                


class MrpProduction(models.Model):
    _inherit = 'mrp.production'

    batch_id = fields.Many2one(
        'round.management.batch',
        string='Round Batch',
    )
    delivery_date = fields.Date(
        string='Delivery Date',
        related='batch_id.delivery_date',
        store=True,
    )
    
    product_categ_id = fields.Many2one(
        'product.category',
        string='Product Category',
        related='product_id.categ_id',
        store=True,
    )

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
        compute='_compute_batch_id',
        store=True,
        readonly=False,
    )
    delivery_date = fields.Date(
        string='Delivery Date',
        related='batch_id.delivery_date',
        store=True,
        readonly=True,
    )
    product_categ_id = fields.Many2one(
        'product.category',
        string='Product Category',
        related='product_id.categ_id',
        store=True,
    )

    @api.depends('origin', 'move_dest_ids.sale_line_id.order_id.batch_id')
    def _compute_batch_id(self):
        for mo in self:
            batch = False

           
            sale_orders = mo.move_dest_ids.mapped('sale_line_id.order_id')
            if sale_orders and sale_orders[0].batch_id:
                batch = sale_orders[0].batch_id

            
            elif mo.origin:
                so = self.env['sale.order'].search([('name', '=', mo.origin)], limit=1)
                if so and so.batch_id:
                    batch = so.batch_id

            mo.batch_id = batch
            
            
class StockRule(models.Model):
    _inherit = 'stock.rule'

    def _prepare_mo_vals(self, *args, **kwargs):
        res = super()._prepare_mo_vals(*args, **kwargs)
        values = kwargs.get('values')
        if not values and len(args) >= 8:   
            values = args[7]
        if values and values.get('sale_line_id'):
            sale_line = self.env['sale.order.line'].browse(values['sale_line_id'])
            if sale_line.order_id and sale_line.order_id.batch_id:
                res['batch_id'] = sale_line.order_id.batch_id.id
                
        return res
    
    

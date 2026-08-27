from odoo import models, fields, api


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    batch_id = fields.Many2one(
        'round.management.batch', 
        string='Round Batch', 
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
        default='regal_van',
        index=True,
    )
    @api.depends('origin')
    def _compute_delivery_date(self):
        for picking in self:
            if picking.origin:
                sale_order = self.env['sale.order'].search([('name', '=', picking.origin)], limit=1)
                picking.delivery_date = sale_order.commitment_date or picking.scheduled_date
            else:
                picking.delivery_date = picking.scheduled_date or fields.Datetime.now()

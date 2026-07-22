from odoo import models, fields

class ResPartner(models.Model):
    _inherit = 'res.partner'

    round_id = fields.Many2one('round.management.round', string='Assigned Round')
    batch_ids = fields.One2many(
        'round.management.batch', 
        string='Customer Batches',
        compute='_compute_batch_ids'
    )
    
    round_code = fields.Char(
        related='round_id.code', 
        string='Round Code', 
        store=True, 
        readonly=True
    )

    def _compute_batch_ids(self):
        for partner in self:
            
            orders = self.env['sale.order'].search([('partner_id', '=', partner.id)])
            partner.batch_ids = orders.mapped('batch_id')

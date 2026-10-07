from odoo import models, fields,api

class ResPartner(models.Model):
    _inherit = 'res.partner'

    round_id = fields.Many2one('round.management.round', string='Assigned Round', required=True)
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
    available_round_ids = fields.Many2many(
        'round.management.round',
        compute='_compute_available_rounds',
    )

    def _compute_batch_ids(self):
        for partner in self:
            
            orders = self.env['sale.order'].search([('partner_id', '=', partner.id)])
            partner.batch_ids = orders.mapped('batch_id')

    @api.depends('zip')
    def _compute_available_rounds(self):
        Round = self.env['round.management.round']

        for rec in self:
            if not rec.zip:
                rec.available_round_ids = Round.search([])
                continue

            region = self.env['round.region'].search([
                ('pincode_ids.name', '=', rec.zip)
            ], limit=1)

            if region:
                rec.available_round_ids = Round.search([
                    ('region_id', '=', region.id)
                ])
            else:
                rec.available_round_ids = Round.search([])
                
                
    @api.model_create_multi
    def create(self, vals_list):
        partners = super().create(vals_list)
        rounds = partners.mapped('round_id')
        if rounds:
            rounds._compute_customer_counts()
        return partners

    def write(self, vals):
        old_rounds = self.mapped('round_id')
        res = super().write(vals)
        if any(field in vals for field in ['customer_lifecycle_status', 'round_id', 'active']):
            new_rounds = self.mapped('round_id')
            (old_rounds | new_rounds)._compute_customer_counts()
            
        return res

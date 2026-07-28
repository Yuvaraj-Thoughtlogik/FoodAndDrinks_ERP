from odoo import models, fields, api

class RoundManagementRound(models.Model):
    _name = 'round.management.round'
    _description = 'Round Details'
    _rec_name = 'name'

    name = fields.Char(string='Round Name', required=True)
    code = fields.Char(
        string='Round Code', 
        required=True, 
        copy=False, 
        readonly=True, 
        default='New'
    )
    state = fields.Selection([
        ('active', 'Active'),
        ('inactive', 'Dead')
    ], string='Status', default='active')
    
    region = fields.Selection([
        ('south', 'South'),
        ('north', 'North'),
        ('east', 'East'),
        ('west', 'West')
    ], string='Region')
    region_id = fields.Many2one(comodel_name='round.region', string='Region')
    
    depot_id = fields.Many2one('stock.warehouse', string='Default Depot') 
    #pay_grade = fields.Char(string='Pay Grade')
    target_cust_rev = fields.Float(string='Target Cust. Rev.', default=0.0)
    max_alt_drops = fields.Integer(string='Max. Alt. Drops', default=0)
    
    # Schedule Configuration
    mon_active = fields.Boolean(string='Monday')
    mon_from = fields.Float(string='From (Mon)')
    mon_to = fields.Float(string='To (Mon)')
    
    tue_active = fields.Boolean(string='Tuesday')
    tue_from = fields.Float(string='From (Tue)')
    tue_to = fields.Float(string='To (Tue)')
    
    wed_active = fields.Boolean(string='Wednesday')
    wed_from = fields.Float(string='From (Wed)')
    wed_to = fields.Float(string='To (Wed)')
    
    thu_active = fields.Boolean(string='Thursday')
    thu_from = fields.Float(string='From (Thu)')
    thu_to = fields.Float(string='To (Thu)')
    
    fri_active = fields.Boolean(string='Friday')
    fri_from = fields.Float(string='From (Fri)')
    fri_to = fields.Float(string='To (Fri)')
    
    sat_active = fields.Boolean(string='Saturday')
    sat_from = fields.Float(string='From (Sat)')
    sat_to = fields.Float(string='To (Sat)')
    
    sun_active = fields.Boolean(string='Sunday')
    sun_from = fields.Float(string='From (Sun)')
    sun_to = fields.Float(string='To (Sun)')
    
    no_between_times = fields.Boolean(string='No Between times on round')
    notes = fields.Html(string='Notes')
    
    batch_ids = fields.One2many('round.management.batch', 'round_id', string='Round Batches')
    partner_id = fields.Many2one('res.partner', string='Default Customer')
    
    alt_round_ids = fields.One2many(
        'round.management.alternative', 
        'round_id', 
        string='Alternative Rounds'
    )
    
    def action_open_new_batch_wizard(self):
        """Opens a pop-up modal to create or view a Round Batch for this specific Round."""
        self.ensure_one()
        return {
            'name': 'Round Batch Entry',
            'type': 'ir.actions.act_window',
            'res_model': 'round.management.batch',
            'view_mode': 'form',
            'target': 'new',  
            'context': {
                'default_round_id': self.id,
                'default_state': 'pln',
            }
        }

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('code', 'New') == 'New':
               
                vals['code'] = self.env['ir.sequence'].next_by_code('round.management.1050.code') or 'New'
        return super().create(vals_list)
        
        
    

    _sql_constraints = [
        ('code_uniq', 'unique(code)', 'The Round Code must be unique!')
    ]

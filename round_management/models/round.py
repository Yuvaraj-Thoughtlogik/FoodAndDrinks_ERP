from odoo import models, fields, api

class RoundManagementRound(models.Model):
    _name = 'round.management.round'
    _description = 'Round Details'
    _rec_name = 'name'
    
    @api.model
    def _default_round_code(self):
        """Generate sequence automatically as soon as the form opens/Create is clicked."""
        return self.env['ir.sequence'].next_by_code('round.management.1050.code') or 'New'

    name = fields.Char(string='Round Name', required=True)
    code = fields.Char(
        string='Round Code', 
        required=True, 
        copy=False, 
        readonly=True, 
        default=_default_round_code
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
    
    TIME_SELECTION_24H = [
        ('00:00', '00:00'), ('00:30', '00:30'),
        ('01:00', '01:00'), ('01:30', '01:30'),
        ('02:00', '02:00'), ('02:30', '02:30'),
        ('03:00', '03:00'), ('03:30', '03:30'),
        ('04:00', '04:00'), ('04:30', '04:30'),
        ('05:00', '05:00'), ('05:30', '05:30'),
        ('06:00', '06:00'), ('06:30', '06:30'),
        ('07:00', '07:00'), ('07:30', '07:30'),
        ('08:00', '08:00'), ('08:30', '08:30'),
        ('09:00', '09:00'), ('09:30', '09:30'),
        ('10:00', '10:00'), ('10:30', '10:30'),
        ('11:00', '11:00'), ('11:30', '11:30'),
        ('12:00', '12:00'), ('12:30', '12:30'),
        ('13:00', '13:00'), ('13:30', '13:30'),
        ('14:00', '14:00'), ('14:30', '14:30'),
        ('15:00', '15:00'), ('15:30', '15:30'),
        ('16:00', '16:00'), ('16:30', '16:30'),
        ('17:00', '17:00'), ('17:30', '17:30'),
        ('18:00', '18:00'), ('18:30', '18:30'),
        ('19:00', '19:00'), ('19:30', '19:30'),
        ('20:00', '20:00'), ('20:30', '20:30'),
        ('21:00', '21:00'), ('21:30', '21:30'),
        ('22:00', '22:00'), ('22:30', '22:30'),
        ('23:00', '23:00'), ('23:30', '23:30'),
    ]

    # Monday
    mon_active = fields.Boolean(string='Monday')
    mon_from = fields.Selection(TIME_SELECTION_24H, string='From (Mon)', default='08:00')
    mon_to = fields.Selection(TIME_SELECTION_24H, string='To (Mon)', default='17:00')

    # Tuesday
    tue_active = fields.Boolean(string='Tuesday')
    tue_from = fields.Selection(TIME_SELECTION_24H, string='From (Tue)', default='08:00')
    tue_to = fields.Selection(TIME_SELECTION_24H, string='To (Tue)', default='17:00')

    # Wednesday
    wed_active = fields.Boolean(string='Wednesday')
    wed_from = fields.Selection(TIME_SELECTION_24H, string='From (Wed)', default='08:00')
    wed_to = fields.Selection(TIME_SELECTION_24H, string='To (Wed)', default='17:00')

    # Thursday
    thu_active = fields.Boolean(string='Thursday')
    thu_from = fields.Selection(TIME_SELECTION_24H, string='From (Thu)', default='08:00')
    thu_to = fields.Selection(TIME_SELECTION_24H, string='To (Thu)', default='17:00')

    # Friday
    fri_active = fields.Boolean(string='Friday')
    fri_from = fields.Selection(TIME_SELECTION_24H, string='From (Fri)', default='08:00')
    fri_to = fields.Selection(TIME_SELECTION_24H, string='To (Fri)', default='17:00')

    # Saturday
    sat_active = fields.Boolean(string='Saturday')
    sat_from = fields.Selection(TIME_SELECTION_24H, string='From (Sat)', default='08:00')
    sat_to = fields.Selection(TIME_SELECTION_24H, string='To (Sat)', default='17:00')

    # Sunday
    sun_active = fields.Boolean(string='Sunday')
    sun_from = fields.Selection(TIME_SELECTION_24H, string='From (Sun)', default='08:00')
    sun_to = fields.Selection(TIME_SELECTION_24H, string='To (Sun)', default='17:00')
    
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

    #@api.model_create_multi
    #def create(self, vals_list):
        #for vals in vals_list:
            #if vals.get('code', 'New') == 'New':
               
                #vals['code'] = self.env['ir.sequence'].next_by_code('round.management.1050.code') or 'New'
        #return super().create(vals_list)
        
        
    

    _sql_constraints = [
        ('code_uniq', 'unique(code)', 'The Round Code must be unique!')
    ]

from odoo import models, fields

class RoundManagementAlternative(models.Model):
    _name = 'round.management.alternative'
    _description = 'Alternative Round Mapping'
    
    round_id = fields.Many2one(
        'round.management.round', 
        string='Primary Round', 
        required=True, 
        ondelete='cascade'
    )
    
    alt_round_id = fields.Many2one(
        'round.management.round', 
        string='Alternative Round', 
        required=True
    )

    alt_round_code = fields.Char(
        related='alt_round_id.code', 
        string='Alter. Rnd Code', 
        readonly=True
    )
    alt_round_name = fields.Char(related='alt_round_id.name', string='Alter. Rnd Name', readonly=True)
    before_time = fields.Char(string='Before', help="e.g. From 8AM or 08:00")
    after_time = fields.Char(string='After', help="e.g. To 12 noon or B12-5")
    active = fields.Boolean(string='Active', default=True)

from odoo import models, fields

class RoundAlternative(models.Model):
    _name = 'round.management.alternative'
    _description = 'Alternative Round Configuration'

    round_id = fields.Many2one('round.management.round', string='Parent Round', ondelete='cascade')
    alternative_round_id = fields.Many2one('round.management.round', string='Alternative Round', required=True)
    
    # Matching legacy "Before" and "After" time fields
    time_before = fields.Char(string='Before')
    time_after = fields.Char(string='After')
    active = fields.Boolean(string='Active', default=True)

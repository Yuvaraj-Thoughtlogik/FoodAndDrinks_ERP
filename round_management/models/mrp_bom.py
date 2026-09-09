from odoo import models,fields


class MrpBom(models.Model):
    _inherit = 'mrp.bom'

    production_type = fields.Selection([
        ('keep','Keep'),
        ('split','Split')
    ], 
    string='Production Type', 
    required=True,
    default='keep'
    )
from odoo import fields, models

class UtmSource(models.Model):
    _inherit = 'utm.source'
    _order = 'sequence,name'

    active = fields.Boolean(default=True)
    sequence = fields.Integer(default=10, help="Used to order sources. Lower is higher priority.")


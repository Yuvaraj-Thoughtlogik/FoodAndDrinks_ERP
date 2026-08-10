from odoo import models, fields, api

class ResPartnerSource(models.Model):
    _name = 'res.partner.customer.source'
    _description = 'Customer Source'
    _order = 'sequence,name'

    name = fields.Char(string='Customer Source')
    sequence = fields.Integer(string='Sequence',default=10)
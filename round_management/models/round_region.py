from odoo import api, fields, models, tools

class RoundRegionPinCode(models.Model):
    _name = 'round.region.pincode'
    _description = 'Round Region Pincode'

    name = fields.Char(required=True,string="Pincode")
    region_id = fields.Many2one(comodel_name='round.region',string="Region")

    _pincode_code_unique = models.Constraint(
        "UNIQUE(name,region_id)",
        "Pin Code must be unique.",
    )

class RoundRegion(models.Model):
    _name = 'round.region'
    _description = 'Round Region'

    name = fields.Char(required=True)

    pincode_ids = fields.One2many(
        comodel_name='round.region.pincode',
        string='Pin-codes',
        inverse_name='region_id'
    )

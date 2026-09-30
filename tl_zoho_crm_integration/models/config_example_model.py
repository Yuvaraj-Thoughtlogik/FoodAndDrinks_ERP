from odoo import models, fields,api
import datetime
import logging
_logger = logging.getLogger(__name__)


# access_zoho_example_model,access_zoho_example_model,model_zoho_example_model,base.group_user,1,1,1,1
# access_zoho_example_model_line,access_zoho_example_model_line,model_zoho_example_model_line,base.group_user,1,1,1,1

class ZohoExampleModel(models.Model):
    _name = 'zoho.example.model'
    _description = 'Zoho Example Model'

    name = fields.Char(string="Name")
    description = fields.Text(string="Description")
    checkbox = fields.Boolean(string="Active", default=True)
    count = fields.Integer(string="Count")
    price = fields.Float(string="Price")
    category = fields.Selection([
        ('basic', 'Basic'),
        ('premium', 'Premium'),
        ('vip', 'VIP')
    ], string="Category")
    date = fields.Date(string="Date")
    datetime = fields.Datetime(string="Datetime")
    file_data = fields.Binary(string="File")
    file_data_filename = fields.Char(string="File Name")

    partner_id = fields.Many2one('res.partner', string="Partner Accounts ", domain="[('is_company','=',True)]")
    partner_ids = fields.Many2many('res.partner', string="Partner Contact", domain="[('is_company','=',False)]")
    tag_ids = fields.Many2many('res.partner.category', string="Tags")
    line_ids = fields.One2many(comodel_name='zoho.example.model.line', inverse_name='example_id', string="Lines")

    @api.model
    def create_test_data(self):
        count = self.search_count([])
        record = self.create([{
            'name': f'Odoo Test {count + 1}',
            'checkbox': True,
            'count': 2,
            'price': 122.9,
            'line_ids':[
                (0,0,{
                    'name': f'Odoo Test {count + 1} Line 1',
                    'checkbox': True,
                    'count': 2,
                    'price': 122.9,
                }),
                (0, 0, {
                    'name': f'Odoo Test {count + 1} Line 2',
                    'checkbox': True,
                    'count': 2,
                    'price': 122.9,
                })

            ]
        }])
        return {
            'type': 'ir.actions.act_window',
            'name': f'{record.name}',
            'res_model': 'zoho.example.model',
            'res_id': record.id,
            'view_mode': 'form'
        }

class ZohoExampleLine(models.Model):
    _name = 'zoho.example.model.line'
    _description = 'Zoho Example Model Line'

    example_id = fields.Many2one(comodel_name='zoho.example.model', string="Example")
    name = fields.Char(string="Name")
    description = fields.Text(string="Description")
    checkbox = fields.Boolean(string="Active", default=True)
    count = fields.Integer(string="Count")
    price = fields.Float(string="Price")
    category = fields.Selection([
        ('basic', 'Basic'),
        ('premium', 'Premium'),
        ('vip', 'VIP')
    ], string="Category")
    date = fields.Date(string="Date")
    datetime = fields.Datetime(string="Datetime")
    file_data = fields.Binary(string="File")
    file_data_filename = fields.Char(string="File Name")
    partner_id = fields.Many2one('res.partner', string="Partner Accounts ",domain="[('is_company','=','True')]")

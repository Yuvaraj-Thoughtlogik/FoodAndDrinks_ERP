from odoo import models, fields, api


class ConfigLogs(models.Model):
    _name = 'zoho.config.logs'
    _description = 'Log of data processing operations'
    _order = 'create_date desc'

    name = fields.Char(string="Name", compute="_compute_name")
    last_sync = fields.Datetime(string="Last Sync")
    config_schedule_id = fields.Many2one(string="Zoho Schedule", comodel_name="zoho.config.schedule", ondelete='cascade')
    zoho_config_app_id = fields.Many2one(string="Zoho Application", comodel_name="zoho.config.application",
                                         required=True, ondelete='cascade')
    modules = fields.Text(string="Module")
    is_test_log = fields.Boolean(string="Is Test Log")
    sync_type = fields.Selection([('1way_sync', 'One-way Sync'), ('2way_sync', 'Two-way Sync')], string="Sync type",
                                 default='1way_sync')
    one_way = fields.Boolean(string='One way', default=True)
    two_way = fields.Boolean(string='Two way')
    status = fields.Selection([('success', 'Success'), ('partial', 'Partial'), ('failed', 'Failed')], string="Status")
    is_failed = fields.Boolean(string="Is Failed", compute='_compute_is_failed', store=True)
    one_way_request = fields.Text(string="One Way Request Payload")
    one_way_response = fields.Text(string="One Way Response")
    two_way_request = fields.Text(string="Two Way Request Payload")
    two_way_response = fields.Text(string="Two Way Response")
    created_odoo_ids = fields.Text(string="Created Odoo Record IDs")
    updated_odoo_ids = fields.Text(string="Updated Odoo Record IDs")
    created_zoho_ids = fields.Text(string="Created Zoho Record IDs")
    updated_zoho_ids = fields.Text(string="Updated Zoho Record IDs")
    odoo_ids = fields.Text(string="Odoo Record IDs")
    zoho_ids = fields.Text(string="Zoho Record IDs")
    success_message = fields.Text(string="Success Message")
    error_message = fields.Text(string="Error Message")

    @api.depends('zoho_config_app_id.name', 'modules')
    def _compute_name(self):
        for rec in self:
            rec.name = f"{rec.zoho_config_app_id.name} Log: {rec.modules}"

    @api.depends('status')
    def _compute_is_failed(self):
        for rec in self:
            rec.is_failed = rec.status == 'failed'

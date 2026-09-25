from odoo import models,fields,api
import json
from datetime import datetime ,date

from odoo.api import ondelete
from odoo.exceptions import ValidationError,UserError

import logging
_logger = logging.getLogger(__name__)


def _safe_json(obj):
    """Convert non-serializable objects to serializable form."""
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    elif hasattr(obj, 'id') and hasattr(obj, 'name'):  # likely a recordset
        return {'id': obj.id, 'name': obj.name}
    return str(obj)  # fallback for anything else


class ZohoConfigSchedule(models.Model):
    _name = 'zoho.config.schedule'
    _description = "Zoho Config Schedule"
    _order = 'sequence'

    sequence = fields.Integer(string="Sequence",default=10,compute='_compute_sequence',store=True)
    name = fields.Char(string="Name",compute="_compute_name")
    # config_id = fields.Many2one(comodel_name="zoho.config",string="Zoho Config",default = lambda self:self.env['zoho.config'].search([],limit=1).id)
    module_id = fields.Many2one(comodel_name='zoho.config.module',string="Module",required = True,domain="[('zoho_config_app_id','=',zoho_config_app_id)]",ondelete='cascade')
    zoho_config_app_id = fields.Many2one(comodel_name='zoho.config.application',string="Zoho Application",ondelete='cascade')
    zoho_app_name = fields.Char(related='zoho_config_app_id.name')
    odoo_model_name = fields.Char(related='module_id.odoo_model_name')
    zoho_to_odoo = fields.Boolean(
        string='Zoho to Odoo',
        compute='_compute_from_config',
        store=False,
        readonly=True
    )
    odoo_to_zoho = fields.Boolean(
        string='Odoo to Zoho',
        compute='_compute_from_config',
        store=False,
        readonly=True
    )
    sync_frequency = fields.Selection(
        [
            ('1_hour', 'One Hour'),
            ('2_hour', 'Two Hour'),
            ('once_a_day', 'Once a Day')
        ],
        string="Sync Frequency",
        compute='_compute_from_config',
        store=False,
        readonly=True,
        required=True
    )
    sync_type = fields.Selection([('one_way','One Way'),('two_way','Two Way')],compute='_compute_sync_type',store=True)
    config_log_ids = fields.One2many(string="Logs", comodel_name='zoho.config.logs', inverse_name='config_schedule_id')
    one_way_last_sync = fields.Datetime(string="Last One-way Sync Time")
    two_way_last_sync = fields.Datetime(string="Last Two-way Sync Time")
    last_sync = fields.Datetime(string ="Last Sync")
    cron_id = fields.Many2one(comodel_name='ir.cron',string='Cron')



    def unlink(self):
        cron_ids = []
        for rec in self:
            if rec.cron_id:
                cron_ids.append(rec.cron_id.id)
            # rec.cron_id.unlink()
        res = super().unlink()
        self.env['ir.cron'].unlink()
        return res

    @api.depends('zoho_config_app_id.zoho_to_odoo','zoho_config_app_id.odoo_to_zoho','zoho_config_app_id.sync_frequency')
    def _compute_from_config(self):
        for rec in self:
            rec.zoho_to_odoo = rec.zoho_config_app_id.zoho_to_odoo
            rec.odoo_to_zoho = rec.zoho_config_app_id.odoo_to_zoho
            rec.sync_frequency = rec.zoho_config_app_id.sync_frequency

    @api.depends('module_id','zoho_to_odoo','odoo_to_zoho')
    def _compute_name(self):
        for rec in self:
            sync = "One Way: Zoho -> Odoo" if rec.zoho_to_odoo else "One Way: Odoo -> Zoho"
            if rec.zoho_to_odoo and rec.odoo_to_zoho:
                sync = "Zoho <-> Odoo Two Way"
            rec.name = f'{rec.zoho_app_name}: {rec.module_id.name} with {sync}'

    @api.depends('module_id')
    def _compute_sequence(self):
        for rec in self:
            rec.sequence = rec.module_id.sequence

    @api.depends('zoho_config_app_id.zoho_to_odoo','zoho_config_app_id.odoo_to_zoho')
    def _compute_sync_type(self):
        for rec in self:
            rec.sync_type = "two_way" if rec.zoho_to_odoo and rec.odoo_to_zoho else "one_way"

    def action_view_module(self):
        self.ensure_one()
        return {
            'type':'ir.actions.act_window',
            'name':f'{self.zoho_app_name}: {self.module_id.name}',
            'res_model':'zoho.config.module',
            'res_id':self.module_id.id,
            'view_mode':'form',
            'target':'current'
        }

    def action_view_logs(self):
        self.ensure_one()
        return {
            'type':'ir.actions.act_window',
            'name':f'{self.zoho_app_name}: {self.module_id.name}',
            'res_model':'zoho.config.logs',
            'view_mode':'list,form',
            'domain':[('config_schedule_id','=',self.id)],
            'target':'current'
        }


    def create_log(self,modules,status,request,response,odoo_ids,zoho_ids,message):
        log = self.env['zoho.config.logs'].create([{
            'config_schedule_id': self.id,
            'zoho_config_app_id': self.zoho_config_app_id.id,
            'modules':modules,
            'is_test_log': False,
            'status': status,
            'one_way': self.zoho_to_odoo,
            'two_way': self.odoo_to_zoho,
            'one_way_request': request['one_way'],
            'one_way_response': response['one_way'],
            'two_way_request': request['two_way'],
            'two_way_response': response['two_way'],
            # 'created_odoo_ids': odoo_ids['created'],
            # 'updated_odoo_ids': odoo_ids['updated'],
            # 'created_zoho_ids': zoho_ids['created'],
            # 'updated_zoho_ids': zoho_ids['updated'] ,
            'odoo_ids': odoo_ids,
            'zoho_ids': zoho_ids ,
            'success_message': '\n'.join(message['success']),
            'error_message': '\n'.join(message['error'])
        }])
        # print("log",log)
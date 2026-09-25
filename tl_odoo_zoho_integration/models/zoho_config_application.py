from odoo import models,fields,api
from odoo.exceptions import ValidationError

class ZohoApplication(models.Model):
    _name = 'zoho.config.application'
    _description = "Zoho Applications"

    name = fields.Char(string="Name")
    description = fields.Text(string="Description",compute='_compute_description')
    addon_name = fields.Char(string="Addon Name")
    addon_id = fields.Many2one(comodel_name='ir.module.module',compute="_compute_addon_id",store=True,ondelete='cascade')

    addon_state = fields.Selection(string="State",related='addon_id.state',store=True)
    icon_flag = fields.Char(string='Icon Flag',related='addon_id.icon_flag')
    icon = fields.Char(string='Icon',related='addon_id.icon')
    sync_type = fields.Selection([('1way_sync', 'One-way Sync'), ('2way_sync', 'Two-way Sync')], string="Sync type",
                                 default='1way_sync')
    sync_frequency = fields.Selection([('1_hour', 'Every Hour'), ('2_hour', 'Every 2 Hours'), ('once_a_day', 'Once a Day')],
                                      string="Sync Frequency", default='once_a_day',required=True)
    zoho_to_odoo = fields.Boolean(string='Zoho to Odoo', default=True)
    odoo_to_zoho = fields.Boolean(string='Odoo to Zoho')

    config_log_ids = fields.One2many(string="Logs", comodel_name='zoho.config.logs',inverse_name='zoho_config_app_id')

    schedule_ids = fields.One2many(comodel_name='zoho.config.schedule',string="Schedule", inverse_name='zoho_config_app_id')

    config_module_ids = fields.One2many(comodel_name='zoho.config.module',string="Modules", inverse_name='zoho_config_app_id')

    schedule_count = fields.Integer(string="Schedule Count",compute='_compute_schedule_count')

    cron_ids = fields.Many2many(comodel_name='ir.cron',string='Schedule Crons')

    re_schedule = fields.Boolean(string='Reschedule')
    notify_msg = fields.Text(string='Notify Message')

    # @api.onchange('notify_msg')
    # def onchange_notify_msg(self):
    #     print("test")
    #     self.ensure_one()
    #     return {
    #         'type': 'ir.actions.client',
    #         'tag': 'display_notification',
    #         'params': {
    #             'title': 'Scheduled Action Created',
    #             'message': self.notify_msg,
    #             'type': 'success',
    #             'sticky': True,
    #         }
    #     }

    @api.depends('name', 'zoho_to_odoo', 'odoo_to_zoho', 'sync_frequency')
    def _compute_description(self):
        for rec in self:
            # Sync type text
            if rec.zoho_to_odoo and rec.odoo_to_zoho:
                sync = "Two-way Sync: Zoho <-> Odoo"
            elif rec.zoho_to_odoo:
                sync = "One-way Sync: Zoho → Odoo"
            else:
                sync = "One-way Sync: Odoo → Zoho"

            # Frequency label
            freq_label = dict(self._fields['sync_frequency'].selection).get(rec.sync_frequency, '')

            rec.description = f"{sync} for {'every' if rec.sync_frequency != 'once_a_day' else ''} {freq_label} "

    @api.onchange('schedule_ids')
    def _onchange_schedule_ids(self):
        for rec in self:
            seen = set()
            for schedule in rec.schedule_ids:
                if schedule.module_id:
                    if schedule.module_id.id in seen:
                        raise ValidationError("You cannot select the same Module more than once.")
                    seen.add(schedule.module_id.id)

    def write(self, vals):
        if 'schedule_ids' in vals:
            for val in vals['schedule_ids']:
                command = val[0]
                if command == 2:
                    schedule_id = val[1]
                    schedule = self.env['zoho.config.schedule'].browse(schedule_id)
                    # print(schedule)
                    if schedule and schedule.module_id:
                        if schedule.module_id.view_id:
                            schedule.module_id.view_id.active = False
                        # schedule.module_id.is_added_to_sync = False
                elif command in (0, 1):
                    values = val[2] if len(val) > 2 else {}
                    rec_id = values.get('module_id')
                    if rec_id:
                        module = self.env['zoho.config.module'].browse(rec_id)
                        if module:
                            if module.view_id:
                                module.view_id.active = True
                            # module.is_added_to_sync = True
        if 'sync_frequency' in vals or 'schedule_ids' in vals:
            vals['re_schedule']=True
        res = super().write(vals)
        return res

    @api.depends('addon_name')
    def _compute_addon_id(self):
        for rec in self:
            rec.addon_id = self.env['ir.module.module'].search([('name','=',rec.addon_name)])

    @api.depends('schedule_ids')
    def _compute_schedule_count(self):
        for rec in self:
            rec.schedule_count = len(rec.schedule_ids) if rec.schedule_ids else 0

    def action_active_all_view(self):
        self.ensure_one()
        for schedule in self.schedule_ids:
            if schedule.module_id.view_id:
                schedule.module_id.view_id.active = True

    def action_view_logs(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Log History',
            'res_model': 'zoho.config.logs',  # replace with actual model
            'view_mode': 'list,form',
            'domain': [('zoho_config_app_id', '=', self.id)],  # or use correct relation field
            'target': 'current',
        }

    def action_view_modules(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Modules',
            'res_model': 'zoho.config.module',  # replace with actual model
            'view_mode': 'kanban,list,form',
            'domain': [('zoho_config_app_id', '=', self.id)],  # or use correct relation field
            'context':{
                'default_zoho_config_app_id':self.id
            },
            'target': 'current',
        }

    def action_create_module(self):
        self.ensure_one()
        return {
            'type':'ir.actions.act_window',
            'name':f'New {self.name} Module',
            'view_mode':'form',
            'res_model':'zoho.config.module',
            'context':{
                'default_zoho_config_app_id':self.id
            }
        }

    def action_active_addon(self):
        self.ensure_one()
        if self.addon_id:
            self.addon_id.button_immediate_install()
        menu_id = self.env.ref("tl_odoo_zoho_integration.menu_zoho_configuration").id
        return {
            'type': 'ir.actions.act_url',
            'url': f'/web#menu_id={menu_id}',
            'target': 'self',
        }

    def action_deactivate_addon(self):
        self.ensure_one()
        if self.addon_id:
            self.addon_id.button_immediate_uninstall()
        # self.unlink()
        menu_id = self.env.ref("tl_odoo_zoho_integration.menu_zoho_application").id
        return {
            'type': 'ir.actions.act_url',
            'url': f'/web#menu_id={menu_id}',
            'target': 'self',
        }

    def update_app_list(self,compute_need=True):
        self.env['ir.module.module'].update_list()
        self.generate_zoho_application()
        menu_id = self.env.ref("tl_odoo_zoho_integration.menu_zoho_application").id
        return {
            'type': 'ir.actions.act_url',
            'url': f'/web#menu_id={menu_id}',
            'target': 'self',
        }

    def generate_zoho_application(self):
        # Addons depending on 'tl_odoo_zoho_integration'. Match on the stored dependency
        # name: 'depend_id' is computed and its search only accepts ids in Odoo 19.
        sub_addons = self.env['ir.module.module'].search(
            [('dependencies_id.name', '=', 'tl_odoo_zoho_integration')])

        for addon in sub_addons:
            application = self.env['zoho.config.application'].search([('addon_id', '=', addon.id)], limit=1)
            if not application:
                self.env['zoho.config.application'].create({
                    'name': str(addon.shortdesc).replace('Connector', '').strip(),
                    'addon_name': addon.name,
                    'addon_id': addon.id,
                })

    def action_view_addon_info(self):
        self.ensure_one()
        return {
            'type':'ir.actions.act_window',
            'name':self.addon_id.shortdesc,
            'res_model':'ir.module.module',
            'res_id':self.addon_id.id,
            'view_mode':'form',
        }

    def action_view_crons(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Scheduled Actions',
            'res_model': 'ir.cron',
            'view_mode': 'list,form',
            'domain': [('id', 'in', self.cron_ids.ids)],
            'context': {'default_model_id': self._name},
        }
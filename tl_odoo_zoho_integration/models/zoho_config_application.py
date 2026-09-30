from odoo import models, fields, api
from odoo.exceptions import ValidationError


class ZohoApplication(models.Model):
    _name = 'zoho.config.application'
    _description = "Zoho Applications"

    name = fields.Char(string="Name")
    description = fields.Text(string="Description", compute='_compute_description')
    addon_name = fields.Char(string="Addon Name")
    addon_id = fields.Many2one(comodel_name='ir.module.module', compute="_compute_addon_id", store=True, ondelete='cascade')

    addon_state = fields.Selection(string="State", related='addon_id.state', store=True)
    icon_flag = fields.Char(string='Icon Flag', related='addon_id.icon_flag')
    icon = fields.Char(string='Icon', related='addon_id.icon')
    sync_type = fields.Selection([('1way_sync', 'One-way Sync'), ('2way_sync', 'Two-way Sync')], string="Sync type",
                                 default='1way_sync')
    sync_frequency = fields.Selection([('1_hour', 'Every Hour'), ('2_hour', 'Every 2 Hours'), ('once_a_day', 'Once a Day')],
                                      string="Sync Frequency", default='once_a_day', required=True)
    zoho_to_odoo = fields.Boolean(string='Zoho to Odoo', default=True)
    odoo_to_zoho = fields.Boolean(string='Odoo to Zoho')

    config_log_ids = fields.One2many(string="Logs", comodel_name='zoho.config.logs', inverse_name='zoho_config_app_id')
    schedule_ids = fields.One2many(comodel_name='zoho.config.schedule', string="Schedule", inverse_name='zoho_config_app_id')
    config_module_ids = fields.One2many(comodel_name='zoho.config.module', string="Modules", inverse_name='zoho_config_app_id')
    schedule_count = fields.Integer(string="Schedule Count", compute='_compute_schedule_count')
    cron_ids = fields.Many2many(comodel_name='ir.cron', string='Schedule Crons')

    re_schedule = fields.Boolean(string='Reschedule')
    notify_msg = fields.Text(string='Notify Message')

    @api.depends('name', 'zoho_to_odoo', 'odoo_to_zoho', 'sync_frequency')
    def _compute_description(self):
        freq_labels = dict(self._fields['sync_frequency'].selection)
        for rec in self:
            if rec.zoho_to_odoo and rec.odoo_to_zoho:
                sync = "Two-way Sync: Zoho <-> Odoo"
            elif rec.zoho_to_odoo:
                sync = "One-way Sync: Zoho → Odoo"
            else:
                sync = "One-way Sync: Odoo → Zoho"
            every = 'every' if rec.sync_frequency != 'once_a_day' else ''
            rec.description = f"{sync} for {every} {freq_labels.get(rec.sync_frequency, '')} "

    @api.onchange('schedule_ids')
    def _onchange_schedule_ids(self):
        for rec in self:
            modules = rec.schedule_ids.module_id
            if len(modules) != len(rec.schedule_ids.filtered('module_id')):
                raise ValidationError("You cannot select the same Module more than once.")

    def write(self, vals):
        if 'schedule_ids' in vals:
            # Toggle the generated Zoho views with the schedule lines they belong to.
            removed_ids, added_ids = [], []
            for command in vals['schedule_ids']:
                if command[0] == 2:
                    removed_ids.append(command[1])
                elif command[0] in (0, 1) and len(command) > 2 and command[2].get('module_id'):
                    added_ids.append(command[2]['module_id'])
            self.env['zoho.config.schedule'].browse(removed_ids).module_id.view_id.active = False
            self.env['zoho.config.module'].browse(added_ids).view_id.active = True
        if 'sync_frequency' in vals or 'schedule_ids' in vals:
            vals['re_schedule'] = True
        return super().write(vals)

    @api.depends('addon_name')
    def _compute_addon_id(self):
        addons = self.env['ir.module.module'].search([('name', 'in', self.mapped('addon_name'))])
        addon_by_name = {addon.name: addon for addon in addons}
        for rec in self:
            rec.addon_id = addon_by_name.get(rec.addon_name, False)

    @api.depends('schedule_ids')
    def _compute_schedule_count(self):
        for rec in self:
            rec.schedule_count = len(rec.schedule_ids)

    def action_active_all_view(self):
        self.ensure_one()
        self.schedule_ids.module_id.view_id.active = True

    def action_view_logs(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Log History',
            'res_model': 'zoho.config.logs',
            'view_mode': 'list,form',
            'domain': [('zoho_config_app_id', '=', self.id)],
            'target': 'current',
        }

    def action_view_modules(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Modules',
            'res_model': 'zoho.config.module',
            'view_mode': 'kanban,list,form',
            'domain': [('zoho_config_app_id', '=', self.id)],
            'context': {'default_zoho_config_app_id': self.id},
            'target': 'current',
        }

    def action_create_module(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': f'New {self.name} Module',
            'view_mode': 'form',
            'res_model': 'zoho.config.module',
            'context': {'default_zoho_config_app_id': self.id},
        }

    def action_active_addon(self):
        self.ensure_one()
        if self.addon_id:
            self.addon_id.button_immediate_install()
        return self.env['zoho.config']._action_open_menu("tl_odoo_zoho_integration.menu_zoho_configuration")

    def action_deactivate_addon(self):
        self.ensure_one()
        if self.addon_id:
            self.addon_id.button_immediate_uninstall()
        return self.env['zoho.config']._action_open_menu("tl_odoo_zoho_integration.menu_zoho_application")

    def update_app_list(self, compute_need=True):
        self.env['ir.module.module'].update_list()
        self.generate_zoho_application()
        return self.env['zoho.config']._action_open_menu("tl_odoo_zoho_integration.menu_zoho_application")

    @api.model
    def _get_zoho_sub_addons(self):
        """Addons depending on 'tl_odoo_zoho_integration'. Match on the stored dependency
        name: 'depend_id' is computed and its search only accepts ids in Odoo 19."""
        return self.env['ir.module.module'].search([('dependencies_id.name', '=', 'tl_odoo_zoho_integration')])

    @api.model
    def generate_zoho_application(self):
        sub_addons = self._get_zoho_sub_addons()
        existing = set(self.search([('addon_id', 'in', sub_addons.ids)]).mapped('addon_id.name'))
        missing = sub_addons.filtered(lambda addon: addon.name not in existing)
        if missing:
            self.create([{
                'name': str(addon.shortdesc).replace('Connector', '').strip(),
                'addon_name': addon.name,
            } for addon in missing])

    def action_view_addon_info(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': self.addon_id.shortdesc,
            'res_model': 'ir.module.module',
            'res_id': self.addon_id.id,
            'view_mode': 'form',
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

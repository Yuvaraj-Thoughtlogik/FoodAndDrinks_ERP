import logging

from odoo import api, fields, models
from odoo.exceptions import UserError

from odoo.addons.tl_odoo_zoho_integration.models.tl_config_fields_map import BUILTIN_FIELD_TYPES

_logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Basic Zoho CRM module -> Odoo field maps, proposed in the import wizard where
# the user can remove lines or add more before importing.
# ---------------------------------------------------------------------------
def F(name, field, **options):
    """Zoho field ``name`` mapped to the existing Odoo field ``field``."""
    return {'name': name, 'field': field, **options}


def NEW(name, field, ftype='char', **options):
    """Zoho field ``name`` mapped to a new custom Odoo field ``field`` of type ``ftype``."""
    return {'name': name, 'field': field, 'type': ftype, **options}


def DEFAULT(field, value):
    """Odoo-side filter: only records with ``field == value`` belong to the module."""
    return {'name': '_default_field', 'field': field, 'default_value': value, 'is_default': True}


ADDRESS = [
    F('Street', 'street'),
    F('City', 'city'),
    F('Zip_Code', 'zip'),
    F('State', 'state_id', is_non_lookup=True),
    F('Country', 'country_id', is_non_lookup=True),
]

ORDER_LINE_SUBFORM = [
    F('Product_Name', 'product_id', zoho_lookup_module='Products'),
    F('List_Price', 'price_unit'),
    F('Quantity', 'product_uom_qty'),
]

# zoho module name (lower case): (odoo model, addons to install, basic field maps)
MODULE_SPECS = {
    'accounts': ('res.partner', ('contacts',), [
        DEFAULT('is_company', 'True'),
        F('Account_Name', 'name'),
        F('Account_Owner', 'user_id', zoho_lookup_module='users'),
        F('Phone', 'phone'),
        F('Website', 'website'),
        F('Billing_Street', 'street'),
        F('Billing_City', 'city'),
        F('Billing_Code', 'zip'),
        F('Billing_State', 'state_id', is_non_lookup=True),
        F('Billing_Country', 'country_id', is_non_lookup=True),
        F('Description', 'comment'),
        F('Tag', 'category_id', zoho_lookup_module='Tag'),
    ]),
    'contacts': ('res.partner', ('contacts',), [
        DEFAULT('is_company', 'False'),
        F('Full_Name', 'name'),
        F('Email', 'email'),
        F('Phone', 'phone'),
        F('Owner', 'user_id', zoho_lookup_module='users'),
        F('Account_Name', 'parent_id', zoho_lookup_module='Accounts'),
        F('Mailing_Street', 'street'),
        F('Mailing_City', 'city'),
        F('Mailing_Zip', 'zip'),
        F('Mailing_State', 'state_id', is_non_lookup=True),
        F('Mailing_Country', 'country_id', is_non_lookup=True),
        F('Description', 'comment'),
        F('Tag', 'category_id', zoho_lookup_module='Tag'),
    ]),
    'vendors': ('res.partner', ('contacts', 'account'), [  # supplier_rank comes from account
        DEFAULT('supplier_rank', '1'),
        F('Vendor_Name', 'name'),
        F('Vendor_Owner', 'user_id', zoho_lookup_module='users'),
        F('Email', 'email'),
        F('Phone', 'phone'),
        F('Website', 'website'),
        *ADDRESS,
        F('Description', 'comment'),
        F('Tag', 'category_id', zoho_lookup_module='Tag'),
    ]),
    'leads': ('crm.lead', ('crm',), [
        DEFAULT('type', 'lead'),
        F('Full_Name', 'name'),
        F('Full_Name', 'contact_name'),
        F('Company', 'partner_name'),
        F('Designation', 'function'),
        F('Owner', 'user_id', zoho_lookup_module='users'),
        F('Email', 'email_from'),
        F('Phone', 'phone'),
        F('Website', 'website'),
        F('Lead_Source', 'source_id', is_non_lookup=True),
        *ADDRESS,
        F('Description', 'description'),
        F('Tag', 'tag_ids', zoho_lookup_module='Tag'),
    ]),
    'deals': ('crm.lead', ('crm',), [
        DEFAULT('type', 'opportunity'),
        F('Deal_Name', 'name'),
        F('Owner', 'user_id', zoho_lookup_module='users'),
        F('Contact_Name', 'partner_id', zoho_lookup_module='Contacts'),
        F('Amount', 'expected_revenue'),
        F('Probability', 'probability'),
        F('Closing_Date', 'date_deadline'),
        F('Stage', 'stage_id', is_non_lookup=True),
        F('Lead_Source', 'source_id', is_non_lookup=True),
        F('Campaign_Source', 'campaign_id', is_non_lookup=True),
        F('Description', 'description'),
        F('Tag', 'tag_ids', zoho_lookup_module='Tag'),
    ]),
    'products': ('product.template', ('stock',), [
        F('Product_Name', 'name'),
        F('Product_Code', 'default_code'),
        F('Product_Active', 'sale_ok'),
        F('Product_Category', 'categ_id', is_non_lookup=True),
        F('Unit_Price', 'list_price'),
        F('Description', 'description'),
    ]),
    'quotes': ('sale.order', ('sale_management',), [
        F('Subject', 'name'),
        F('Owner', 'user_id', zoho_lookup_module='users'),
        F('Account_Name', 'partner_id', zoho_lookup_module='Accounts'),
        F('Valid_Till', 'validity_date'),
        F('Quoted_Items', 'order_line', subform=ORDER_LINE_SUBFORM),
        F('Terms_and_Conditions', 'note'),
        F('Tag', 'tag_ids', zoho_lookup_module='Tag'),
    ]),
    'sales_orders': ('sale.order', ('sale_management',), [
        F('Subject', 'name'),
        F('Owner', 'user_id', zoho_lookup_module='users'),
        F('Account_Name', 'partner_id', zoho_lookup_module='Accounts'),
        F('Due_Date', 'validity_date'),
        F('Order_Items', 'order_line', subform=ORDER_LINE_SUBFORM),
        F('Terms_and_Conditions', 'note'),
        F('Tag', 'tag_ids', zoho_lookup_module='Tag'),
    ]),
}

RELATIONAL_TYPES = ('many2one', 'many2many', 'one2many')


class ImportModuleNames(models.Model):
    _name = 'zoho.import.module.name'
    _description = "Zoho CRM Module name"
    _order = 'sequence'

    sequence = fields.Integer(string="Sequence", default=1)
    name = fields.Char(string='Name')
    imported = fields.Boolean(string="Imported", default=False)
    is_supported = fields.Boolean(compute='_compute_is_supported', search='_search_is_supported')

    def _compute_is_supported(self):
        for rec in self:
            rec.is_supported = (rec.name or '').lower() in MODULE_SPECS

    def _search_is_supported(self, operator, value):
        if operator not in ('=', '!='):
            raise UserError(f"Unsupported search on 'is_supported': {operator}")
        supported = [rec.id for rec in self.search([]) if rec.is_supported]
        return [('id', 'in' if (operator == '=') == bool(value) else 'not in', supported)]


class ImportModuleWizard(models.TransientModel):
    _name = 'zoho.import.module'
    _description = "Import Base Zoho CRM Modules"

    modules_ids = fields.Many2many(comodel_name='zoho.import.module.name', string="Modules", required=True,
                                   domain="[('imported', '=', False), ('is_supported', '=', True)]")
    zoho_app_id = fields.Many2one(comodel_name='zoho.config.application', string="Zoho Application", readonly=True)
    line_ids = fields.One2many('zoho.import.module.line', 'wizard_id', string="Field Mapping")

    # ------------------------------------------------------------------
    # Step 1: select modules, install the Odoo apps they need
    # ------------------------------------------------------------------
    def action_load_mapping(self):
        self.ensure_one()
        unsupported = self.modules_ids.filtered(lambda m: not m.is_supported)
        if unsupported:
            raise UserError(f"No standard mapping available for: {', '.join(unsupported.mapped('name'))}")
        addons = {addon for module in self.modules_ids for addon in MODULE_SPECS[module.name.lower()][1]}
        self.install_addon(addons)
        if 'leads' in [name.lower() for name in self.modules_ids.mapped('name')]:
            self._enable_crm_leads()
        # Build the mapping in a new request (server action), once the registry
        # knows the models of the apps just installed.
        return {
            'type': 'ir.actions.server',
            'id': self.env.ref('tl_zoho_crm_integration.action_zoho_import_open_mapping').id,
            'context': {'zoho_import_wizard_id': self.id},
        }

    # ------------------------------------------------------------------
    # Step 2: review the mapping (full-page list of lines)
    # ------------------------------------------------------------------
    @api.model
    def _get_from_context(self):
        wizard = self.browse(self.env.context.get('zoho_import_wizard_id')).exists()
        if not wizard:
            raise UserError("This import session has expired. Please start the import again.")
        return wizard

    def action_open_mapping(self):
        self.ensure_one()
        skipped = []
        if not self.line_ids:
            self.line_ids = self._default_line_commands(self.modules_ids, skipped)
        action = {
            'type': 'ir.actions.act_window',
            'name': f"Zoho CRM Import: {', '.join(self.modules_ids.mapped('name'))}",
            'res_model': 'zoho.import.module.line',
            'view_mode': 'list',
            'views': [(self.env.ref('tl_zoho_crm_integration.view_zoho_import_module_line_list').id, 'list')],
            'search_view_id': self.env.ref('tl_zoho_crm_integration.view_zoho_import_module_line_search').id,
            'domain': [('wizard_id', '=', self.id)],
            'context': {
                'zoho_import_wizard_id': self.id,
                'zoho_import_module_ids': self.modules_ids.ids,
                'default_wizard_id': self.id,
                'default_module_name_id': self.modules_ids.id if len(self.modules_ids) == 1 else False,
                'search_default_group_by_module': 1,
            },
            'target': 'current',
        }
        if not skipped:
            return action
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': "Some standard fields are not available",
                'message': "\n".join(skipped),
                'type': 'warning',
                'sticky': True,
                'next': action,
            },
        }

    def install_addon(self, addon_names):
        if isinstance(addon_names, str):
            addon_names = [addon_names]
        to_install = self.env['ir.module.module'].search([('name', 'in', list(addon_names)), ('state', '!=', 'installed')])
        if to_install:
            to_install.button_immediate_install()

    def _enable_crm_leads(self):
        settings = self.env['res.config.settings'].sudo().create({'group_use_lead': True})
        # Apply changes: different methods across versions
        if hasattr(settings, 'execute'):
            settings.execute()
        elif hasattr(settings, 'set_values'):
            settings.set_values()
        self.env['ir.config_parameter'].sudo().set_param('crm.use_leads', True)

    # ------------------------------------------------------------------
    # Default lines from MODULE_SPECS
    # ------------------------------------------------------------------
    def _default_line_commands(self, modules, skipped):
        commands = []
        sequence = 0
        for module in modules:
            model, _addons, field_specs = MODULE_SPECS.get(module.name.lower(), (None, (), []))
            for spec in field_specs:
                sequence += 1
                vals = self._spec_to_line_vals(model, spec, skipped, module.name)
                if vals:
                    commands.append(fields.Command.create(dict(vals, module_name_id=module.id, sequence=sequence)))
        return commands

    def _spec_to_line_vals(self, model, spec, skipped, module_name):
        vals = {key: spec[key] for key in ('name', 'zoho_lookup_module', 'is_non_lookup', 'default_value', 'is_default')
                if key in spec}
        if spec.get('type'):
            vals.update(field_option='new', new_field_name=spec['field'], new_field_type=spec['type'])
            return vals
        field = self.env['ir.model.fields']._get(model, spec['field'])
        if not field:
            # e.g. a field provided by an app that is not installed
            skipped.append(f"{module_name}: '{spec['name']}' skipped, field {model}.{spec['field']} not found.")
            return None
        vals['odoo_field_id'] = field.id
        return vals

    # ------------------------------------------------------------------
    # Step 2: import the reviewed mapping
    # ------------------------------------------------------------------
    def action_confirm(self):
        self.ensure_one()
        Module = self.env['zoho.config.module']
        for module_name in self.modules_ids:
            lines = self.line_ids.filtered(lambda line: line.module_name_id == module_name)
            if not lines:
                raise UserError(f"Add at least one field mapping line for module '{module_name.name}'.")
            odoo_model = self.env['ir.model']._get(MODULE_SPECS[module_name.name.lower()][0])
            module = Module.create({
                'name': module_name.name,
                'odoo_model': odoo_model.id,
                'module_name_id': module_name.id,
                'zoho_config_app_id': self.zoho_app_id.id,
                'fields_ids': [fields.Command.create(line._prepare_field_map_vals()) for line in lines],
            })
            if self.zoho_app_id:
                self.zoho_app_id.write({'schedule_ids': [fields.Command.create({"module_id": module.id})]})
            module_name.imported = True
        if self.zoho_app_id:
            return self.zoho_app_id.action_view_modules()
        return {'type': 'ir.actions.client', 'tag': 'reload'}


class ImportModuleLine(models.TransientModel):
    _name = 'zoho.import.module.line'
    _description = "Zoho CRM Import Field Mapping Line"
    _order = 'sequence, id'

    wizard_id = fields.Many2one('zoho.import.module', ondelete='cascade')
    subform_summary = fields.Char(string="Subform Fields", compute='_compute_subform_summary')
    sequence = fields.Integer(default=10)
    module_name_id = fields.Many2one('zoho.import.module.name', string="Zoho Module")
    odoo_model_id = fields.Many2one('ir.model', string="Odoo Model", compute='_compute_odoo_model_id')

    name = fields.Char(string="Zoho Field", required=True)
    field_option = fields.Selection([('existing', 'Existing Field'), ('new', 'New Field')],
                                    string="Field Option", default='existing', required=True)
    odoo_field_id = fields.Many2one('ir.model.fields', string="Odoo Field", ondelete='cascade',
                                    domain="[('model_id', '=', odoo_model_id)]")
    new_field_name = fields.Char(string="New Field Name", default='x_')
    new_field_type = fields.Selection(BUILTIN_FIELD_TYPES, string="New Field Type", default='char')
    relation_model_id = fields.Many2one('ir.model', string="Relation Model", domain="[('transient', '=', False)]")
    zoho_lookup_module = fields.Char(string="Zoho Lookup Module")
    is_non_lookup = fields.Boolean(string="Non Lookup")
    is_default = fields.Boolean(string="Default Filter")
    default_value = fields.Char(string="Default Value")

    @api.depends('module_name_id')
    def _compute_odoo_model_id(self):
        IrModel = self.env['ir.model']
        for line in self:
            model_name = MODULE_SPECS.get((line.module_name_id.name or '').lower(), (False,))[0]
            line.odoo_model_id = IrModel._get(model_name) if model_name else False

    def _get_subform_specs(self):
        """Standard subform field maps (e.g. Quoted_Items) matching this one2many line."""
        self.ensure_one()
        if self.field_option != 'existing' or self.odoo_field_id.ttype != 'one2many':
            return []
        field_specs = MODULE_SPECS.get((self.module_name_id.name or '').lower(), (None, (), []))[2]
        return next((spec['subform'] for spec in field_specs
                     if spec.get('subform') and spec['name'] == self.name
                     and spec['field'] == self.odoo_field_id.name), [])

    @api.depends('name', 'module_name_id', 'field_option', 'odoo_field_id')
    def _compute_subform_summary(self):
        for line in self:
            line.subform_summary = ', '.join(spec['name'] for spec in line._get_subform_specs())

    def action_import_mapping(self):
        """List header button: import every line of the session, whatever the selection."""
        return self.env['zoho.import.module']._get_from_context().action_confirm()

    @api.onchange('is_default')
    def _onchange_is_default(self):
        if self.is_default:
            self.name = '_default_field'

    def _prepare_field_map_vals(self):
        """Values of the zoho.config.fields.map created from this line."""
        self.ensure_one()
        label = f"{self.module_name_id.name}: '{self.name}'"
        vals = {
            'name': self.name,
            'zoho_lookup_module': self.zoho_lookup_module,
            'is_non_lookup': self.is_non_lookup,
            'is_default': self.is_default,
            'default_value': self.default_value,
        }
        if self.field_option == 'new':
            if not (self.new_field_name or '').startswith('x_') or len(self.new_field_name) < 3:
                raise UserError(f"{label}: new field names must start with 'x_' (e.g. x_custom_field).")
            if self.new_field_type == 'one2many':
                raise UserError(f"{label}: new one2many fields cannot be created from this wizard.")
            if self.new_field_type in RELATIONAL_TYPES and not self.relation_model_id:
                raise UserError(f"{label}: select the relation model of the new {self.new_field_type} field.")
            vals.update(field_option='new', odoo_field_name=self.new_field_name, new_field_type=self.new_field_type,
                        relation_model_id=self.relation_model_id.id)
            return vals
        if not self.odoo_field_id:
            raise UserError(f"{label}: select the Odoo field.")
        vals['odoo_field_id'] = self.odoo_field_id.id
        subform_maps = []
        for spec in self._get_subform_specs():
            if sub_field := self.env['ir.model.fields']._get(self.odoo_field_id.relation, spec['field']):
                subform_maps.append(fields.Command.create({
                    'name': spec['name'],
                    'odoo_field_id': sub_field.id,
                    'zoho_lookup_module': spec.get('zoho_lookup_module'),
                    'is_non_lookup': spec.get('is_non_lookup', False),
                }))
        if subform_maps:
            vals['subform_field_ids'] = subform_maps
        return vals

import logging
import re

from odoo import models, fields, _, api
from odoo.exceptions import ValidationError

from ..utils import slugify

_logger = logging.getLogger(__name__)

BUILTIN_FIELD_TYPES = [
    ('char', 'Char'),
    ('text', 'Text'),
    # ('html', 'HTML'),
    ('boolean', 'Boolean'),
    ('integer', 'Integer'),
    ('float', 'Float'),
    # ('monetary', 'Monetary'),
    ('many2one', 'Many2one'),
    ('one2many', 'One2many'),
    ('many2many', 'Many2many'),
    # ('selection', 'Selection'),
    ('date', 'Date'),
    ('datetime', 'Datetime'),
    ('binary', 'Binary'),
    # ('reference', 'Reference')
]
NEW_FIELD_TYPES = {ftype for ftype, _label in BUILTIN_FIELD_TYPES}
RELATIONAL_TYPES = ('many2one', 'many2many', 'one2many')


class IRModel(models.Model):
    _inherit = 'ir.model'

    @api.depends('name', 'model')
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = f"{rec.name} - {rec.model}"


class IrModelFields(models.Model):
    _inherit = 'ir.model.fields'
    # Allow searching fields by technical name as well as by label.
    _rec_names_search = ['field_description', 'name']

    relation_model_id = fields.Many2one(comodel_name='ir.model', string="Relation Model")

    @api.onchange('relation_model_id')
    def _onchange_relation_model_id(self):
        for rec in self:
            if rec.relation_model_id:
                rec.relation = rec.relation_model_id.model

    @api.onchange('model_id')
    def _onchange_model_id(self):
        for rec in self:
            if rec.model_id:
                rec.model = rec.model_id.model

class ZohoConfigSubformField(models.Model):
    _name = 'zoho.config.subform.fields.map'
    _description = "Subform Field Mapping"

    name = fields.Char("Zoho Subfield", required=True)
    parent_field_id = fields.Many2one('zoho.config.fields.map', string="Parent Subform Field", ondelete='cascade')
    model_id = fields.Many2one(comodel_name='ir.model', string="Model", related='parent_field_id.relation_model_id',
                               store=True)

    odoo_field_id = fields.Many2one(
        'ir.model.fields',
        string="Odoo Field",
        required=True,
        domain="[('model_id','=',model_id)]",
        ondelete='cascade'
    )

    odoo_field_name = fields.Char("Odoo Subfield", compute="_compute_subfield_name", store=True)
    is_non_lookup = fields.Boolean(string="Is Multi Select (Non Lookup)")
    field_type = fields.Selection(BUILTIN_FIELD_TYPES, string="Field Type", compute='_compute_field_type', store=True)
    zoho_lookup_module = fields.Char(string="Zoho Lookup Module Name")


    @api.depends('odoo_field_id')
    def _compute_field_type(self):
        for rec in self:
            rec.field_type = rec.odoo_field_id.ttype if rec.odoo_field_id else False

    @api.depends('odoo_field_id')
    def _compute_subfield_name(self):
        for rec in self:
            rec.odoo_field_name = rec.odoo_field_id.name if rec.odoo_field_id else False

class ZohoConfigFields(models.Model):
    _name = 'zoho.config.fields.map'
    _description = "Zoho Sync Fields"

    # No unique(odoo_field_name, cr_sync_module_id) constraint: a '_default_field' filter may
    # target a field that is also synced (e.g. Sales_Orders user_id). The former
    # _sql_constraints declaration was never applied, Odoo 19 ignores that attribute.

    name = fields.Char(string="Zoho Field Name", required=True)
    cr_sync_module_id = fields.Many2one(
        comodel_name='zoho.config.module',
        string="Module",
        ondelete='cascade'
    )

    model_id = fields.Many2one(
        comodel_name='ir.model',
        string="Model",
    )
    model_name = fields.Char(string="Model Name",related='parent_field_map_id.relation_model')
    odoo_field_id = fields.Many2one(
        'ir.model.fields',
        string="Odoo Field",
        domain="[('model_id','=',model_id)]",
        ondelete='cascade'
    )
    field_option = fields.Selection([
        ('existing', 'Existing Field'),
        ('new', 'New Field'),
    ], string="Field Option", default='existing', required=True)
    restrict_new = fields.Boolean(string="Restrict new")
    odoo_field_name = fields.Char(string="Odoo Field Name", store=True, default='x_')
    is_new_field = fields.Boolean(string="Is New Field", compute='_compute_is_new_field', store=True)
    field_type = fields.Char(string="Field Type",compute='_compute_form_field_id')
    new_field_type = fields.Selection(BUILTIN_FIELD_TYPES, string="Field Type",default='char')
    is_default = fields.Boolean(string="Set Default Value")
    is_non_lookup = fields.Boolean(string="Is Non Lookup")
    default_value = fields.Char(string='Default Value on Sync')

    is_subform = fields.Boolean("Is Subform?", compute='_compute_is_subform')

    relation_model_option = fields.Selection([
        ('existing', 'Existing Model'),
        ('new', 'New Model'),
    ], string="Relation Model Option", default='existing')

    relation_model = fields.Char(
        "Odoo Related Model",
        store=True,
        default='x_',
    )
    zoho_lookup_module = fields.Char(string="Zoho Lookup Module Name")
    parent_field_map_id = fields.Many2one(
        'zoho.config.fields.map',
        string="Parent Field Map"
    )
    subform_field_ids = fields.One2many(
        'zoho.config.fields.map',
        'parent_field_map_id',
        string="Subform Field Mapping"
    )


    relation_model_id = fields.Many2one(
        'ir.model',
        string="Relation Model",
        domain="[('transient', '=', False)]",
        ondelete="cascade",
        compute='_compute_form_field_id'
    )

    zoho_id_field_name = fields.Char(string="Zoho ID Field name",compute='_compute_zoho_id_field')
    zoho_id_field_label = fields.Char(string="Zoho ID Field Label",compute='_compute_zoho_id_field')

    @api.model_create_multi
    def create(self, val_list):
        IrModel = self.env["ir.model"].sudo()
        IrModelFields = self.env["ir.model.fields"].sudo()
        IrModelAccess = self.env["ir.model.access"].sudo()

        for vals in val_list:
            if vals.get("field_option") == "new":
                field_name = vals.get("odoo_field_name")
                if not field_name:
                    raise ValidationError("Odoo field name is required when creating a new field.")
                if not str(field_name).startswith("x_"):
                    raise ValidationError(
                        "Custom field names must start with 'x_'. Example: x_custom_field"
                    )

                field_type = vals.get("new_field_type")
                if not field_type:
                    raise ValidationError("Field type is required when creating a new field.")
                if field_type not in NEW_FIELD_TYPES:
                    raise ValidationError(f"Invalid field type '{field_type}'. Please choose a valid Odoo field type.")
                model = False
                if vals.get('cr_sync_module_id'):
                    module = self.env["zoho.config.module"].browse(vals["cr_sync_module_id"])
                    model = module.odoo_model
                elif vals.get('model_id'):
                    model = IrModel.browse(vals.get('model_id'))
                elif vals.get('model_name'):
                    model = IrModel.search([('model', '=', vals.get('model_name'))], limit=1)

                if not model:
                    raise ValidationError(
                        "Please Select Odoo Model. It is required"
                    )

                relation_model = False
                if field_type in RELATIONAL_TYPES:
                    if vals.get("relation_model_option") == "new":
                        if not vals.get("relation_model"):
                            raise ValidationError(
                                "Relation model name is required when creating a new relation model."
                            )
                        if not str(vals.get("relation_model")).startswith("x_"):
                            raise ValidationError(
                                "Custom relation model names must start with 'x_'. Example: x_custom_model"
                            )
                        relation_model = IrModel.search([("model", "=", vals["relation_model"])], limit=1)
                        if not relation_model:
                            relation_model = IrModel.create({
                                "name": vals["relation_model"].lstrip("x_").replace(".", " ").replace("_", " ").title(),
                                "model": vals["relation_model"],
                                "state": "manual",
                            })
                            IrModelAccess.create({
                                "name": f"access_{vals['relation_model']}_user",
                                "model_id": relation_model.id,
                                "group_id": False,
                                "perm_read": True,
                                "perm_write": True,
                                "perm_create": True,
                                "perm_unlink": True,
                            })

                    else:
                        relation_model_id = vals.get("relation_model_id")
                        if not relation_model_id:
                            raise ValidationError(
                                "You must select a relation model when choosing 'existing' relation model option.")

                        relation_model = IrModel.browse(relation_model_id)

                # Name of the inverse many2one created on the target model for one2many fields
                relation_field_name = f"x_{model.model.strip().replace('.', '_')}_id"

                if field_type == 'one2many' and not IrModelFields.search_count([
                    ('name', '=', relation_field_name),
                    ('model_id', '=', relation_model.id)
                ], limit=1):
                    IrModelFields.create({
                        "name": relation_field_name,
                        "model_id": relation_model.id,
                        "field_description": model.model.strip().replace('.', ' ').title(),
                        "ttype": "many2one",
                        "relation": model.model,  # Relates to the parent model
                        "state": "manual",
                    })

                new_field = IrModelFields.search([
                    ('name', '=', field_name),
                    ('model_id', '=', model.id)
                ], limit=1)
                if not new_field:
                    new_field_vals = {
                        "name": field_name,
                        "model_id": model.id,
                        "field_description": vals.get('name', field_name),
                        "ttype": field_type,
                        "state": "manual",
                    }
                    if relation_model:
                        new_field_vals['relation'] = relation_model.model
                    if field_type == 'one2many':
                        new_field_vals['relation_field'] = relation_field_name
                    new_field = IrModelFields.create(new_field_vals)

                vals.update({
                    "odoo_field_id": new_field.id,
                    "relation_model": relation_model.model if relation_model else '',
                })

            else:
                field_id = vals.get("odoo_field_id")
                if not field_id:
                    raise ValidationError("Odoo field is required.")
                field = IrModelFields.browse(field_id)
                vals.update({
                    "odoo_field_name": field.name,
                    "relation_model": field.relation or '',
                })

            # Always clean field name
            vals['name'] = vals['name'].replace(' ', '_')

        return super().create(val_list)

    @api.onchange('odoo_field_name')
    def _onchange_odoo_field_name(self):
        for rec in self:
            existing_field = self.env["ir.model.fields"].sudo().search([
                ("name", "=", rec.odoo_field_name),
                ("model", "=", rec.model_id.model),
            ], limit=1)
            if existing_field:
                raise ValidationError(
                    f"The field '{rec.odoo_field_name}' already exists in model '{rec.model_id.model}'."
                )

    @api.onchange('is_default')
    def _make_name_default_value(self):
        self.name = "_default_field" if self.is_default else ""

    @api.onchange('name')
    def _onchange_name(self):
        for rec in self:
            if rec.name:
                rec.name = rec.name.replace(' ', '_')
                if rec.restrict_new:
                    rec.odoo_field_name = f'x_{str(rec.name).lower()}'

    @api.onchange('relation_model')
    def _onchange_relation_model(self):
        for rec in self:
            relation_model = self.env["ir.model"].sudo().search([("model", "=", rec.relation_model)], limit=1)
            if relation_model:
                raise ValidationError(f"Relation model {rec.relation_model} already exists.")

    @api.depends('odoo_field_id')
    def _compute_form_field_id(self):
        IrModel = self.env['ir.model'].sudo()
        for rec in self:
            field = rec.odoo_field_id.sudo()
            rec.relation_model_id = IrModel._get(field.relation) if field.relation else False
            rec.field_type = field.ttype or 'char'

    @api.depends('odoo_field_id')
    def _compute_is_subform(self):
        for rec in self:
            rec.is_subform = rec.odoo_field_id.sudo().ttype == 'one2many'

    @api.onchange('field_option')
    def _onchange_field_option(self):
        for rec in self:
            if rec.field_option == 'new' and rec.name:
                rec.odoo_field_name = f'x_{rec.name.lower()}'

    @staticmethod
    def _strip_relational_suffix(field_name):
        return re.sub(r'(_ids|_id|_line)$', '', field_name)

    @api.onchange('new_field_type')
    def _onchange_new_field_type(self):
        suffixes = {'many2one': '_id', 'many2many': '_ids', 'one2many': '_line'}
        for rec in self:
            if rec.odoo_field_name:
                base_name = self._strip_relational_suffix(rec.odoo_field_name)
                rec.odoo_field_name = base_name + suffixes.get(rec.new_field_type, '')
            if rec.restrict_new and rec.new_field_type == 'one2many':
                raise ValidationError(
                    "Creating a 'one2many' field is not supported for subform fields. Please choose a different field type.")

    @api.onchange('relation_model_option')
    def _onchange_relation_model_option(self):
        for rec in self:
            if rec.relation_model_option == 'new' and rec.odoo_field_name:
                rec.relation_model = f'{self._strip_relational_suffix(rec.odoo_field_name)}_model'

    @api.depends('field_option')
    def _compute_is_new_field(self):
        for rec in self:
            rec.is_new_field = rec.field_option == 'new'

    @api.depends('name', 'zoho_lookup_module', 'cr_sync_module_id.name', 'odoo_field_id')
    def _compute_zoho_id_field(self):
        for rec in self:
            module = rec.cr_sync_module_id or rec.parent_field_map_id.cr_sync_module_id
            app_name = (module.zoho_app_name or '').strip()
            if rec.zoho_lookup_module and rec.field_type in ('many2one', 'many2many'):
                lookup = rec.zoho_lookup_module.strip()
                rec.zoho_id_field_name = f"x_{slugify(app_name)}_{slugify(lookup)}_id"
                rec.zoho_id_field_label = f"{app_name} {lookup.replace('_', ' ').title()} ID"
            elif rec.field_type == 'one2many':
                module_name = (module.name or '').strip()
                rec.zoho_id_field_name = f"x_{slugify(app_name)}_{slugify(module_name)}_{rec.name.lower()}"
                rec.zoho_id_field_label = (f"{app_name} {module_name.replace('_', ' ').title()} "
                                           f"{rec.name.strip().replace('_', ' ')}")
            else:
                rec.zoho_id_field_name = ''
                rec.zoho_id_field_label = ''

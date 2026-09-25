import logging,re,base64
from dateutil import parser as date_parser
import pytz
import datetime ,psycopg2
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError
from datetime import date, datetime

def _safe_json(obj):
    """Convert non-serializable objects to serializable form."""
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    elif hasattr(obj, 'id') and hasattr(obj, 'name'):  # likely a recordset
        return {'id': obj.id, 'name': obj.name}
    return str(obj)  # fallback for anything else



_logger = logging.getLogger(__name__)

# from cr_odoo_zoho_sync import ZohoConfig
IGNORED_REQUIRED_FIELDS = {
    'product.template': ['product_variant_ids'],
    'sale.order': ['order_line', 'partner_invoice_id', 'partner_shipping_id'],
    'purchase.order': ['order_line', 'currency_id'],
    'account.move': ['invoice_line_ids', 'journal_id', 'currency_id'],
    'stock.picking': ['move_ids_without_package', 'location_id', 'location_dest_id'],
    'stock.move': ['location_id', 'location_dest_id'],
    # Add more models as needed
}

def label_to_key(val):
    return re.sub(r'\s+', '_', val.strip().lower())

def key_to_label(key):
    key = re.sub(r'_+', ' ', key)            # Replace multiple underscores with space
    return key.title()

def parse_datetime_flexibly(val):
    """
    Attempt to parse a flexible datetime string or datetime object.
    Converts timezone-aware datetimes to naive UTC.

    Args:
        val (str | datetime.datetime): The input datetime string or object.

    Returns:
        (datetime | None, str | None): Parsed naive datetime or None, with an error message if failed.
    """
    if not val:
        return None, "Datetime input is empty or None."

    # If already a datetime object
    if isinstance(val, datetime):
        if val.tzinfo:
            val = val.astimezone(pytz.UTC).replace(tzinfo=None)
        return val, None

    # If input is a string, try to parse it
    if isinstance(val, str):
        try:
            dt = date_parser.parse(val)
            if dt.tzinfo:
                dt = dt.astimezone(pytz.UTC).replace(tzinfo=None)
            return dt, None
        except Exception as e:
            return None, f"Datetime parsing error: {str(e)}"

    return None, f"Unsupported datetime input type: {type(val).__name__}"

class ZohoConfigModule(models.Model):
    _name = 'zoho.config.module'
    _description = "Zoho Sync Modules"
    _order = 'sequence'

    _sql_constraints = [
        ('unique_module_per_application', 'unique(name, zoho_config_app_id)',
         'Each Module name must be unique per Zoho Application.'),
    ]

    name = fields.Char(string="Zoho Module Name", required=True)
    sequence = fields.Integer(string="Sequence", default = 10)
    zoho_config_app_id = fields.Many2one(comodel_name='zoho.config.application',string="Zoho Application",required=True,ondelete='cascade')
    zoho_app_name = fields.Char(related='zoho_config_app_id.name')
    zoho_id_field= fields.Char(string="Zoho ID Field Name",compute='_compute_zoho_id_field')
    addon_name = fields.Char(related='zoho_config_app_id.addon_name')

    odoo_model = fields.Many2one(comodel_name='ir.model', string='Odoo Model', required=True,ondelete='cascade',domain='["&","&","&", ("model", "not ilike", "ir.%"), ("model", "not ilike", "zoho.%"), ("model", "not ilike", "base%"), ("transient", "!=", True)]')
    odoo_model_name = fields.Char(string="Odoo Model Name", compute='_compute_odoo_model_name', store=True)
    last_one_way_sync = fields.Datetime(string="Last Sync Time")
    last_two_way_sync = fields.Datetime(string="Last Two Way Sync Time")
    fields_ids = fields.One2many(
        comodel_name='zoho.config.fields.map',
        inverse_name='cr_sync_module_id',
        string='Fields Map',
    )
    fields_count = fields.Integer(string="Total Fields Maps",compute='_compute_fields_count')
    view_id = fields.Many2one(
        comodel_name='ir.ui.view',
        string='Zoho Inherited View',
        readonly=True,
        help='Reference to the inherited form view created for Zoho fields.',
        compute='_compute_view_id',
        store=True,
        index=True,
    )
    is_view_active = fields.Boolean(related='view_id.active')
    one_way_test_complete = fields.Boolean(string="Test Complete")
    two_way_test_complete = fields.Boolean(string="Test Complete")
    required_fields = fields.Text(string="Required fields", compute='_compute_required_fields')

    is_added_to_sync = fields.Boolean(string="Is Added to Sync",default=False)
    test_case_view_id = fields.Many2one(comodel_name='ir.ui.view',string='Testcase view',ondelete="set null")
    test_case_field_id = fields.Many2one(comodel_name='ir.model.fields',string='Testcase Field',ondelete="set null")

    @api.depends('fields_ids')
    def _compute_fields_count(self):
        for rec in self:
            rec.fields_count = len(rec.fields_ids)

    @api.depends('odoo_model')
    def _compute_required_fields(self):
        for rec in self:
            try:
                if rec.odoo_model:
                    model = self.env[rec.odoo_model_name]
                    required = self.get_required_fields(model)
                    ignored = IGNORED_REQUIRED_FIELDS.get(rec.odoo_model_name, [])
                    rec.required_fields = [rf for rf in required if rf not in ignored]
                else:
                    rec.required_fields = []
            except Exception:
                rec.required_fields = []

    @api.depends('odoo_model')
    def _compute_odoo_model_name(self):
        for rec in self:
            rec.odoo_model_name = rec.odoo_model.model if rec.odoo_model else ""

    @api.depends('zoho_config_app_id','name')
    def _compute_zoho_id_field(self):
        for rec in self:
            field_name =''
            if rec.zoho_config_app_id and rec.name:
                field_name = f"x_{rec.zoho_config_app_id.name.strip().replace(' ','_').lower()}_{rec.name.strip().replace(' ','_').lower()}_id"

            rec.zoho_id_field = field_name or ''

    @api.depends('fields_ids', 'fields_ids.create_date')
    def _compute_view_id(self):
        for rec in self:
            if not rec.create_date:
                if rec.view_id:
                    rec.view_id.unlink()
                continue
            if rec.fields_ids and any(not field.create_date for field in rec.fields_ids):
                if rec.view_id:
                    rec.view_id.unlink()
                continue

            # Remove old view if present
            if rec.view_id:
                rec.view_id.unlink()
                rec.view_id = False

            # Generate new view
            view = rec._generate_inherited_view()
            if view:
                rec.view_id = view

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for rec in records:
            existing_field, inherited_view = rec.create_or_get_dynamic_field(rec.zoho_app_name,
                                                                              rec.odoo_model_name)
            rec.test_case_field_id=existing_field.id
            rec.test_case_view_id=inherited_view.id
        return records

    def write(self, vals):
        if 'odoo_model' in vals or 'zoho_config_app_id' in vals:
            raise ValidationError("You cannot change the main values once it has been set.")
        res = super().write(vals)
        return res

    def unlink(self):
        View = self.env['ir.ui.view'].sudo()
        Field = self.env['ir.model.fields'].sudo()

        view_ids = []
        test_field_ids = []
        field_ids = []

        for rec in self:
            if rec.test_case_view_id:
                view_ids.append(rec.test_case_view_id.id)
            if rec.test_case_field_id:
                test_field_ids.append(rec.test_case_field_id.id)

        res = super().unlink()
        View.browse(view_ids).unlink()
        Field.browse(test_field_ids).unlink()
        return res

    def create_or_get_dynamic_field(self, zoho_app_name, model_name):
        Model = self.env['ir.model'].sudo()
        Field = self.env['ir.model.fields'].sudo()
        View = self.env['ir.ui.view'].sudo()

        model = Model.search([('model', '=', 'zoho.config.testcase.wizard')], limit=1)
        model_name_safe = model_name.strip().replace('.', '_').lower()
        zoho_app_name_safe = zoho_app_name.strip().replace(' ', '_').lower()
        field_name = f'x_{zoho_app_name_safe}_testcase_{model_name_safe}_id'

        base_view = View.search([
            ('model', '=', 'zoho.config.testcase.wizard'),
            ('type', '=', 'form'),
            ('inherit_id', '=', False)
        ], limit=1)

        if not base_view:
            _logger.info(f"🛠️ Base view for zoho.config.testcase.wizard not found: {field_name}")
            return None, None

        existing_field = Field.search([
            ('name', '=', field_name),
            ('model', '=', 'zoho.config.testcase.wizard')
        ], limit=1)

        if not existing_field:
            existing_field = Field.create({
                'name': field_name,
                'field_description': 'Odoo Record',
                'model_id': model.id,
                'model': 'zoho.config.testcase.wizard',
                'ttype': 'many2one',
                'relation': model_name,
                'state': 'manual',
            })
            _logger.info(f"✅ Created field: {field_name}")

        inherited_view = View.search([
            ('inherit_id', '=', base_view.id),
            ('name', '=', f"Inherited: {field_name}")
        ], limit=1)

        default_domain = [
            (field_map.odoo_field_name, '=',
             field_map.default_value if field_map.field_type != 'boolean'
             else field_map.default_value.lower() == 'true')
            for field_map in self.fields_ids if field_map.is_default
        ]

        if not inherited_view:
            xpath_expr = "//field[@name='test_type']"
            arch = f"""
                <data>
                    <xpath expr="{xpath_expr}" position="before">
                        <field name="{field_name}" 
                            invisible="not two_way or odoo_model != '{model_name}' or zoho_app_name != '{zoho_app_name}'" 
                            required="two_way"
                            domain="{default_domain}"/>
                    </xpath>
                </data>
            """
            inherited_view = View.create({
                'name': f"Inherited: {field_name}",
                'type': 'form',
                'model': 'zoho.config.testcase.wizard',
                'inherit_id': base_view.id,
                'arch_base': arch,
            })
            _logger.info(f"🛠️ Created new inherited view with field: {field_name}")

        return existing_field, inherited_view

    def _generate_inherited_view(self):
        IrUiView = self.env["ir.ui.view"].sudo()

        if not self.odoo_model_name:
            raise ValidationError(_("Odoo Model Name is required to create inherited view."))

        base_view = self.env['ir.ui.view'].sudo().search([
            ('model', '=', self.odoo_model_name),
            ('type', '=', 'form'),
            ('inherit_id', '=', False)
        ], limit=1)

        if not base_view:
            return None

        new_fields = self.fields_ids.filtered(lambda f: f.is_new_field)
        # if not new_fields:
        #     return None
        page_label = f"{self.zoho_config_app_id.name.strip().replace('_',' ')} {self.name.strip().replace('_',' ')} Details"

        # Add a custom field for the Zoho ID
        self._add_custom_field(self.odoo_model_name, self.zoho_id_field, 'char',  f"Zoho ID")

        # Separate fields into two groups excluding one2many fields
        field_list = [field for field in list(new_fields) if field.field_type != "one2many"]
        half = (len(field_list) + 1) // 2
        group_1_fields = field_list[:half]
        group_2_fields = field_list[half:]

        # Separate one2many fields into their own group
        one2many_fields = [field for field in list(new_fields) if field.field_type == "one2many"]

        def generate_field_lines(fields_list):
            xml_output = []

            for field in fields_list:
                field_name = field.odoo_field_name
                widget = ""

                # Determine widget based on field type
                if field.field_type == "many2many":
                    widget = "many2many_tags"
                elif field.field_type == "binary":
                    widget = "binary"

                # Start the XML field element
                field_xml = f"<field name='{field_name}'"

                # Add widget if applicable
                if widget:
                    field_xml += f" widget='{widget}'"

                # Close the field tag
                field_xml += "/>"

                # Handle 'one2many' field type and its subfields
                if field.field_type == "one2many":
                    field_xml = f"<group><field name='{field_name}'>\n    <list>\n"
                    if field.subform_field_ids:
                        subfields_xml = generate_field_lines(field.subform_field_ids)
                        field_xml += f"{subfields_xml}\n"
                    field_xml += f"    </list>\n</field></group>"

                xml_output.append(field_xml)

            # Return the complete XML
            return "\n".join(xml_output)


        invisible_query = []
        for field_map in self.fields_ids.filtered("is_default"):
            val = field_map.default_value or ""
            if field_map.field_type == "boolean":
                # Normalize to True/False string
                val = "True" if val.lower() == "true" else "False"
            else:
                # Wrap string-like defaults in quotes for domain expression
                if not val.isdigit():
                    val = f"'{val}'"
            invisible_query.append(f"{field_map.odoo_field_name} != {val}")

        invisible = " or ".join(invisible_query)

        xml_arch = f"""
            <data>
                <xpath expr="//notebook" position="inside">
                    <page string="{page_label}" invisible="{invisible}">
                        <group>
                            <group>
                                <field name="{self.zoho_id_field}" readonly="1"/>
                            </group>
                            <group/>
                            <group>
                                {generate_field_lines(group_1_fields)}
                            </group>
                            <group>
                                {generate_field_lines(group_2_fields)}
                            </group>
                        </group>
                        <!-- Add a separate group for one2many fields -->
                            {generate_field_lines(one2many_fields)}
                    </page>
                </xpath>
            </data>
        """

        view_vals = {
            'name': f"zoho.{(self.name or '').replace(' ', '.').lower()}.inherited.view",
            'type': 'form',
            'model': self.odoo_model_name,
            'inherit_id': base_view.id,
            'arch_base': xml_arch,
        }

        # Search for an existing view with the same name + model + inherit_id
        view = IrUiView.search([
            ('name', '=', view_vals['name']),
            ('model', '=', view_vals['model']),
            ('inherit_id', '=', view_vals['inherit_id']),
        ], limit=1)

        if view:
            # Optional: update arch if you want to overwrite the existing one
            view.write({'arch_base': view_vals['arch_base']})
        else:
            # Create a new view if not found
            view = IrUiView.create(view_vals)

        return view.id

    def action_create_view(self):
        for rec in self:
            view_id = rec._generate_inherited_view()
            if view_id:
                rec.view_id = view_id
        return{
            'type':'ir.actions.client',
            'tag':'reload'
        }

    def action_active_view(self):
        for rec in self:
            # print(rec.view_id)
            rec.view_id.active = True
        return {
            'type': 'ir.actions.client',
            'tag': 'reload'
        }

    def action_inactive_view(self):
        for rec in self:
            rec.view_id.active = False
        return {
            'type': 'ir.actions.client',
            'tag': 'reload'
        }

    def action_view_fields_map(self):
        self.ensure_one()
        return {
            'type':'ir.actions.act_window',
            'name':f'{self.name}: Fields map',
            'res_model':'zoho.config.fields.map',
            'domain':[('cr_sync_module_id','=',self.id)],
            'view_mode':'list,form',
            'view_type':'current',
        }

    def action_create_testcase(self):
        self.ensure_one()
        self.env['zoho.config'].check_ready_to_sync()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Test Case',
            'res_model': 'zoho.config.testcase.wizard',
            'view_mode': 'form',
            'context':{
                'default_config_module_id':self.id,
            },
            'target': 'new',
        }

    def _add_custom_field(self, model_name, name, ttype, label):
        model_rec = self.env['ir.model'].sudo().search([('model', '=', model_name)], limit=1)
        if not model_rec:
            raise ValidationError(f"Model {model_name} not found in ir.model")

        field = self.env['ir.model.fields'].sudo().search([
            ('model_id', '=', model_rec.id),
            ('name', '=', name)
        ], limit=1)

        if not field:
            field = self.env['ir.model.fields'].sudo().create([{
                'name': name,
                'field_description': label,
                'model_id': model_rec.id,
                'model': model_name,
                'ttype': ttype,
                'state': 'manual',
            }])

        return field

    def _add_dynamic_selection_option(self, model_name, field_name, value_label):
        field = self.env['ir.model.fields'].sudo().search([
            ('model', '=', model_name),
            ('name', '=', field_name)
        ], limit=1)

        if not field:
            raise UserError(f"Field {field_name} not found on model {model_name}")

        value_key = label_to_key(value_label)
        exists = self.env['ir.model.fields.selection'].sudo().search([
            ('field_id', '=', field.id),
            ('value', '=', value_key)
        ], limit=1)

        if not exists:
            exists = self.env['ir.model.fields.selection'].sudo().create({
                'field_id': field.id,
                'value': value_key,
                'name': value_label,
                'sequence': 99
            })
            _logger.info(f"Added new selection value '{value_label}' to field {field_name} on model {model_name}")
        return exists

    def get_required_fields(self, model):
        required_fields = []
        Model = model

        # Step 1: Find all required fields that aren't computed or related
        for fname, field in Model._fields.items():
            if not field.required or field.compute or field.related:
                continue
            required_fields.append(fname)

        # Step 2: Filter out those with hardcoded Python defaults
        required_no_default = []
        for fname in required_fields:
            field = Model._fields[fname]
            has_python_default = field.default is not None

            if has_python_default:
                continue  # skip, because default is assigned

            # check if default_get provides a value
            default_vals = Model.with_context({}).default_get([fname])
            if fname in default_vals:
                continue  # skip, default will be auto-set

            required_no_default.append(fname)

        return required_no_default

    def get_selection_key_or_value(self, model_name, field_name, value, check_as='label'):
        """
        Convert between selection key and label based on check_as.

        :param model_name: Technical model name, e.g., 'res.partner'
        :param field_name: The selection field name, e.g., 'category'
        :param value: The key or label to convert
        :param check_as: 'label' to get key, 'key' to get label
        :return: (result, None) if valid, else (None, error_message)
        """
        Model = self.env[model_name]
        field = Model._fields.get(field_name)
        if not field or field.type != 'selection':
            return None, f"Field '{field_name}' is not a selection field on model '{model_name}'"

        selection = field.selection
        if callable(selection):
            selection = selection(self.env)

        if check_as == 'label':
            for key, label in selection:
                if label == value:
                    return key, None
            return None, f"Label '{value}' not found in selection for field '{field_name}'"

        elif check_as == 'key':
            for key, label in selection:
                if key == value:
                    return label, None
            return None, f"Key '{value}' not found in selection for field '{field_name}'"

        return None, f"Invalid 'check_as' value: {check_as} (must be 'key' or 'label')"

    def _get_or_create_zoho_related_record(self, model_name, val, field_info, all_vals=None):
        if all_vals is None:
            all_vals = {}

        def raise_or_none(message):
            return None,message

        if not val:
            return None,'Empty Value'
        try:
            RelModel = self.env[model_name]
        except Exception as e:
            return raise_or_none(f"Invalid model '{model_name}' for field {field_info.odoo_field_name}: {e}")

        if model_name in ['res.users']:
            if not isinstance(val, dict):
                return raise_or_none(f"Invalid value for model '{model_name}': expected dict, got {type(val).__name__}")

            name = (val.get('name') or '').strip()
            email = (val.get('email') or '').strip()

            if name and email:
                user = self.env['res.users'].sudo().search([
                    ('name', '=', name),
                    ('login', '=', email)
                ], limit=1)

                if user:
                    return user.id, None
                return raise_or_none(f"User not found with name='{name}' and email='{email}'")
            else:
                return raise_or_none("Invalid user data: missing name or email")

        if model_name.startswith('ir.'):
            return raise_or_none(f"Cannot create or update records in system model '{model_name}'")
        print(field_info.zoho_id_field_name)
        print(field_info.zoho_id_field_label)

        if model_name in ['res.country', 'res.country.state']:
            name = val.get('name') if isinstance(val, dict) else str(val).strip()
            if not name:
                return raise_or_none(f"Missing name for model '{model_name}'")
            match = RelModel.search([('name', '=', name)], limit=1)
            if match:
                return match.id,None
            return raise_or_none(f"No match in {model_name} for name '{name}'")
        zoho_id= None
        name=None
        if isinstance(val, dict):
            zoho_id = str(val.get('id') or '').strip()
            name = val.get('name') or val.get('full_name') or val.get('email') or val.get('label') or 'Unknown'
            name = str(name).strip()
        elif isinstance(val, str):
            zoho_id = ''
            name = str(val).strip()

        if not name:
            return raise_or_none(f"No valid name found for model '{model_name}'")

        name_field = next((f for f in ['name', 'x_name'] if f in RelModel._fields), None)
        if not name_field:
            name_field = next((f.name for f in RelModel._fields.values() if f.type == 'char'), None)
        if not name_field:
            return raise_or_none(f"No char field found in model '{model_name}'")

        if zoho_id:
            if field_info.zoho_id_field_name not in RelModel._fields:
                self._add_custom_field(model_name, field_info.zoho_id_field_name, 'char', 'Zoho ID')
            existing = RelModel.search([(field_info.zoho_id_field_name, '=', zoho_id)], limit=1)
            if existing:
                return existing.id,None

        elif name:
            existing_by_name = RelModel.search([(name_field, '=', name)], limit=1)
            if existing_by_name:
                return existing_by_name.id,None


        create_vals = {name_field: name}
        if zoho_id:
            create_vals[field_info.zoho_id_field_name] = zoho_id
        print("many2one",RelModel,create_vals)
        try:
            with self.env.cr.savepoint():
                new_record = RelModel.create([create_vals])

                if model_name == 'product.template':
                    product_model = self.env['product.product']
                    # print(field_info.zoho_id_field_name,field_info.zoho_id_field_label)
                    if field_info.zoho_id_field_name not in product_model._fields:
                        self._add_custom_field('product.product', field_info.zoho_id_field_name, 'char', "Zoho ID")
                    variant = new_record.product_variant_id
                    if variant:
                        try:
                            with self.env.cr.savepoint():
                                variant.write({field_info.zoho_id_field_name: zoho_id})
                        except psycopg2.Error as postgres_e:
                            return self.format_postgres_error(postgres_e), None
                        except Exception as e:
                            return str(e),None

                if model_name == 'product.product':
                    template_model = self.env['product.template']
                    print(field_info.zoho_id_field_name, field_info.zoho_id_field_label)

                    if field_info.zoho_id_field_name not in template_model._fields:
                        self._add_custom_field('product.template', field_info.zoho_id_field_name, 'char', "Zoho ID")

                    template = new_record.product_tmpl_id
                    if template:
                        print("have")
                        try:
                            with self.env.cr.savepoint():
                                template.write({field_info.zoho_id_field_name: zoho_id})
                        except psycopg2.Error as postgres_e:
                            return self.format_postgres_error(postgres_e), None
                        except Exception as e:
                            return str(e),None
                _logger.info(f"[ZOHO] Created new {model_name} record: {name_field} = {name}")

                return new_record.id,None


        except psycopg2.Error as postgres_e:
            return raise_or_none(self.format_postgres_error(postgres_e))
        except Exception as e:
            return raise_or_none(f"Failed to create {model_name} with {name_field}={name}: {self.format_postgres_error(e)}")

    def format_postgres_error(self, error):
        """
        Parses a PostgreSQL error (typically from psycopg2) and returns a structured dictionary
        with details about the failed constraint (e.g., NOT NULL violations).

        Args:
            error (Exception): The database exception object (e.g., psycopg2.IntegrityError)

        Returns:
            dict: A structured map containing field, table, row ID, and human-readable details.
        """
        error_str = str(error)

        # Extract field, table, and row ID from error string
        field_match = re.search(r'column "(.*?)"', error_str)
        table_match = re.search(r'relation "(.*?)"', error_str)
        row_match = re.search(r'Failing row contains \((\d+),', error_str)

        # Detect the constraint type from the error message
        if 'violates not-null constraint' in error_str:
            issue = "This field is required but is currently missing (null)."
            details_template = "The row failed to insert/update because '{}' has a NOT NULL constraint."
        elif 'violates unique constraint' in error_str:
            issue = "This field must be unique, but a duplicate value was provided."
            details_template = "The row failed to insert/update because '{}' must be unique."
        else:
            issue = "A database constraint was violated."
            details_template = "The row failed to insert/update due to a constraint on '{}'."

        # Safely get field name for details
        field_name = field_match.group(1) if field_match else "an unknown field"

        error_map = {
            "Field": field_name if field_match else None,
            "Issue": issue,
            "Affected Table": table_match.group(1) if table_match else None,
            "Failing Row ID": int(row_match.group(1)) if row_match else None,
            "Details": details_template.format(field_name)
        }

        return error_map


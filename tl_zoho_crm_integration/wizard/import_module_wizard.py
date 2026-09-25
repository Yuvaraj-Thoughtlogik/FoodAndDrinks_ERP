from odoo import models, fields,api


class ImportModuleNames(models.Model):

    _name = 'zoho.import.module.name'
    _description = "Zoho CRM Module name"
    _order = 'sequence'

    sequence = fields.Integer(string="Sequence",default=1)
    name = fields.Char(string='Name')
    imported = fields.Boolean(string="Imported",default=False)

class ImportModuleWizard(models.TransientModel):

    _name = 'zoho.import.module'
    _description = "Import Base Zoho CRM Modules"

    modules_ids = fields.Many2many(comodel_name='zoho.import.module.name',string="Modules", required = True,domain="[('imported','=',False)]")
    # config_id = fields.Many2one(comodel_name='zoho.config',string="Config", readonly=True)
    zoho_app_id = fields.Many2one(comodel_name='zoho.config.application',string="Zoho Application", readonly=True)

    def action_confirm(self):
        for module in self.modules_ids:
            module_name = module.name
            self.generate_module_fields_map(module_name,module.id)
            module.imported = True
        return {'type': 'ir.actions.client', 'tag': 'reload'}


    def _create_custom_field(self, model, name, label, field_type, selection=None,relation=None):
        # Search if field already exists
        existing = self.env['ir.model.fields'].search([
            ('model', '=', model),
            ('name', '=', name)
        ], limit=1)
        if existing:
            return existing.id

        model_id = self.env['ir.model'].search([('model', '=', model)], limit=1).id
        field_vals = {
            'name': name,
            'field_description': label,
            'model_id': model_id,
            'model': model,
            'ttype': field_type,
            'state':'manual',
        }
        if relation:
            field_vals['relation'] = relation
        if field_type == 'selection' and selection:
            field_vals['selection'] = selection

        return self.env['ir.model.fields'].create(field_vals).id

    def _field_id(self, model, field_name):
        return self.env['ir.model.fields'].search([
            ('model', '=', model), ('name', '=', field_name)
        ], limit=1).id

    def _model_id(self,model):
        return self.env['ir.model'].search([('model','=',model)],limit=1).id

    def generate_fields_map(self, module_name, module_id=None):
        module_name = module_name.lower()
        fields_map = []

        if module_name == 'accounts':
            fields_map = [
                {
                    'name': '_default_field',
                    'odoo_field_id': self._field_id('res.partner', 'is_company'),
                    'default_value': 'True',  # Contacts are individuals
                    'is_default': True,
                    'cr_sync_module_id': module_id,
                },
                {
                    'name': 'Record_Image',
                    'odoo_field_id': self._field_id('res.partner', 'image_1920'),
                    'cr_sync_module_id': module_id,
                },

                # ---- Basic Info ----
                {
                    'name': 'Account_Name',
                    'odoo_field_id': self._field_id('res.partner', 'name'),
                    'cr_sync_module_id': module_id,
                },
                {
                    'name': 'Account_Number',
                    'odoo_field_name': 'x_account_number',
                    'new_field_type': 'integer',
                    'field_option': 'new',
                    'cr_sync_module_id': module_id,
                },
                {
                    'name': 'Account_Owner',
                    'odoo_field_id': self._field_id('res.partner', 'user_id'),
                    'zoho_lookup_module': 'users',
                    'cr_sync_module_id': module_id,
                },
                {
                    'name': 'Account_Site',
                    'odoo_field_name': 'x_account_site',
                    'new_field_type': 'char',
                    'field_option': 'new',
                    'cr_sync_module_id': module_id,
                },
                {
                    'name': 'Account_Type',
                    'odoo_field_name': 'x_account_type',
                    'new_field_type': 'char',
                    'field_option': 'new',
                    'cr_sync_module_id': module_id,
                },
                {
                    'name': 'Annual_Revenue',
                    'odoo_field_name': 'x_annual_revenue',
                    'new_field_type': 'float',
                    'field_option': 'new',
                    'cr_sync_module_id': module_id,
                },

                # ---- Billing Address ----
                {
                    'name': 'Billing_City',
                    'odoo_field_id': self._field_id('res.partner', 'city'),
                    'cr_sync_module_id': module_id,
                },
                {
                    'name': 'Billing_Code',
                    'odoo_field_id': self._field_id('res.partner', 'zip'),
                    'cr_sync_module_id': module_id,
                },
                {
                    'name': 'Billing_Country',
                    'odoo_field_id': self._field_id('res.partner', 'country_id'),
                    'is_non_lookup': True,
                    'cr_sync_module_id': module_id,
                },
                {
                    'name': 'Billing_State',
                    'odoo_field_id': self._field_id('res.partner', 'state_id'),
                    'is_non_lookup': True,
                    'cr_sync_module_id': module_id,
                },
                {
                    'name': 'Billing_Street',
                    'odoo_field_id': self._field_id('res.partner', 'street'),
                    'cr_sync_module_id': module_id,
                },

                # ---- Shipping Address ----
                {
                    'name': 'Shipping_City',
                    'odoo_field_name': 'x_shipping_city',
                    'new_field_type': 'char',
                    'field_option': 'new',
                    'cr_sync_module_id': module_id,
                },
                {
                    'name': 'Shipping_Code',
                    'odoo_field_name': 'x_shipping_zip',
                    'new_field_type': 'char',
                    'field_option': 'new',
                    'cr_sync_module_id': module_id,
                },
                {
                    'name': 'Shipping_Country',
                    'odoo_field_name': 'x_shipping_country',
                    'new_field_type': 'char',
                    'field_option': 'new',
                    'cr_sync_module_id': module_id,
                },
                {
                    'name': 'Shipping_State',
                    'odoo_field_name': 'x_shipping_state',
                    'new_field_type': 'char',
                    'field_option': 'new',
                    'cr_sync_module_id': module_id,
                },
                {
                    'name': 'Shipping_Street',
                    'odoo_field_name': 'x_shipping_street',
                    'new_field_type': 'char',
                    'field_option': 'new',
                    'cr_sync_module_id': module_id,
                },

                # ---- Other Info ----
                {
                    'name': 'Description',
                    'odoo_field_id': self._field_id('res.partner', 'comment'),
                    'cr_sync_module_id': module_id,
                },
                {
                    'name': 'Employees',
                    'odoo_field_name': 'x_employees',
                    'new_field_type': 'integer',
                    'field_option': 'new',
                    'cr_sync_module_id': module_id,
                },
                {
                    'name': 'Fax',
                    'odoo_field_name': 'x_fax',
                    'new_field_type': 'char',
                    'field_option': 'new',
                    'cr_sync_module_id': module_id,
                },
                {
                    'name': 'Industry',
                    'odoo_field_id': self._field_id('res.partner', 'industry_id'),
                    'is_non_lookup': True,
                    'cr_sync_module_id': module_id,
                },
                {
                    'name': 'Ownership',
                    'odoo_field_name': 'x_ownership',
                    'new_field_type': 'char',
                    'field_option': 'new',
                    'cr_sync_module_id': module_id,
                },
                {
                    'name': 'Phone',
                    'odoo_field_id': self._field_id('res.partner', 'phone'),
                    'cr_sync_module_id': module_id,
                },
                {
                    'name': 'Rating',
                    'odoo_field_name': 'x_rating',
                    'new_field_type': 'char',
                    'field_option': 'new',
                    'cr_sync_module_id': module_id,
                },
                {
                    'name': 'SIC_Code',
                    'odoo_field_id': self._field_id('res.partner', 'company_registry'),
                    'cr_sync_module_id': module_id,
                },
                {
                    'name': 'Tag',
                    'odoo_field_id': self._field_id('res.partner', 'category_id'),
                    'zoho_lookup_module': "Tag",
                    'cr_sync_module_id': module_id,
                },
                {
                    'name': 'Ticker_Symbol',
                    'odoo_field_name': 'x_ticker_symbol',
                    'new_field_type': 'char',
                    'field_option': 'new',
                    'cr_sync_module_id': module_id,
                },
                {
                    'name': 'Website',
                    'odoo_field_id': self._field_id('res.partner', 'website'),
                    'cr_sync_module_id': module_id,
                },
            ]

        elif module_name == 'contacts':
            fields_map = [
                {
                    'name': '_default_field',
                    'odoo_field_id': self._field_id('res.partner', 'is_company'),
                    'default_value': 'False',  # Contacts are individuals
                    'is_default': True,
                    'cr_sync_module_id': module_id,
                },

                # ---- Image ----
                {
                    'name': 'Record_Image',
                    'odoo_field_id': self._field_id('res.partner', 'image_1920'),
                    'cr_sync_module_id': module_id,
                },

                # ---- Basic Info ----
                {
                    'name': 'Salutation',
                    'odoo_field_name': 'x_salutation',
                    'new_field_type': 'char',
                    'field_option': 'new',
                    'cr_sync_module_id': module_id,
                },
                {
                    'name': 'First_Name',
                    'odoo_field_name': 'x_first_name',
                    'new_field_type': 'char',
                    'field_option': 'new',
                    'cr_sync_module_id': module_id,
                },
                {
                    'name': 'Last_Name',
                    'odoo_field_name': 'x_last_name',
                    'new_field_type': 'char',
                    'field_option': 'new',
                    'cr_sync_module_id': module_id,
                },
                {
                    'name': 'Full_Name',
                    'odoo_field_id': self._field_id('res.partner', 'name'),
                    'cr_sync_module_id': module_id,
                },
                {
                    'name': 'Title',
                    'odoo_field_id': self._field_id('res.partner', 'title'),
                    'is_non_lookup': True,
                    'cr_sync_module_id': module_id,
                },
                {
                    'name': 'Department',
                    'odoo_field_name': 'x_department',
                    'new_field_type': 'char',
                    'field_option': 'new',
                    'cr_sync_module_id': module_id,
                },

                # ---- Owner / Account ----
                {
                    'name': 'Owner',
                    'odoo_field_id': self._field_id('res.partner', 'user_id'),
                    'zoho_lookup_module': 'users',
                    'cr_sync_module_id': module_id,
                },
                {
                    'name': 'Account_Name',
                    'odoo_field_id': self._field_id('res.partner', 'parent_id'),
                    'zoho_lookup_module': 'Accounts',
                    'cr_sync_module_id': module_id,
                },
                {
                    'name': 'Vendor_Name',
                    'odoo_field_name': 'x_vendor_id',
                    'new_field_type': 'many2one',
                    'field_option': 'new',
                    'relation_model_id': self._model_id('res.partner'),
                    'zoho_lookup_module': 'Vendors',
                    'cr_sync_module_id': module_id,
                },

                # ---- Contact Info ----
                {
                    'name': 'Phone',
                    'odoo_field_id': self._field_id('res.partner', 'phone'),
                    'cr_sync_module_id': module_id,
                },
                {
                    'name': 'Mobile',
                    'odoo_field_id': self._field_id('res.partner', 'mobile'),
                    'cr_sync_module_id': module_id,
                },
                {
                    'name': 'Home_Phone',
                    'odoo_field_name': 'x_home_phone',
                    'new_field_type': 'char',
                    'field_option': 'new',
                    'cr_sync_module_id': module_id,
                },
                {
                    'name': 'Asst_Phone',
                    'odoo_field_name': 'x_asst_phone',
                    'new_field_type': 'char',
                    'field_option': 'new',
                    'cr_sync_module_id': module_id,
                },
                {
                    'name': 'Other_Phone',
                    'odoo_field_name': 'x_other_phone',
                    'new_field_type': 'char',
                    'field_option': 'new',
                    'cr_sync_module_id': module_id,
                },
                {
                    'name': 'Fax',
                    'odoo_field_name': 'x_fax',
                    'new_field_type': 'char',
                    'field_option': 'new',
                    'cr_sync_module_id': module_id,
                },
                {
                    'name': 'Email',
                    'odoo_field_id': self._field_id('res.partner', 'email'),
                    'cr_sync_module_id': module_id,
                },
                {
                    'name': 'Secondary_Email',
                    'odoo_field_name': 'x_secondary_email',
                    'new_field_type': 'char',
                    'field_option': 'new',
                    'cr_sync_module_id': module_id,
                },
                {
                    'name': 'Skype_ID',
                    'odoo_field_name': 'x_skype',
                    'new_field_type': 'char',
                    'field_option': 'new',
                    'cr_sync_module_id': module_id,
                },
                {
                    'name': 'Twitter',
                    'odoo_field_name': 'x_twitter',
                    'new_field_type': 'char',
                    'field_option': 'new',
                    'cr_sync_module_id': module_id,
                },
                {
                    'name': 'Assistant',
                    'odoo_field_name': 'x_assistant',
                    'new_field_type': 'char',
                    'field_option': 'new',
                    'cr_sync_module_id': module_id,
                },

                # ---- Address: Mailing ----
                {
                    'name': 'Mailing_Street',
                    'odoo_field_id': self._field_id('res.partner', 'street'),
                    'cr_sync_module_id': module_id,
                },
                {
                    'name': 'Mailing_City',
                    'odoo_field_id': self._field_id('res.partner', 'city'),
                    'cr_sync_module_id': module_id,
                },
                {
                    'name': 'Mailing_State',
                    'odoo_field_id': self._field_id('res.partner', 'state_id'),
                    'is_non_lookup': True,
                    'cr_sync_module_id': module_id,
                },
                {
                    'name': 'Mailing_Country',
                    'odoo_field_id': self._field_id('res.partner', 'country_id'),
                    'is_non_lookup': True,
                    'cr_sync_module_id': module_id,
                },
                {
                    'name': 'Mailing_Zip',
                    'odoo_field_id': self._field_id('res.partner', 'zip'),
                    'cr_sync_module_id': module_id,
                },

                # ---- Address: Other ----
                {
                    'name': 'Other_Street',
                    'odoo_field_name': 'x_other_street',
                    'new_field_type': 'char',
                    'field_option': 'new',
                    'cr_sync_module_id': module_id,
                },
                {
                    'name': 'Other_City',
                    'odoo_field_name': 'x_other_city',
                    'new_field_type': 'char',
                    'field_option': 'new',
                    'cr_sync_module_id': module_id,
                },
                {
                    'name': 'Other_State',
                    'odoo_field_name': 'x_other_state',
                    'new_field_type': 'char',
                    'field_option': 'new',
                    'is_non_lookup': True,
                    'cr_sync_module_id': module_id,
                },
                {
                    'name': 'Other_Country',
                    'odoo_field_name': 'x_other_country',
                    'new_field_type': 'char',
                    'field_option': 'new',
                    'is_non_lookup': True,
                    'cr_sync_module_id': module_id,
                },
                {
                    'name': 'Other_Zip',
                    'odoo_field_name': 'x_other_zip',
                    'new_field_type': 'char',
                    'field_option': 'new',
                    'cr_sync_module_id': module_id,
                },

                # ---- Profile & Details ----
                {
                    'name': 'Lead_Source',
                    'odoo_field_name': 'x_lead_source',
                    'new_field_type': 'char',
                    'field_option': 'new',
                    'cr_sync_module_id': module_id,
                },
                {
                    'name': 'Date_of_Birth',
                    'odoo_field_name': 'x_date_of_birth',
                    'new_field_type': 'date',
                    'field_option': 'new',
                    'cr_sync_module_id': module_id,
                },
                {
                    'name': 'Description',
                    'odoo_field_id': self._field_id('res.partner', 'comment'),
                    'cr_sync_module_id': module_id,
                },
                {
                    'name': 'Tag',
                    'odoo_field_id': self._field_id('res.partner', 'category_id'),
                    'zoho_lookup_module': 'Tag',
                    'cr_sync_module_id': module_id,
                },
            ]

        elif module_name == 'leads':
            fields_map = [
                {
                    'name': '_default_field',
                    'odoo_field_id': self._field_id('crm.lead', 'type'),
                    'default_value': 'lead',  # default type is lead
                    'is_default': True,
                    'cr_sync_module_id': module_id,
                },
                {
                    'name': 'Record_Image',
                    'odoo_field_id': self._field_id('res.partner', 'image_1920'),
                    'cr_sync_module_id': module_id,
                },

                # ---- Basic Info ----
                {
                    'name': 'Full_Name',
                    'odoo_field_id': self._field_id('res.partner', 'name'),
                    'cr_sync_module_id': module_id,
                },
                {
                    'name': 'First_Name',
                    'odoo_field_name': 'x_first_name',
                    'new_field_type': 'char',
                    'field_option': 'new',
                    'cr_sync_module_id': module_id,
                },
                {
                    'name': 'Last_Name',
                    'odoo_field_name': 'x_last_name',
                    'new_field_type': 'char',
                    'field_option': 'new',
                    'cr_sync_module_id': module_id,
                },
                {
                    'name': 'Full_Name',
                    'odoo_field_id': self._field_id('crm.lead', 'contact_name'),
                    'cr_sync_module_id': module_id,
                },
                {
                    'name': 'Salutation',
                    'odoo_field_id': self._field_id('crm.lead', 'title'),
                    'is_non_lookup': True,
                    'cr_sync_module_id': module_id,
                },
                {
                    'name': 'Company',
                    'odoo_field_id': self._field_id('crm.lead', 'partner_name'),
                    'cr_sync_module_id': module_id,
                },
                {
                    'name': 'Designation',
                    'odoo_field_id': self._field_id('crm.lead', 'function'),
                    'cr_sync_module_id': module_id,
                },
                {
                    'name': 'Owner',
                    'odoo_field_id': self._field_id('crm.lead', 'user_id'),
                    'zoho_lookup_module': 'users',
                    'cr_sync_module_id': module_id,
                },

                # ---- Contact Info ----
                {
                    'name': 'Email',
                    'odoo_field_id': self._field_id('crm.lead', 'email_from'),
                    'cr_sync_module_id': module_id,
                },
                {
                    'name': 'Secondary_Email',
                    'odoo_field_name': 'x_secondary_email',
                    'new_field_type': 'char',
                    'field_option': 'new',
                    'cr_sync_module_id': module_id,
                },
                {
                    'name': 'Phone',
                    'odoo_field_id': self._field_id('crm.lead', 'phone'),
                    'cr_sync_module_id': module_id,
                },
                {
                    'name': 'Mobile',
                    'odoo_field_id': self._field_id('crm.lead', 'mobile'),
                    'cr_sync_module_id': module_id,
                },
                {
                    'name': 'Fax',
                    'odoo_field_name': 'x_fax',
                    'new_field_type': 'char',
                    'field_option': 'new',
                    'cr_sync_module_id': module_id,
                },
                {
                    'name': 'Skype_ID',
                    'odoo_field_name': 'x_skype_id',
                    'new_field_type': 'char',
                    'field_option': 'new',
                    'cr_sync_module_id': module_id,
                },
                {
                    'name': 'Twitter',
                    'odoo_field_name': 'x_twitter',
                    'new_field_type': 'char',
                    'field_option': 'new',
                    'cr_sync_module_id': module_id,
                },
                {
                    'name': 'Website',
                    'odoo_field_id': self._field_id('crm.lead', 'website'),
                    'cr_sync_module_id': module_id,
                },

                # ---- Lead Info ----
                {
                    'name': 'Lead_Source',
                    'odoo_field_id': self._field_id('crm.lead', 'source_id'),
                    'is_non_lookup': True,
                    'cr_sync_module_id': module_id,
                },
                {
                    'name': 'Lead_Status',
                    'odoo_field_name': 'x_lead_status',
                    'new_field_type': 'char',
                    'field_option': 'new',
                    'cr_sync_module_id': module_id,
                },
                {
                    'name': 'Industry',
                    'odoo_field_id': self._field_id('crm.lead', 'industry_id'),
                    'is_non_lookup': True,
                    'cr_sync_module_id': module_id,
                },
                {
                    'name': 'Annual_Revenue',
                    'odoo_field_name': 'x_annual_revenue',
                    'new_field_type': 'float',
                    'field_option': 'new',
                    'cr_sync_module_id': module_id,
                },
                {
                    'name': 'No_of_Employees',
                    'odoo_field_name': 'x_employees',
                    'new_field_type': 'integer',
                    'field_option': 'new',
                    'cr_sync_module_id': module_id,
                },
                {
                    'name': 'Rating',
                    'odoo_field_name': 'x_rating',
                    'new_field_type': 'char',
                    'field_option': 'new',
                    'cr_sync_module_id': module_id,
                },

                # ---- Address ----
                {
                    'name': 'Street',
                    'odoo_field_id': self._field_id('crm.lead', 'street'),
                    'cr_sync_module_id': module_id,
                },
                {
                    'name': 'City',
                    'odoo_field_id': self._field_id('crm.lead', 'city'),
                    'cr_sync_module_id': module_id,
                },
                {
                    'name': 'State',
                    'odoo_field_id': self._field_id('crm.lead', 'state_id'),
                    'is_non_lookup': True,
                    'cr_sync_module_id': module_id,
                },
                {
                    'name': 'Country',
                    'odoo_field_id': self._field_id('crm.lead', 'country_id'),
                    'is_non_lookup': True,
                    'cr_sync_module_id': module_id,
                },
                {
                    'name': 'Zip_Code',
                    'odoo_field_id': self._field_id('crm.lead', 'zip'),
                    'cr_sync_module_id': module_id,
                },

                # ---- Other Info ----
                {
                    'name': 'Description',
                    'odoo_field_id': self._field_id('crm.lead', 'description'),
                    'cr_sync_module_id': module_id,
                },
                {
                    'name': 'Tag',
                    'odoo_field_id': self._field_id('crm.lead', 'tag_ids'),
                    'zoho_lookup_module': 'Tag',
                    'cr_sync_module_id': module_id,
                },
            ]

        elif module_name == 'deals':
            fields_map = [
                {
                    'name': '_default_field',
                    'odoo_field_id': self._field_id('crm.lead', 'type'),
                    'default_value': 'opportunity',  # default type is opportunity
                    'is_default': True,
                    'cr_sync_module_id': module_id,
                },

                # ---- Core Fields ----
                {
                    'name': 'Deal_Name',
                    'odoo_field_id': self._field_id('crm.lead', 'name'),
                    'cr_sync_module_id': module_id,
                },
                {
                    'name': 'Owner',
                    'odoo_field_id': self._field_id('crm.lead', 'user_id'),
                    'zoho_lookup_module': 'users',
                    'cr_sync_module_id': module_id,
                },
                {
                    'name': 'Account_Name',
                    'odoo_field_name': 'x_account_name',
                    'new_field_type': 'many2one',
                    'field_option': 'new',
                    'relation_model_id': self._model_id('res.partner'),
                    'cr_sync_module_id': module_id,
                },
                {
                    'name': 'Contact_Name',
                    'odoo_field_id': self._field_id('crm.lead', 'partner_id'),
                    'zoho_lookup_module': 'Contacts',
                    'cr_sync_module_id': module_id,
                },

                # ---- Financials ----
                {
                    'name': 'Amount',
                    'odoo_field_id': self._field_id('crm.lead', 'planned_revenue'),
                    'cr_sync_module_id': module_id,
                },
                {
                    'name': 'Expected_Revenue',
                    'odoo_field_id': self._field_id('crm.lead', 'expected_revenue'),
                    'cr_sync_module_id': module_id,
                },
                {
                    'name': 'Probability',
                    'odoo_field_id': self._field_id('crm.lead', 'probability'),
                    'cr_sync_module_id': module_id,
                },

                # ---- Dates ----
                {
                    'name': 'Closing_Date',
                    'odoo_field_id': self._field_id('crm.lead', 'date_deadline'),
                    'cr_sync_module_id': module_id,
                },
                {
                    'name': 'Next_Step',
                    'odoo_field_name': 'x_next_step',
                    'new_field_type': 'char',
                    'field_option': 'new',
                    'cr_sync_module_id': module_id,
                },

                # ---- Classification ----
                {
                    'name': 'Stage',
                    'odoo_field_id': self._field_id('crm.lead', 'stage_id'),
                    'is_non_lookup': True,
                    'cr_sync_module_id': module_id,
                },
                {
                    'name': 'Type',
                    'odoo_field_name': 'x_deal_type',
                    'new_field_type': 'char',
                    'field_option': 'new',
                    'cr_sync_module_id': module_id,
                },
                {
                    'name': 'Lead_Source',
                    'odoo_field_id': self._field_id('crm.lead', 'source_id'),
                    'is_non_lookup': True,
                    'cr_sync_module_id': module_id,
                },
                {
                    'name': 'Campaign_Source',
                    'odoo_field_id': self._field_id('crm.lead', 'campaign_id'),
                    'is_non_lookup': True,
                    'cr_sync_module_id': module_id,
                },

                # ---- Other Info ----
                {
                    'name': 'Description',
                    'odoo_field_id': self._field_id('crm.lead', 'description'),
                    'cr_sync_module_id': module_id,
                },
                {
                    'name': 'Record_Image',
                    'odoo_field_name': 'x_deal_image',
                    'new_field_type': 'binary',
                    'field_option': 'new',
                    'cr_sync_module_id': module_id,
                },
                {
                    'name': 'Tag',
                    'odoo_field_id': self._field_id('crm.lead', 'tag_ids'),
                    'zoho_lookup_module': 'Tag',
                    'cr_sync_module_id': module_id,
                },
            ]

        elif module_name == 'vendors':
            fields_map = [
                {
                    'name': '_default_field',
                    'odoo_field_id': self._field_id('res.partner', 'supplier_rank'),
                    'default_value': 1,  # Mark as vendor
                    'is_default': True,
                    'cr_sync_module_id': module_id,
                },

                # ---- Basic Info ----
                {
                    'name': 'Vendor_Name',
                    'odoo_field_id': self._field_id('res.partner', 'name'),
                    'cr_sync_module_id': module_id,
                },
                {
                    'name': 'Vendor_Owner',
                    'odoo_field_id': self._field_id('res.partner', 'user_id'),
                    'zoho_lookup_module': 'users',
                    'cr_sync_module_id': module_id,
                },
                {
                    'name': 'Email',
                    'odoo_field_id': self._field_id('res.partner', 'email'),
                    'cr_sync_module_id': module_id,
                },
                {
                    'name': 'Phone',
                    'odoo_field_id': self._field_id('res.partner', 'phone'),
                    'cr_sync_module_id': module_id,
                },
                {
                    'name': 'Website',
                    'odoo_field_id': self._field_id('res.partner', 'website'),
                    'cr_sync_module_id': module_id,
                },

                # ---- Address ----
                {
                    'name': 'Street',
                    'odoo_field_id': self._field_id('res.partner', 'street'),
                    'cr_sync_module_id': module_id,
                },
                {
                    'name': 'City',
                    'odoo_field_id': self._field_id('res.partner', 'city'),
                    'cr_sync_module_id': module_id,
                },
                {
                    'name': 'State',
                    'odoo_field_id': self._field_id('res.partner', 'state_id'),
                    'is_non_lookup': True,
                    'cr_sync_module_id': module_id,
                },
                {
                    'name': 'Country',
                    'odoo_field_id': self._field_id('res.partner', 'country_id'),
                    'is_non_lookup': True,
                    'cr_sync_module_id': module_id,
                },
                {
                    'name': 'Zip_Code',
                    'odoo_field_id': self._field_id('res.partner', 'zip'),
                    'cr_sync_module_id': module_id,
                },
                # ---- Other Info ----
                {
                    'name': 'Tag',
                    'odoo_field_id': self._field_id('res.partner', 'category_id'),
                    'zoho_lookup_module': 'Tag',
                    'cr_sync_module_id': module_id,
                },
                {
                    'name': 'Category',
                    'odoo_field_name': 'x_vendor_category',
                    'new_field_type': 'char',
                    'field_option': 'new',
                    'cr_sync_module_id': module_id,
                },
                {
                    'name': 'Description',
                    'odoo_field_id': self._field_id('res.partner', 'comment'),
                    'cr_sync_module_id': module_id,
                },
            ]

        elif module_name == 'products':
            fields_map = [
                # ---- Core Info ----
                {
                    'name': 'Product_Name',
                    'odoo_field_id': self._field_id('product.template', 'name'),
                    'cr_sync_module_id': module_id,
                },
                {
                    'name': 'Product_Code',
                    'odoo_field_id': self._field_id('product.template', 'default_code'),
                    'cr_sync_module_id': module_id,
                },
                {
                    'name': 'Product_Owner',
                    'odoo_field_name': 'x_product_owner_id',
                    'new_field_type': 'many2one',
                    'field_option': 'new',
                    'relation_model_id': self._model_id('res.users'),
                    'zoho_lookup_module': 'users',
                    'cr_sync_module_id': module_id,
                },
                {
                    'name': 'Product_Active',
                    'odoo_field_id': self._field_id('product.template', 'sale_ok'),
                    'cr_sync_module_id': module_id,
                },

                # ---- Classification ----
                {
                    'name': 'Product_Category',
                    'odoo_field_id': self._field_id('product.template', 'categ_id'),
                    'is_non_lookup': True,
                    'cr_sync_module_id': module_id,
                },
                {
                    'name': 'Manufacturer',
                    'odoo_field_name': 'x_manufacturer',
                    'new_field_type': 'char',
                    'field_option': 'new',
                    'cr_sync_module_id': module_id,
                },
                {
                    'name': 'Vendor_Name',
                    'odoo_field_name': 'x_vendor_id',
                    'new_field_type': 'many2one',
                    'field_option': 'new',
                    'relation_model_id': self._model_id('res.partner'),
                    'zoho_lookup_module': 'Vendors',
                    'cr_sync_module_id': module_id,
                },

                # ---- Pricing ----
                {
                    'name': 'Unit_Price',
                    'odoo_field_id': self._field_id('product.template', 'list_price'),
                    'cr_sync_module_id': module_id,
                },
                {
                    'name': 'Commission_Rate',
                    'odoo_field_name': 'x_commission_rate',
                    'new_field_type': 'float',
                    'field_option': 'new',
                    'cr_sync_module_id': module_id,
                },
                {
                    'name': 'Tax',
                    'odoo_field_id': self._field_id('product.template', 'taxes_id'),
                    'is_non_lookup': True,
                    'cr_sync_module_id': module_id,
                },

                # ---- Stock & Dimensions ----
                {
                    'name': 'Quantity_in_Stock',
                    'odoo_field_name': 'x_quantity_in_stock',
                    'new_field_type': 'float',
                    'field_option': 'new',
                    'cr_sync_module_id': module_id,
                },
                {
                    'name': 'Qty_in_Demand',
                    'odoo_field_name': 'x_qty_in_demand',
                    'new_field_type': 'float',
                    'field_option': 'new',
                    'cr_sync_module_id': module_id,
                },
                {
                    'name': 'Reorder_Level',
                    'odoo_field_name': 'x_reorder_level',
                    'new_field_type': 'float',
                    'field_option': 'new',
                    'cr_sync_module_id': module_id,
                },

                # ---- Other Info ----
                {
                    'name': 'Description',
                    'odoo_field_id': self._field_id('product.template', 'description'),
                    'cr_sync_module_id': module_id,
                },
                {
                    'name': 'Product_Image',
                    'odoo_field_id': self._field_id('product.template', 'image_1920'),
                    'cr_sync_module_id': module_id,
                },
                {
                    'name': 'Tag',
                    'odoo_field_name': 'x_product_tag_ids',
                    'new_field_type': 'many2many',
                    'field_option': 'new',
                    'relation_model': 'x_product_tag',
                    'cr_sync_module_id': module_id,
                },
            ]

        elif module_name == 'quotes':
            fields_map = [
                # ---- Core Info ----
                {
                    'name': 'Subject',
                    'odoo_field_id': self._field_id('sale.order', 'name'),
                    'cr_sync_module_id': module_id,
                },
                {
                    'name': 'Owner',
                    'odoo_field_id': self._field_id('sale.order', 'user_id'),
                    'zoho_lookup_module': 'users',
                    'cr_sync_module_id': module_id,
                },
                {
                    'name': 'Account_Name',
                    'odoo_field_id': self._field_id('sale.order', 'partner_id'),
                    'zoho_lookup_module': 'Accounts',
                    'cr_sync_module_id': module_id,
                },
                {
                    'name': 'Contact_Name',
                    'odoo_field_name': 'x_contact_id',
                    'new_field_type': 'many2one',
                    'field_option': 'new',
                    'relation_model_id': self._model_id('res.partner'),
                    'zoho_lookup_module': 'Contacts',
                    'cr_sync_module_id': module_id,
                },

                # ---- Dates ----
                {
                    'name': 'Quote_Date',
                    'odoo_field_id': self._field_id('sale.order', 'date_order'),
                    'cr_sync_module_id': module_id,
                },
                {
                    'name': 'Valid_Till',
                    'odoo_field_id': self._field_id('sale.order', 'validity_date'),
                    'cr_sync_module_id': module_id,
                },

                # ---- Opportunity Link ----
                {
                    'name': 'Opportunity_Name',
                    'odoo_field_name': 'x_opportunity_id',
                    'new_field_type': 'many2one',
                    'field_option': 'new',
                    'relation_model_id': self._model_id('crm.lead'),
                    'zoho_lookup_module': 'Deals',
                    'cr_sync_module_id': module_id,
                },

                # ---- Quoted Items (Subform) ----
                {
                    'name': 'Quoted_Items',
                    'odoo_field_id': self._field_id('sale.order', 'order_line'),
                    'subform_field_ids': [
                        (0, 0, {
                            'name': 'Product_Name',
                            'odoo_field_id': self._field_id('sale.order.line', 'product_id'),
                            'zoho_lookup_module': 'Products',
                        }),
                        (0, 0, {
                            'name': 'List_Price',
                            'odoo_field_id': self._field_id('sale.order.line', 'price_unit'),
                        }),
                        (0, 0, {
                            'name': 'Quantity',
                            'odoo_field_id': self._field_id('sale.order.line', 'product_uom_qty'),
                        }),
                    ],
                    'cr_sync_module_id': module_id,
                },

                # ---- Notes & Others ----
                {
                    'name': 'Terms_and_Conditions',
                    'odoo_field_name': 'x_t_and_c',
                    'new_field_type': 'html',
                    'field_option': 'new',
                    'cr_sync_module_id': module_id,
                },
                {
                    'name': 'Description',
                    'odoo_field_name': 'x_description',
                    'new_field_type': 'text',
                    'field_option': 'new',
                    'cr_sync_module_id': module_id,
                },
                {
                    'name': 'Tag',
                    'odoo_field_id': self._field_id('sale.order', 'tag_ids'),
                    'zoho_lookup_module': 'Tag',
                    'cr_sync_module_id': module_id,
                },
            ]

        elif module_name == 'sales_orders':
            fields_map = [
                # ---- Default field ----
                {
                    'name': '_default_field',
                    'odoo_field_id': self._field_id('sale.order', 'user_id'),
                    'default_value': 'SalesOrders',
                    'is_default': True,
                    'cr_sync_module_id': module_id,
                },

                # ---- Core Fields ----
                {
                    'name': 'Subject',
                    'odoo_field_id': self._field_id('sale.order', 'name'),
                    'cr_sync_module_id': module_id,
                },
                {
                    'name': 'Owner',
                    'odoo_field_id': self._field_id('sale.order', 'user_id'),
                    'zoho_lookup_module': 'Users',
                    'cr_sync_module_id': module_id,
                },
                {
                    'name': 'Account_Name',
                    'odoo_field_id': self._field_id('sale.order', 'partner_id'),
                    'zoho_lookup_module': 'Accounts',
                    'cr_sync_module_id': module_id,
                },
                {
                    'name': 'Contact_Name',
                    'odoo_field_name': 'x_contact_id',
                    'new_field_type': 'many2one',
                    'field_option': 'new',
                    'relation_model_id': self._model_id('res.partner'),
                    'zoho_lookup_module': 'Contacts',
                    'cr_sync_module_id': module_id,
                },
                {
                    'name': 'Potential_Name',
                    'odoo_field_name': 'x_opportunity_id',
                    'new_field_type': 'many2one',
                    'field_option': 'new',
                    'relation_model_id': self._model_id('crm.lead'),
                    'zoho_lookup_module': 'Deals',
                    'cr_sync_module_id': module_id,
                },
                {
                    'name': 'Quote_Name',
                    'odoo_field_name': 'x_quote_id',
                    'new_field_type': 'many2one',
                    'field_option': 'new',
                    'relation_model_id': self._model_id('sale.order'),
                    'zoho_lookup_module': 'Quotes',
                    'cr_sync_module_id': module_id,
                },
                {
                    'name': 'Purchase_Order',
                    'odoo_field_name': 'x_purchase_order',
                    'new_field_type': 'char',
                    'field_option': 'new',
                    'cr_sync_module_id': module_id,
                },
                {
                    'name': 'Carrier',
                    'odoo_field_name': 'x_carrier',
                    'new_field_type': 'char',
                    'field_option': 'new',
                    'cr_sync_module_id': module_id,
                },

                # ---- Dates ----
                {
                    'name': 'Order_Date',
                    'odoo_field_id': self._field_id('sale.order', 'date_order'),
                    'cr_sync_module_id': module_id,
                },
                {
                    'name': 'Due_Date',
                    'odoo_field_id': self._field_id('sale.order', 'validity_date'),
                    'cr_sync_module_id': module_id,
                },

                # ---- Tags ----
                {
                    'name': 'Tag',
                    'odoo_field_id': self._field_id('sale.order', 'tag_ids'),
                    'zoho_lookup_module': 'Tag',
                    'cr_sync_module_id': module_id,
                },

                # ---- Order Lines (Subform) ----
                {
                    'name': 'Order_Items',
                    'odoo_field_id': self._field_id('sale.order', 'order_line'),
                    'subform_field_ids': [
                        (0, 0, {
                            'name': 'Product_Name',
                            'odoo_field_id': self._field_id('sale.order.line', 'product_id'),
                            'zoho_lookup_module': 'Products',
                        }),
                        (0, 0, {
                            'name': 'List_Price',
                            'odoo_field_id': self._field_id('sale.order.line', 'price_unit'),
                        }),
                        (0, 0, {
                            'name': 'Quantity',
                            'odoo_field_id': self._field_id('sale.order.line', 'product_uom_qty'),
                        }),
                    ],
                    'cr_sync_module_id': module_id,
                },

                # ---- Notes / Terms ----
                {
                    'name': 'Terms_and_Conditions',
                    'odoo_field_name': 'x_terms_and_conditions',
                    'new_field_type': 'text',
                    'field_option': 'new',
                    'cr_sync_module_id': module_id,
                },
                {
                    'name': 'Description',
                    'odoo_field_name': 'x_description',
                    'new_field_type': 'text',
                    'field_option': 'new',
                    'cr_sync_module_id': module_id,
                },

            ]

        return fields_map


    def install_addon(self,addon_name):
        module = self.env['ir.module.module'].search([('name', '=', addon_name)], limit=1)
        if module and module.state != 'installed':
            module.button_immediate_install()

    def generate_module_fields_map(self,zoho_module,name_id):
        odoo_model_name = None
        if zoho_module.lower() in ['accounts','contacts','vendors']:
            odoo_model_name = 'res.partner'
            self.install_addon('contacts')
        elif zoho_module.lower() in ['leads','deals']:
            self.install_addon('crm')
            if zoho_module.lower() == 'leads':
                settings = self.env['res.config.settings'].sudo().create({'group_use_lead': True})
                # Apply changes: different methods across versions
                if hasattr(settings, 'execute'):
                    settings.execute()
                elif hasattr(settings, 'set_values'):
                    settings.set_values()
                # Optional: still store the parameter (not enough by itself)
                self.env['ir.config_parameter'].sudo().set_param('crm.use_leads', True)
            odoo_model_name = 'crm.lead'
        elif zoho_module.lower() in ['quotes','sale orders']:
            odoo_model_name = 'sale.order'
            self.install_addon('sale_management')
        elif zoho_module.lower() in ['products']:
            odoo_model_name = 'product.template'
            self.install_addon('stock')

        if odoo_model_name:
            odoo_model = self.env['ir.model'].search([('model', '=', odoo_model_name)], limit=1)

            # Create Zoho config module
            fields_map = self.generate_fields_map(module_name=zoho_module.lower())
            module = self.env['zoho.config.module'].create({
                'name':zoho_module,
                'odoo_model': odoo_model.id,
                'module_name_id':name_id,
                'zoho_config_app_id':self.zoho_app_id.id,
                'fields_ids':[(0, 0, field_map) for field_map in fields_map]
            })

            if self.zoho_app_id:
                self.zoho_app_id.write({
                    'schedule_ids': [(0,0,{"module_id":module.id})]  # Add existing record to O2M field
                })

{
    'name': 'Zoho CRM Connector',
    'version': '1.0',
    'category': 'Tools',
    'summary': 'Zoho CRM integration with Odoo',
    'author': 'Thoughtlogik',
    'website': 'www.thoughtlogik.com',
    'license': 'LGPL-3',
    'depends': ['tl_odoo_zoho_integration'],
    'data': [
        'security/ir.model.access.csv',
        'views/config_application_views.xml',
        'wizard/import_module_wizard.xml',
        'data/zoho_config_module_names.xml',
        'data/zoho_crm_v8_scopes.xml',
        'views/example_model_views.xml',
        'data/base_data.xml',
        # 'data/example_model_fields.xml',
    ],
    'installable': True,
    'application': False,
}

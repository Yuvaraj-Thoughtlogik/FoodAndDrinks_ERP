
{
    'name': 'Odoo Zoho Connector',
    'version': '1.0',
    'category': 'Tools',
    'summary': 'Module for Zoho integration with Odoo',
    'author': 'Thoughtlogik',
    'website': 'www.thoughtlogik.com',
    'license': 'LGPL-3',
    'depends': ['base', 'web', 'base_automation'],
    'data': [
        'security/ir.model.access.csv',
        'views/view_success_message.xml',
        'views/zoho_config_views.xml',
        'views/config_modules_views.xml',
        'views/config_fields_map_views.xml',
        'views/config_application_views.xml',
        'views/config_logs.xml',
        'wizard/test_case_wizard_view.xml',
        'views/actions.xml',
        'data/zoho_config_region_data.xml',
        'data/zoho_live_cron.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'tl_odoo_zoho_integration/static/src/components/json_editor/json_editor_widget.js',
            'tl_odoo_zoho_integration/static/src/components/json_editor/json_editor_template.xml',
            'tl_odoo_zoho_integration/static/src/components/notify_msg/notify_msg_widget.js',
            'tl_odoo_zoho_integration/static/src/components/notify_msg/notify_msg_templates.xml',
            'https://cdn.jsdelivr.net/npm/jsoneditor@9.10.0/dist/jsoneditor.min.css',
            'https://cdn.jsdelivr.net/npm/jsoneditor@9.10.0/dist/jsoneditor.min.js',
            'https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.0/css/all.min.css',
            'tl_odoo_zoho_integration/static/src/js/form_autoreload.js',
            'tl_odoo_zoho_integration/static/src/css/style.css'
        ],
    },

    'installable': True,
    'application': True,
}

{
    'name': 'Round Management',
    'version': '19.0.1.0.0',
    'category': 'Operations/Logistics',
    'summary': 'Manage driver delivery rounds and execution batches.',

    'author': 'ThoughtLogik',
    'website': 'https://www.thoughtlogik.com',

    'depends': [
        'base',
        'sale',
        'stock',
        'fleet',
        'hr'
    ],

    'data': [
        'data/ir_sequence_data.xml',
        'security/ir.model.access.csv',

        'views/round_views.xml',
        'views/round_batch_views.xml',
        'views/sale_order_views.xml',
        'views/res_partner_views.xml',
        'views/fleet_vehicle_views.xml',
        'views/round_sale_order_views.xml',
        'wizard/select_alt_round_wizard_views.xml',
        'wizard/batch_duplicator_view.xml',
        'wizard/bulk_round_change_views.xml',
        'wizard/update_status_wizard_views.xml',
        'wizard/bulk_batch_change_wizard_views.xml',
        'wizard/sale_order_batch_filter_wizard.xml',

        'views/menus.xml',
        'views/round_region_view.xml',
    ],

    'images': [
        'static/description/icon.png',
    ],

    'license': 'LGPL-3',

    'installable': True,
    'application': True,
    'auto_install': False,
}

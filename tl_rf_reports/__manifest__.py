# -*- coding: utf-8 -*-
{
    'name': "Regal Fish Reports",
    'version': '19.0.1.0.0',
    'summary': "Dock Weight Breakdown Report and Analytics for Regal Fish",
    'description': """
        Regal Fish Reports Module
        =========================
        - Reporting menu integrated under Round Management
        - Dock Weight Breakdown Report (grouped by Depot -> Category -> Product)
        - Date range filtering with Late Orders inclusion toggle
    """,
    'category': 'Operations/Logistics',
    'author': "Thoughtlogik Technology Solutions",
    'company': "Thoughtlogik Technology Solutions",
    'maintainer': "Thoughtlogik Technology Solutions",
    'website': "https://thoughtlogik.com",
    'license': 'LGPL-3',
    'depends': [
        'base',
        'web',
        'sale',
        'stock',
        'round_management',
    ],
    'data': [
        'security/ir.model.access.csv',
        'wizard/round_report_wizard_views.xml',
        'report/dock_weight_breakdown_report_views.xml',
        'views/sale_order_views.xml',
        'views/menus.xml',
    ],

    'assets': {
        'web.assets_backend': [
            'tl_rf_reports/static/src/scss/horizontal_checkboxes.scss',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
}

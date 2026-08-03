# -*- coding: utf-8 -*-
# Part of Wicoders Solutions. See LICENSE file for full copyright and licensing details.

{
    'name': 'Record Quick Preview',
    'version': '19.0.0.2',
    'license': 'AGPL-3',
    'category': 'Web',
    'summary': """Quick record preview in popup from list view""",
    'description': """
        This module allows users to quickly preview any record directly from the list view without leaving the page.
        Key Features:
        - Adds an eye icon in list view for quick preview.
        - Opens the record in a popup form view.
        - Fully integrated with Odoo backend views.
        - Lightweight and user-friendly experience.
    """,
    'depends': ['web'],
    'assets': {
        'web.assets_backend': [
            'wc_quick_preview/static/src/views/list/list_view.js',
            'wc_quick_preview/static/src/views/list/list_view.xml',
        ],
    },
    'images': [
        'static/description/banner.png',
    ],
    'author': 'Thoughtlogik',
    'website': 'https://Thoughtlogik.com',
   
    'installable': True,
    'application': False,
    'auto_install': False,
}

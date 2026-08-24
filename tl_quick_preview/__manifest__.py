# -*- coding: utf-8 -*-
{
    'name': 'TL List Quick Preview',
    'version': '19.0.1.0.0',
    'category': 'Extra Tools',
    'summary': 'Quick record preview in popup modal from list view buttons',
    'description': """
        Allows adding quick preview buttons to any list view (e.g. <button name="quick_view" string="View" icon="fa-eye"/> or special="quick_view")
        to open the record in a form view modal popup without leaving the current page.
    """,
    'author': 'Thoughtlogik Technology Solutions',
    'website': 'https://thoughtlogik.com/',
    'license': 'LGPL-3',
    'depends': ['web', 'base'],
    'data': [],
    'assets': {
        'web.assets_backend': [
            'tl_quick_preview/static/src/js/quick_preview.js',
            'tl_quick_preview/static/src/xml/quick_preview.xml',
        ],
    },
    'installable': True,
    'application': False,
    'auto_install': False,
}

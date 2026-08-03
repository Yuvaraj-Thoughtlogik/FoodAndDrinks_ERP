# -*- coding: utf-8 -*-
{
    'name': 'Quick Record Preview',
    'version': '19.0.1.0.0',
    'summary': 'Hover over record names to see quick preview popup',
    'description': """
Quick Record Preview
====================

This module adds a quick preview popup when hovering over record names in list views.
No need to open the form - see key information instantly!

Features:
---------
* Hover over record name to see preview popup
* Shows key fields and information
* Quick actions directly in preview
* Keyboard navigation support
* Works in all list views
* Configurable preview fields
* Smooth animations and positioning

Usage:
------
* Hover over any record name in a list view
* Preview popup appears with key information
* Click quick actions without opening the form
* Press Escape to close preview

Technical Details:
------------------
* Extends ListRenderer to add hover handlers
* Creates preview popup component
* Fetches record data on demand
* Compatible with Odoo 17.0+
    """,
    'category': 'Web',
    'author': 'Thoghtlogik',
    'website': '',
    'depends': ['web'],
    'data': [
        'security/ir.model.access.csv',
        'views/preview_config_views.xml',
        'views/menu.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'quick_record_preview/static/src/js/search_bar.js',
            'quick_record_preview/static/src/js/list_renderer.js',
            'quick_record_preview/static/src/js/kanban_record.js',
            'quick_record_preview/static/src/js/preview_popup.js',
            'quick_record_preview/static/src/xml/list_renderer.xml',
            'quick_record_preview/static/src/xml/kanban_record.xml',
            'quick_record_preview/static/src/xml/preview_popup.xml',
            'quick_record_preview/static/src/css/preview_popup.css',
        ],
    },
    
    'installable': True,
    'application': False,
    'auto_install': False,
    'license': 'LGPL-3',
    'images': ['static/description/banner.gif'],
 
}


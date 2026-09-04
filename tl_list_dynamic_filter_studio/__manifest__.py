{
    'name': 'List Dynamic Filter - Studio Design',
    'version': '19.0.1.2.0',
    'summary': 'Lay out generated filter popups by hand in Odoo Studio',
    'description': """
List Dynamic Filter - Studio Design
===================================

Bridge between *Generic List Dynamic Filter* and Odoo Studio.

Install it from **Settings -> List Dynamic Filters -> Design with Studio**.

Once installed, every filter configuration gains a *Design with Studio* button
that opens its generated popup view in the Studio editor. While a configuration
is marked as Studio designed, the module stops regenerating that popup's layout,
so hand-made changes survive every save. *Reset Design* drops the Studio layers
and hands the popup back to the generator.
    """,
    'author': "Thoughtlogik Technology Solutions",
    'website': "https://thoughtlogik.com/",
    'category': 'Tools',
    'license': 'LGPL-3',
    'depends': [
        'tl_list_dynamic_filter',
        'web_studio',
    ],
    'data': [
        'views/list_filter_configuration_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'tl_list_dynamic_filter_studio/static/src/js/studio_design_button.js',
            'tl_list_dynamic_filter_studio/static/src/xml/studio_design_button.xml',
        ],
    },
    'installable': True,
    'auto_install': False,
}

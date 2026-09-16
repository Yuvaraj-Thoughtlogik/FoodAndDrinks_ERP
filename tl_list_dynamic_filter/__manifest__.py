{
    'name': 'Generic List Dynamic Filter',
    'version': '19.0.6.0.0',
    'summary': 'Configurable multi-field filter popup for any list view',
    'description': """
Generic List Dynamic Filter
===========================

Configure a filter button on any list view. The popup is built dynamically
from the fields you whitelist on the configuration record, and supports every
field type:

* Char / Text / Html  -> contains, does not contain, equals, is set ...
* Integer / Float / Monetary -> =, !=, >, >=, <, <=, between
* Date / Datetime -> between, plus relative presets (today, this month, last year ...)
* Boolean -> yes / no
* Selection -> real dropdown of the field's own options
* Many2one / One2many / Many2many -> contains (display name), exact record, is set

Empty rows are ignored, so the popup behaves like a search bar: fill in what
you care about, leave the rest blank.
    """,
    'author': "Thoughtlogik Technology Solutions",
    'website': "https://thoughtlogik.com/",
    'category': 'Tools',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'base_setup',
        'web',
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/list_filter_configuration_views.xml',
        'views/res_config_settings_views.xml',
        'wizard/list_filter_wizard_views.xml',
    ],
    'post_init_hook': 'post_init_hook',
    'installable': True,
    'application': True,
}

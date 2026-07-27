{
    'name': 'Generic List Date Filter',
    'version': '19.0.1.0.0',
    'summary': 'Generic Date Filter for List Views',
    'description': """
Generic Date Filter
===================
Configure a date filter for any model and automatically create
server actions and list view buttons.
    """,
    'author': "Thoughtlogik Technology Solutions",
    'website': "https://thoughtlogik.com/",
    'version': '1.0',
    'category': 'Tools',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'web',
    ],
    'data': [
        'security/ir.model.access.csv',

        'views/list_filter_configuration_views.xml',
        'wizard/list_date_filter_wizard_views.xml',
    ],
    'installable': True,
    'application': True,
}
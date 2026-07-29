{
    'name': 'UK Address Multi-Postcode Lookup (Ideal Postcodes)',
    'version': '19.0.1.0.0',
    'category': 'Sales/Contacts',
    'summary': 'Lookup UK addresses via Ideal Postcodes supporting single and multi-postcode searches.',
    'author': 'Thoughtlogik',
    'website': 'https://thoughtlogik.com',
    'depends': ['base', 'contacts'],
    'data': [
        'security/ir.model.access.csv',
        'views/res_config_settings_views.xml',
        'views/res_partner_views.xml',
        #'wizard/address_wizard_views.xml',
    ],
    'external_dependencies': {
        'python': ['requests'],
    },
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}

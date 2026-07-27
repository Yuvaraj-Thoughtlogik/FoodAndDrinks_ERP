{
    'name': "RF Custom Contact",
    'author': "Thoughtlogik Technology Solutions",
    'website': "https://thoughtlogik.com/",
    'category': 'Sales/Sales',
    'version': '1.0',

    'depends': [
        'base',
        'product',
        'sale_management',
        'stock',
        'contacts',
    ],

    'data': [
        "security/ir.model.access.csv",
        "data/cron.xml",
        "data/sequence.xml",
        "views/res_partner_views.xml",
        "wizard/close_reason_wizard.xml",
    ],

    'application': False,
    'installable': True,
    'auto_install': False,
}
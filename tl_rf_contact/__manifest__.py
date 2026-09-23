{
    'name': "RF Custom Contact",
    'author': "Thoughtlogik Technology Solutions",
    'website': "https://thoughtlogik.com/",
    'category': 'Sales/Sales',
    'version': '1.0',
    "license": "LGPL-3",
    'depends': [
        'base',
        'product',
        'sale',
        'sale_management',
        'sale_stock',
        'contacts',
        'tl_contact_utm'
    ],

    'data': [
        "security/ir.model.access.csv",
        "data/cron.xml",
        "data/sequence.xml",
        "data/actions.xml",
        "views/res_partner_views.xml",
        "views/res_partner_referral_views.xml",
        "wizard/close_reason_wizard.xml",
    ],

    'application': False,
    'installable': True,
    'auto_install': False,
}
{
    "name": "UK Postcode Address Lookup",
    "version": "19.0.1.0.0",
    "author": "Your Company",
    "website": "",
    "license": "LGPL-3",
    "category": "Contacts",
    "summary": "Lookup UK addresses using postcode",
    "depends": [
        "contacts",
    ],
    "external_dependencies": {
        "python": ["requests"],
    },
    "data": [
        "security/ir.model.access.csv",

        "views/res_partner_views.xml",
        "views/postcode_lookup_views.xml",
        "views/res_config_settings_views.xml",

        "data/ir_config_parameter.xml",
    ],
    "installable": True,
    "application": False,
}

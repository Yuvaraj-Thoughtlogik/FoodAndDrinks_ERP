{
    "name": "Contact Customer Source Audit",
    "summary": "Track customer source changes on contacts with audit logs.",
    "description": """
Contact Customer Source Audit
=============================

Features:
- Adds Customer Source field to Contacts.
- Tracks every Customer Source change.
- Records Previous Source and Current Source.
- Records Changed By and Changed On.
- Records Source Document and Source Reference.
- Smart button on Contact to view audit history.
- Tree, Form, and Search views for audit logs.
""",
    "version": "19.0.1.0.0",
    "author": "Thoughtlogik Technology Solutions",
    "website": "https://thoughtlogik.com",
    "license": "LGPL-3",
    "category": "CRM",
    "depends": [
        "base",
        "contacts",
        "utm",
        "sale",
        "mail",
    ],
    "data": [
        "security/ir.model.access.csv",

        "views/contact_utm_logs_views.xml",
        "views/res_partner_views.xml",
        "views/sale_order_views.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
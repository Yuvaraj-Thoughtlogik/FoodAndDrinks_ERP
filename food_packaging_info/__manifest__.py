{
    'name': 'Food Packaging & Automation',
    'version': '19.0.1.0.0',
    'category': 'Inventory/Packaging',
    'summary': 'Auto-allergen highlighting for product labels',
    'depends': ['product', 'stock', 'sale'],
    'data': [
        'security/ir.model.access.csv',
        'views/product_template_views.xml',
        'views/sale_order_views.xml',
        'views/product_form_view.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}

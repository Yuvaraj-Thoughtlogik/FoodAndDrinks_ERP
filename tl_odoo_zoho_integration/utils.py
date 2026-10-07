"""Helpers shared by the Zoho base connector and its application addons."""
import re
from datetime import date, datetime

import pytz
from dateutil import parser as date_parser

# Timeout (seconds) applied to every HTTP call made to Zoho.
ZOHO_TIMEOUT = 60

IGNORED_REQUIRED_FIELDS = {
    'product.template': ['product_variant_ids'],
    'sale.order': ['order_line', 'partner_invoice_id', 'partner_shipping_id'],
    'purchase.order': ['order_line', 'currency_id'],
    'account.move': ['invoice_line_ids', 'journal_id', 'currency_id'],
    'stock.picking': ['move_ids_without_package', 'location_id', 'location_dest_id'],
    'stock.move': ['location_id', 'location_dest_id'],
}


def safe_json(obj):
    """``json.dumps`` default: convert non-serializable objects to serializable form."""
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if hasattr(obj, 'id') and hasattr(obj, 'name'):  # likely a recordset
        return {'id': obj.id, 'name': obj.name}
    return str(obj)


def slugify(value):
    """'Zoho CRM ' -> 'zoho_crm' (used to build technical field names)."""
    return (value or '').strip().replace(' ', '_').lower()


def label_to_key(val):
    return re.sub(r'\s+', '_', val.strip().lower())


def key_to_label(key):
    return re.sub(r'_+', ' ', key).title()


def parse_datetime_flexibly(val):
    """Parse a datetime string/object and return it as a naive UTC datetime.

    :return: ``(datetime | None, error message | None)``
    """
    if not val:
        return None, "Datetime input is empty or None."
    if isinstance(val, str):
        try:
            val = date_parser.parse(val)
        except Exception as e:
            return None, f"Datetime parsing error: {e}"
    if not isinstance(val, datetime):
        return None, f"Unsupported datetime input type: {type(val).__name__}"
    if val.tzinfo:
        val = val.astimezone(pytz.UTC).replace(tzinfo=None)
    return val, None

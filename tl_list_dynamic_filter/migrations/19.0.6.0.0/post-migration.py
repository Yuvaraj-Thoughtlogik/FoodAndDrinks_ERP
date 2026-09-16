"""Make existing "End Date" inputs follow "Start Date" automatically.

Date-range "to" fields created before this version are plain manual fields.
Re-syncing them regenerates the field with a compute that copies the "from"
value over whenever it changes, while staying editable (``readonly=False``).
"""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return

    env = api.Environment(cr, SUPERUSER_ID, {})

    lines = env['list.filter.config.field'].search([
        ('field_family', '=', 'date'),
        ('wizard_field_to_id', '!=', False),
    ])
    if not lines:
        return
    try:
        lines._sync_wizard_fields()
    except Exception as exc:  # pragma: no cover
        _logger.warning("Could not resync date range wizard fields: %s", exc)

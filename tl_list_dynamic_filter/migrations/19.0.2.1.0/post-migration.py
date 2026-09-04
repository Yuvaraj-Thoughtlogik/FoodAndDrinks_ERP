"""Drop the short-lived condition-grid models and rebuild the form popups."""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)

STALE_MODELS = ('list.filter.wizard.line', 'list.filter.field.option')
STALE_TABLES = ('list_filter_wizard_line', 'list_filter_field_option')


def migrate(cr, version):
    if not version:
        return

    env = api.Environment(cr, SUPERUSER_ID, {})

    stale = env['ir.model'].search([('model', 'in', list(STALE_MODELS))])
    if stale:
        try:
            stale.unlink()
        except Exception as exc:  # pragma: no cover
            _logger.warning("Could not remove obsolete models: %s", exc)

    for table in STALE_TABLES:
        cr.execute("DROP TABLE IF EXISTS %s CASCADE" % table)

    configs = env['list.filter.configuration'].with_context(active_test=False).search([])
    for config in configs:
        try:
            config.field_line_ids._sync_wizard_fields()
            config._rebuild_all()
        except Exception as exc:  # pragma: no cover
            _logger.warning("Could not rebuild list filter %s: %s", config.id, exc)

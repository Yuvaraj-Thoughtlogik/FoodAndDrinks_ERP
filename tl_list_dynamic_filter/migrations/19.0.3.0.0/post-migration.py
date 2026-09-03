"""Remove the debris left by the rename from ``tl_list_date_filter``.

Also rebuilds every popup, since this version dropped the two-column layout.
"""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return

    env = api.Environment(cr, SUPERUSER_ID, {})

    from odoo.addons.tl_list_dynamic_filter.hooks import cleanup_obsolete_records
    cleanup_obsolete_records(env)

    # the two-column layout is gone ("column" is a reserved word, hence quoted)
    cr.execute("ALTER TABLE list_filter_configuration "
               "DROP COLUMN IF EXISTS column_count")
    cr.execute('ALTER TABLE list_filter_config_field '
               'DROP COLUMN IF EXISTS "column"')

    configs = env['list.filter.configuration'].with_context(active_test=False).search([])
    for config in configs:
        try:
            config._rebuild_all()
        except Exception as exc:  # pragma: no cover
            _logger.warning("Could not rebuild list filter %s: %s", config.id, exc)

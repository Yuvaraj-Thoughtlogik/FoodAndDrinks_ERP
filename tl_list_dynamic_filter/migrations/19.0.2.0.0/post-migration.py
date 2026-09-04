"""Upgrade from the date-only version to the dynamic form version.

* the single ``date_field_id`` of every configuration becomes a filter field
  with the ``Is between`` condition,
* the generated wizard fields, popup views, actions and list-view buttons are
  (re)built.
"""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return

    env = api.Environment(cr, SUPERUSER_ID, {})
    ConfigField = env['list.filter.config.field']

    cr.execute("""
        SELECT column_name FROM information_schema.columns
         WHERE table_name = 'list_filter_configuration'
           AND column_name = 'date_field_id'
    """)
    if cr.fetchone():
        cr.execute("""
            SELECT id, date_field_id
              FROM list_filter_configuration
             WHERE date_field_id IS NOT NULL
        """)
        for config_id, field_id in cr.fetchall():
            if ConfigField.search_count([('config_id', '=', config_id),
                                         ('field_id', '=', field_id)]):
                continue
            try:
                ConfigField.create({
                    'config_id': config_id,
                    'field_id': field_id,
                    'sequence': 10,
                    'operator': 'between',
                })
            except Exception as exc:  # pragma: no cover
                _logger.warning(
                    "Could not migrate date field %s of configuration %s: %s",
                    field_id, config_id, exc)
        cr.execute("ALTER TABLE list_filter_configuration DROP COLUMN date_field_id")

    # rebuild everything so old buttons point at the new generated actions
    configs = env['list.filter.configuration'].with_context(active_test=False).search([])
    for config in configs:
        try:
            config.field_line_ids._sync_wizard_fields()
            config._rebuild_all()
        except Exception as exc:  # pragma: no cover
            _logger.warning("Could not rebuild list filter %s: %s", config.id, exc)

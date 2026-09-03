"""Housekeeping for the rename from ``tl_list_date_filter``.

Renaming an addon folder makes Odoo treat it as a brand new module: the old
one stays flagged as installed in the database, and every record its XML
created -- views, actions, menus -- stays alive. Those old views still list
fields this version no longer has (``column_count``, ``date_field_id``...),
which breaks the configuration form with

    ValueError: Invalid field 'column_count' on 'list.filter.configuration'

This removes that debris. It runs on install and on upgrade, and does nothing
when there is no debris to remove.
"""
import logging

_logger = logging.getLogger(__name__)

OBSOLETE_MODULES = ('tl_list_date_filter',)

#: only UI records are dropped -- configurations and their data are kept
CLEANABLE_MODELS = (
    'ir.ui.view',
    'ir.ui.menu',
    'ir.actions.act_window',
    'ir.actions.act_window.view',
    'ir.actions.server',
    'ir.model.access',
)

OUR_MODELS = (
    'list.filter.configuration',
    'list.filter.config.field',
    'list.filter.wizard',
    # models that only existed in intermediate versions
    'list.filter.wizard.line',
    'list.filter.field.option',
)


def cleanup_obsolete_records(env):
    """Drop UI records owned by the pre-rename module."""
    cr = env.cr

    cr.execute(
        "SELECT model, res_id FROM ir_model_data WHERE module IN %s",
        (OBSOLETE_MODULES,),
    )
    grouped = {}
    for model, res_id in cr.fetchall():
        grouped.setdefault(model, []).append(res_id)

    for model, ids in grouped.items():
        if model not in CLEANABLE_MODELS or model not in env:
            continue
        try:
            env[model].browse(ids).exists().sudo().unlink()
        except Exception as exc:  # pragma: no cover
            _logger.warning("Could not remove obsolete %s records: %s", model, exc)

    cr.execute("DELETE FROM ir_model_data WHERE module IN %s", (OBSOLETE_MODULES,))

    cr.execute(
        "UPDATE ir_module_module SET state = 'uninstalled' "
        " WHERE name IN %s AND state NOT IN ('uninstalled', 'uninstallable')",
        (OBSOLETE_MODULES,),
    )

    # Any leftover view on our models that no module owns any more and that we
    # did not generate ourselves would break the UI the same way.
    _drop_orphan_views(env)


def _drop_orphan_views(env):
    cr = env.cr
    generated = set(
        env['list.filter.configuration'].with_context(active_test=False)
        .search([]).mapped('wizard_view_id').ids
    ) | set(
        env['list.filter.configuration'].with_context(active_test=False)
        .search([]).mapped('created_view_id').ids
    )

    cr.execute(
        """
        SELECT v.id
          FROM ir_ui_view v
     LEFT JOIN ir_model_data d
            ON d.model = 'ir.ui.view' AND d.res_id = v.id
         WHERE v.model IN %s
           AND d.id IS NULL
        """,
        (OUR_MODELS,),
    )
    orphans = [row[0] for row in cr.fetchall() if row[0] not in generated]
    if not orphans:
        return
    try:
        env['ir.ui.view'].browse(orphans).exists().sudo().unlink()
        _logger.info("Removed %s orphan list-filter views", len(orphans))
    except Exception as exc:  # pragma: no cover
        _logger.warning("Could not remove orphan list-filter views: %s", exc)


def post_init_hook(env):
    cleanup_obsolete_records(env)

"""Regenerate every popup on the new two-column layout.

Popups laid out in Studio keep their arch: ``_keep_custom_arch`` is what
decides, and the Studio bridge answers True for them.
"""
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return

    env = api.Environment(cr, SUPERUSER_ID, {})

    configs = env['list.filter.configuration'].with_context(
        active_test=False).search([])
    for config in configs:
        try:
            config._rebuild_all()
        except Exception as exc:  # pragma: no cover
            _logger.warning("Could not rebuild list filter %s: %s",
                            config.id, exc)

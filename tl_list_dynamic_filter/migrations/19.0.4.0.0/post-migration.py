"""Give every existing configuration its second, full page action.

Configurations created before this version only had the dialog action
(``target=new``). Rebuilding them creates the page action (``target=current``)
that points at the same generated popup view -- the one Studio is opened on.
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
        if config.wizard_page_action_id:
            continue
        try:
            config._build_wizard_view()
        except Exception as exc:  # pragma: no cover
            _logger.warning(
                "Could not create the page action of list filter %s: %s",
                config.id, exc)

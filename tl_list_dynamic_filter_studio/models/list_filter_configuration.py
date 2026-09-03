import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

#: By default the popup is opened as a full page and the user enters Studio
#: from the top bar -- that works on every version and never calls into
#: Studio's internals.
#:
#: If your build does expose a client action that opens the Studio view editor,
#: put its tag in the system parameter below and it will be used instead. Only
#: an *editor* tag is valid; never a "leave studio" one.
STUDIO_TAG_PARAM = 'tl_list_dynamic_filter.studio_action_tag'


class ListFilterConfiguration(models.Model):
    _inherit = 'list.filter.configuration'

    studio_design = fields.Boolean(
        string="Designed with Studio",
        copy=False,
        help="When set, the popup layout is no longer regenerated from the "
             "filter fields, so changes made in Studio are preserved.",
    )
    studio_view_count = fields.Integer(compute='_compute_studio_view_count')

    # ------------------------------------------------------------------
    @api.depends('wizard_view_id')
    def _compute_studio_view_count(self):
        for rec in self:
            rec.studio_view_count = len(rec._studio_views())

    def _studio_views(self):
        """Views Studio stacked on top of the generated popup view."""
        self.ensure_one()
        if not self.wizard_view_id:
            return self.env['ir.ui.view']
        return self.env['ir.ui.view'].with_context(active_test=False).search([
            ('inherit_id', '=', self.wizard_view_id.id),
        ])

    # ------------------------------------------------------------------
    def _keep_custom_arch(self):
        """Do not overwrite a popup the user laid out in Studio."""
        self.ensure_one()
        return self.studio_design or super()._keep_custom_arch()

    def _blank_wizard_views(self):
        """Refuse to wipe a Studio layout behind the user's back.

        Adding, removing or re-conditioning a filter field rebuilds the
        generated inputs, which means the popup arch has to be rewritten -- and
        that would silently throw away the Studio design.
        """
        locked = self.filtered('studio_design')
        if locked:
            raise UserError(_(
                "The popup of '%s' is designed with Studio, so its layout "
                "cannot be rebuilt automatically.\n\n"
                "Use 'Reset Design' first if you want to change which fields "
                "the popup exposes, or edit the layout in Studio.",
                ', '.join(locked.mapped('name')),
            ))
        return super()._blank_wizard_views()

    # ------------------------------------------------------------------
    def action_open_studio(self):
        """Open this configuration's popup view in the Studio editor."""
        self.ensure_one()
        if not self.field_line_ids:
            raise UserError(_(
                "Add at least one filter field before designing the popup."
            ))
        if not self.wizard_action_id:
            self._rebuild_all()

        # from now on the generator leaves the layout alone
        if not self.studio_design:
            self.studio_design = True

        tag = self._studio_action_tag()
        if tag:
            return {
                'type': 'ir.actions.client',
                'tag': tag,
                'target': 'current',
                'params': {
                    'action_id': self.wizard_action_id.id,
                    'view_type': 'form',
                },
            }

        # No usable Studio client action on this build: open the popup as a
        # full page instead, so the user can enter Studio from the systray and
        # land straight on this view.
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _("Open Studio from the toolbar"),
                'message': _(
                    "This popup is now open as a full page. Click the Studio "
                    "icon in the top bar to edit its layout."
                ),
                'type': 'info',
                'sticky': False,
                'next': self._popup_as_page(),
            },
        }

    def _studio_action_tag(self):
        """Client action tag that opens the Studio view editor, if configured.

        Nothing is guessed here on purpose. Studio registers its entry point in
        javascript and the surrounding records include actions that must never
        be called from outside Studio (``leave`` raises "leave when not in
        studio???"), so a tag is only used when an administrator sets it
        explicitly.
        """
        forced = self.env['ir.config_parameter'].sudo().get_param(STUDIO_TAG_PARAM)
        return forced.strip() if forced else False

    def _popup_as_page(self):
        """The generated popup action, opened full page rather than as a dialog."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': self.dialog_title or self.name or _("Filter"),
            'res_model': 'list.filter.wizard',
            'view_mode': 'form',
            'views': [(self.wizard_view_id.id, 'form')],
            'target': 'current',
            'context': {'default_config_id': self.id},
        }

    def action_reset_design(self):
        """Drop the Studio layers and hand the popup back to the generator."""
        for rec in self:
            studio_views = rec._studio_views()
            if studio_views:
                try:
                    studio_views.sudo().unlink()
                except Exception as exc:  # pragma: no cover
                    _logger.warning(
                        "Could not remove Studio views of configuration %s: %s",
                        rec.id, exc)
                    studio_views.sudo().write({'active': False})
            rec.studio_design = False
            rec.field_line_ids._sync_wizard_fields()
            rec._rebuild_all()
        return True

import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

#: Studio is entered through the web client URL rather than through a client
#: action tag: the tags Studio registers in javascript are not part of a public
#: API and some of them ("leave") blow up when called from outside Studio.
#:
#: This is only the *tail* of the URL. The client appends it to the path the
#: user is standing on, so the configuration record stays in the breadcrumb::
#:
#:     /odoo/action-714/7
#:  -> /odoo/action-714/7/action-735/new/studio?debug=1&mode=editor&...
#:
#: and closing Studio walks back to that record instead of leaving the user on
#: the popup action alone.
STUDIO_PATH = 'action-%s/new/studio?debug=1&mode=editor&_tab=views&_view_type=form'


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
    def prepare_studio_url(self):
        """Get the popup ready for Studio and return the relative URL tail.

        Called by the *Design with Studio* button, which appends the result to
        the path it is already on so the configuration record is kept in the
        breadcrumb behind Studio.
        """
        self.ensure_one()
        if not self.field_line_ids:
            raise UserError(_(
                "Add at least one filter field before designing the popup."
            ))
        if not self.wizard_page_action_id:
            self._rebuild_all()
        if not self.wizard_page_action_id:
            raise UserError(_(
                "The popup of '%s' has no generated page action yet. "
                "Use 'Rebuild' first.", self.name or ''))

        # from now on the generator leaves the layout alone
        if not self.studio_design:
            self.studio_design = True

        return STUDIO_PATH % self.wizard_page_action_id.id

    def action_open_studio(self):
        """Fallback for callers without the javascript button (server actions,
        tests): opens Studio at the root of the web client, so the breadcrumb
        starts at the popup itself.
        """
        self.ensure_one()
        return {
            'type': 'ir.actions.act_url',
            'url': '/odoo/%s' % self.prepare_studio_url(),
            'target': 'self',
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

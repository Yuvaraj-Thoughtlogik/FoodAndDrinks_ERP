# -*- coding: utf-8 -*-
from odoo import models


class Base(models.AbstractModel):
    _inherit = 'base'

    def quick_view(self):
        """Opens the record in a modal popup form view."""
        self.ensure_one()
        return {
            'name': self.display_name or self._description or 'Record Preview',
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'new',
            'context': dict(self.env.context),
        }

    def action_quick_preview(self):
        """Alias for quick_view."""
        return self.quick_view()

    def action_quick_view(self):
        """Alias for quick_view."""
        return self.quick_view()

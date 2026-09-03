import ast

from odoo import api, fields, models
from odoo.exceptions import UserError


class ListFilterWizard(models.TransientModel):
    """The filter popup.

    The model itself only carries ``config_id``; every visible input is a real
    manual field generated from the configuration (``x_flt_<line id>``), which
    is why the dialog looks and behaves like an ordinary Odoo form: native
    dropdowns, tag inputs and date pickers, with no javascript.
    """

    _name = 'list.filter.wizard'
    _description = 'List Dynamic Filter'

    config_id = fields.Many2one(
        'list.filter.configuration',
        string="Configuration",
        required=True,
        ondelete='cascade',
    )

    # ------------------------------------------------------------------
    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        config_id = values.get('config_id') or self.env.context.get('default_config_id')
        if config_id:
            values.update(self._date_defaults(config_id))
        return values

    @api.model
    def _date_defaults(self, config_id):
        """Date inputs open on today, like a day-of filter would."""
        config = self.env['list.filter.configuration'].browse(config_id).exists()
        if not config:
            return {}
        today = fields.Date.context_today(self)
        defaults = {}
        for line in config.field_line_ids:
            if line.field_family != 'date':
                continue
            for field in (line.wizard_field_id, line.wizard_field_to_id):
                if field and field.name in self._fields:
                    defaults[field.name] = today
        return defaults

    # ------------------------------------------------------------------
    def _build_domain(self):
        self.ensure_one()
        domain = []
        for line in self.config_id.field_line_ids.sorted(lambda l: (l.sequence, l.id)):
            leaves = line._build_leaf(self)
            if not leaves:
                continue
            domain = (['&'] + domain + list(leaves)) if domain else list(leaves)

        extra = self.config_id.extra_domain
        if extra:
            try:
                extra = ast.literal_eval(extra)
            except Exception:
                extra = []
            if extra:
                domain = (['&'] + domain + list(extra)) if domain else list(extra)
        return domain

    # ------------------------------------------------------------------
    def action_apply(self):
        self.ensure_one()
        config = self.config_id
        if not config:
            raise UserError("This filter is not linked to a configuration.")

        view = config.view_id or config._target_view()
        return {
            'type': 'ir.actions.act_window',
            'name': config.name or 'Filtered Records',
            'res_model': config.model_id.model,
            'view_mode': 'list,form',
            'views': [(view.id, 'list'), (False, 'form')],
            'domain': self._build_domain(),
            'target': config.result_target,
            'context': dict(self.env.context, tl_list_filter_config_id=config.id),
        }

    def action_clear(self):
        """Reset every input to its default and keep the dialog open."""
        self.ensure_one()
        values = {}
        for line in self.config_id.field_line_ids:
            for field in (line.wizard_field_id, line.wizard_field_to_id):
                if not field or field.name not in self._fields:
                    continue
                odoo_field = self._fields[field.name]
                if odoo_field.type == 'many2many':
                    values[field.name] = [(5, 0, 0)]
                elif odoo_field.type in ('integer', 'float', 'monetary'):
                    values[field.name] = 0
                else:
                    values[field.name] = False
        # dates go back to today rather than empty
        values.update(self._date_defaults(self.config_id.id))
        if values:
            self.write(values)
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'view_id': self.config_id.wizard_view_id.id,
            'target': 'new',
            'context': dict(self.env.context, default_config_id=self.config_id.id),
        }

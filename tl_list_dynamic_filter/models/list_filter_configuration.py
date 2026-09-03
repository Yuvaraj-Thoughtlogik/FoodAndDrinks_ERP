import ast
from markupsafe import escape

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError

SKIP = 'tl_list_filter_skip_view_sync'
WIZARD_MODEL = 'list.filter.wizard'


class ListFilterConfiguration(models.Model):
    _name = 'list.filter.configuration'
    _description = 'List Dynamic Filter Configuration'
    _order = 'model_id, name'

    name = fields.Char(string="Button Name", required=True)
    active = fields.Boolean(default=True)

    model_id = fields.Many2one(
        'ir.model',
        string="Model",
        required=True,
        domain="[('transient', '=', False)]",
        ondelete='cascade',
    )
    model_name = fields.Char(related='model_id.model', string="Model Name")

    view_id = fields.Many2one(
        'ir.ui.view',
        string="List View",
        domain="[('model', '=', model_name), ('type', '=', 'list'),"
               " ('mode', '=', 'primary')]",
        help="List view the button is added to. Leave empty to use the "
             "default list view of the model.",
    )

    field_line_ids = fields.One2many(
        'list.filter.config.field',
        'config_id',
        string="Filter Fields",
        copy=True,
    )
    field_count = fields.Integer(compute='_compute_field_count')

    # --- popup presentation ----------------------------------------------
    dialog_title = fields.Char(
        string="Popup Title",
        help="Title of the filter dialog. Defaults to the button name.",
    )
    apply_label = fields.Char(string="Apply Button", default="Apply")

    # --- button ----------------------------------------------------------
    button_class = fields.Selection(
        [
            ('btn-primary', 'Primary'),
            ('btn-secondary', 'Secondary'),
            ('btn-light', 'Light'),
        ],
        default='btn-primary',
        required=True,
        string="Button Style",
    )
    extra_domain = fields.Char(
        string="Extra Domain",
        default='[]',
        help="Domain always ANDed with what the user enters in the popup.",
    )
    result_target = fields.Selection(
        [('current', 'Same window'), ('new', 'New window')],
        default='current',
        required=True,
        string="Open Results In",
    )

    # --- generated records ------------------------------------------------
    created_view_id = fields.Many2one(
        'ir.ui.view', string="Generated List View",
        readonly=True, ondelete='set null', copy=False)
    wizard_view_id = fields.Many2one(
        'ir.ui.view', string="Generated Popup View",
        readonly=True, ondelete='set null', copy=False)
    wizard_action_id = fields.Many2one(
        'ir.actions.act_window', string="Generated Action",
        readonly=True, ondelete='set null', copy=False)

    # ------------------------------------------------------------------
    @api.depends('field_line_ids')
    def _compute_field_count(self):
        for rec in self:
            rec.field_count = len(rec.field_line_ids)

    @api.constrains('extra_domain')
    def _check_extra_domain(self):
        for rec in self:
            if not rec.extra_domain:
                continue
            try:
                parsed = ast.literal_eval(rec.extra_domain)
                assert isinstance(parsed, (list, tuple))
            except Exception:
                raise ValidationError(
                    "The extra domain must be a valid python list, e.g. "
                    "[('state', '!=', 'cancel')]"
                )

    @api.onchange('model_id')
    def _onchange_model_id(self):
        self.view_id = False
        self.field_line_ids = [(5, 0, 0)]

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._rebuild_all()
        return records

    def write(self, vals):
        res = super().write(vals)
        if self.env.context.get(SKIP):
            return res
        watched = {
            'name', 'model_id', 'view_id', 'button_class', 'active',
            'dialog_title', 'apply_label', 'result_target',
        }
        if watched & set(vals):
            self._rebuild_all()
        return res

    def unlink(self):
        generated_fields = (
            self.mapped('field_line_ids.wizard_field_id')
            | self.mapped('field_line_ids.wizard_field_to_id')
        )
        (self.mapped('created_view_id')
         | self.mapped('wizard_view_id')).sudo().unlink()
        self.mapped('wizard_action_id').sudo().unlink()
        res = super().unlink()
        generated_fields.sudo().unlink()
        return res

    def copy_data(self, default=None):
        vals_list = super().copy_data(default=default)
        for vals in vals_list:
            vals.update(created_view_id=False, wizard_view_id=False,
                        wizard_action_id=False)
        return vals_list

    def _rebuild_all(self):
        self._build_wizard_view()
        self._create_or_update_view()

    # ==================================================================
    # 1. the popup: a generated form view + its own action
    # ==================================================================
    def _wizard_arch(self):
        """Build the form arch of the filter popup: one label + input per row."""
        self.ensure_one()
        lines = self.field_line_ids.filtered('wizard_field_id').sorted(
            lambda l: (l.sequence, l.id))
        body = ('<group name="filter_fields">%s</group>'
                % ''.join(l._arch_row() for l in lines))

        # The sheet/group skeleton is what Studio expects to drop widgets into,
        # so the popup is a regular editable form rather than a bare dialog.
        return """
<form string="{title}">
    <sheet>
        <field name="config_id" invisible="1"/>
        {body}
    </sheet>
    <footer>
        <button name="action_apply" type="object" string="{apply}"
                class="btn-primary" data-hotkey="q"/>
        <button name="action_clear" type="object" string="Clear"
                class="btn-secondary"/>
        <button string="Cancel" class="btn-secondary" special="cancel"
                data-hotkey="x"/>
    </footer>
</form>
        """.format(
            title=escape(self.dialog_title or self.name or 'Filter'),
            body=body,
            apply=escape(self.apply_label or 'Apply'),
        )

    def _keep_custom_arch(self):
        """Hook: return True to leave an already generated popup arch alone.

        The Studio bridge module overrides this so a popup laid out by hand in
        Studio is not overwritten the next time the configuration is saved.
        """
        self.ensure_one()
        return False

    def _blank_wizard_views(self):
        """Strip the generated popup arch.

        Odoo refuses to drop a field that a view still references, so the arch
        is emptied before the generated wizard fields are rebuilt.
        """
        views = self.mapped('wizard_view_id')
        if views:
            views.sudo().write({
                'arch': '<form><sheet>'
                        '<field name="config_id" invisible="1"/>'
                        '<group name="filter_fields"/>'
                        '</sheet></form>',
            })

    def _build_wizard_view(self):
        View = self.env['ir.ui.view'].sudo()
        Action = self.env['ir.actions.act_window'].sudo()
        for rec in self:
            values = {
                'name': 'list.filter.wizard.form.%s' % rec.id,
                'type': 'form',
                'model': WIZARD_MODEL,
                'mode': 'primary',
                'inherit_id': False,
                'priority': 99,
                'arch': rec._wizard_arch(),
            }
            if rec.wizard_view_id:
                if rec._keep_custom_arch():
                    values.pop('arch', None)
                rec.wizard_view_id.write(values)
                view = rec.wizard_view_id
            else:
                view = View.create(values)

            action_values = {
                'name': rec.dialog_title or rec.name or 'Filter',
                'res_model': WIZARD_MODEL,
                'view_mode': 'form',
                'target': 'new',
                'view_id': view.id,
                'context': "{'default_config_id': %s}" % rec.id,
            }
            if rec.wizard_action_id:
                rec.wizard_action_id.write(action_values)
                action = rec.wizard_action_id
            else:
                action = Action.create(action_values)

            rec.with_context(**{SKIP: True}).write({
                'wizard_view_id': view.id,
                'wizard_action_id': action.id,
            })

    # ==================================================================
    # 2. the button on the list view
    # ==================================================================
    def _target_view(self):
        self.ensure_one()
        if self.view_id:
            return self.view_id
        view = self.env['ir.ui.view'].search([
            ('model', '=', self.model_id.model),
            ('type', '=', 'list'),
            ('mode', '=', 'primary'),
        ], order='priority, id', limit=1)
        if not view:
            raise UserError(
                "No list view found for model '%s'. Please select one manually."
                % self.model_id.model
            )
        return view

    def _has_header(self, target_view):
        """Does the combined arch already carry a <header> inside <list>?

        Our own generated view is temporarily disabled so we never detect the
        header we created ourselves.
        """
        self.ensure_one()
        own = self.created_view_id
        was_active = own.active if own else None
        try:
            if own and was_active:
                own.sudo().write({'active': False})
            arch = self.env[self.model_id.model].sudo().get_view(
                view_id=target_view.id, view_type='list')['arch']
        except Exception:
            return False
        finally:
            if own and was_active:
                own.sudo().write({'active': True})
        return '<header' in arch

    def _button_arch(self, action_id, inside_header):
        self.ensure_one()
        button = (
            '<button string="{label}" type="action" name="{action}" '
            'display="always" class="btn {klass}"/>'
        ).format(
            label=escape(self.name or 'Filter'),
            action=action_id,
            klass=self.button_class,
        )
        if inside_header:
            return '<xpath expr="//list/header" position="inside">%s</xpath>' % button
        return ('<xpath expr="//list" position="inside">'
                '<header>%s</header></xpath>' % button)

    def _create_or_update_view(self):
        View = self.env['ir.ui.view'].sudo()
        for rec in self:
            if not rec.active:
                if rec.created_view_id:
                    rec.created_view_id.sudo().write({'active': False})
                continue
            if not rec.wizard_action_id:
                continue

            target = rec._target_view()
            values = {
                'name': '%s.dynamic.filter.%s' % (rec.model_id.model, rec.id),
                'type': 'list',
                'model': rec.model_id.model,
                'mode': 'extension',
                'inherit_id': target.id,
                'arch': rec._button_arch(
                    rec.wizard_action_id.id, rec._has_header(target)),
                'active': True,
            }
            if rec.created_view_id:
                rec.created_view_id.write(values)
            else:
                view = View.create(values)
                rec.with_context(**{SKIP: True}).write({'created_view_id': view.id})

    # ------------------------------------------------------------------
    # actions
    # ------------------------------------------------------------------
    def action_rebuild(self):
        self.mapped('field_line_ids')._sync_wizard_fields()
        self._rebuild_all()
        return True

    def action_open_filter(self):
        self.ensure_one()
        if not self.wizard_action_id:
            self._rebuild_all()
        action = self.wizard_action_id.sudo().read()[0]
        action['context'] = {'default_config_id': self.id}
        return action

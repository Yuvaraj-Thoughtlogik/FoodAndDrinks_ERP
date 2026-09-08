"""One field/value configuration line of a demo record template."""

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from . import demo_field_utils as futils
from .demo_value_mixin import SKIP


class DemoRecordCreatorLine(models.Model):
    _name = 'tl.demo.record.creator.line'
    _inherit = ['tl.demo.value.mixin']
    _description = 'Demo Record Field Configuration'
    _order = 'sequence, id'

    creator_id = fields.Many2one(
        'tl.demo.record.creator',
        string="Template",
        required=True,
        ondelete='cascade',
        index=True,
    )
    model_id = fields.Many2one(
        related='creator_id.model_id', string="Model", readonly=True)

    child_line_ids = fields.One2many(
        'tl.demo.record.creator.child.line', 'line_id',
        string="Child Records Configuration")

    allowed_child_field_ids = fields.Many2many(
        'ir.model.fields', compute='_compute_allowed_child_field_ids',
        string="Selectable Child Fields",
        help="Selectable fields of the child model for One2many configuration.")

    def _creator(self):
        self.ensure_one()
        return self.creator_id

    # ------------------------------------------------------------------
    # Computes
    # ------------------------------------------------------------------
    @api.depends('ttype', 'relation', 'field_id')
    def _compute_allowed_child_field_ids(self):
        for line in self:
            if line.ttype == 'one2many' and line.relation:
                inverse = line._child_inverse_name()
                ids = futils.selectable_field_ids(
                    self.env, line.relation,
                    excluded=(inverse,) if inverse else (),
                    skip_types=('one2many',))
                line.allowed_child_field_ids = [(6, 0, ids)]
            else:
                line.allowed_child_field_ids = [(6, 0, [])]

    # ------------------------------------------------------------------
    # Onchange
    # ------------------------------------------------------------------
    @api.onchange('field_id')
    def _onchange_field_id_reset_value(self):
        """Clear child configuration that cannot belong to the new field.

        Nothing is loaded in its place, not even the child model's required
        fields: use the Load buttons inside the line to pull in the child
        fields you actually want to set.
        """
        super()._onchange_field_id_reset_value()
        for line in self:
            if not line.field_id:
                continue
            # child lines were configured against the previous field's
            # comodel, so they can never survive the change
            line.child_line_ids = [(5, 0, 0)]
            if line.field_id.ttype == 'one2many' and line.value_count <= 0:
                line.value_count = 1

    # ------------------------------------------------------------------
    # Actions for Child Lines
    # ------------------------------------------------------------------
    def action_load_required_child_fields(self):
        self.ensure_one()
        self.child_line_ids = [(5, 0, 0)] + self._child_line_vals(required_only=True)

    def action_load_all_child_fields(self):
        self.ensure_one()
        self.child_line_ids = [(5, 0, 0)] + self._child_line_vals(required_only=False)

    def action_clear_child_fields(self):
        self.ensure_one()
        self.child_line_ids = [(5, 0, 0)]

    # ------------------------------------------------------------------
    # One2many helpers
    # ------------------------------------------------------------------
    def _child_model(self):
        self.ensure_one()
        if not self.relation:
            return None
        return self.env.get(self.relation)

    def _child_inverse_name(self):
        """The child field pointing back at the parent - Odoo sets it itself."""
        self.ensure_one()
        if self.ttype != 'one2many':
            return False
        model = self.env.get(self.field_id.model)
        field = model._fields.get(self.field_id.name) if model else None
        return getattr(field, 'inverse_name', False) if field else False

    def _child_line_vals(self, required_only=True):
        """``[(0, 0, vals)]`` commands for this One2many's child fields."""
        self.ensure_one()
        child_model = self._child_model()
        if child_model is None:
            return []
        inverse = self._child_inverse_name()
        candidates = (futils.required_fields(child_model) if required_only
                      else futils.configurable_fields(child_model))
        IrModelFields = self.env['ir.model.fields']
        commands = []
        for index, field in enumerate(candidates):
            if inverse and field.name == inverse:
                continue
            field_rec = IrModelFields._get(self.relation, field.name)
            if not field_rec:
                continue
            commands.append((0, 0, {
                'sequence': (index + 1) * 10,
                'field_id': field_rec.id,
                'use_random': field.type in futils.RANDOMISABLE_TTYPES,
                'value_count': 1,
            }))
        return commands

    # ------------------------------------------------------------------
    # validation
    # ------------------------------------------------------------------
    def _validate_one2many(self):
        """Structural checks on the child configuration only.

        Which child fields the child model insists on is the child model's
        business, answered when the run writes the records.
        """
        self.ensure_one()
        label = self._label()
        child_model = self._child_model()
        if child_model is None:
            raise UserError(
                _("The child model of '%s' could not be resolved.", label))
        if self.value_count < 0:
            raise UserError(
                _("Number of Values on '%s' cannot be negative.", label))
        if not self.value_count:
            return

        children = self.child_line_ids
        for child in children:
            if child.field_id.model != self.relation:
                raise UserError(
                    _("'%(child)s' belongs to %(other)s, not to %(model)s, so "
                      "it cannot be configured under '%(label)s'.",
                      child=child._label(), other=child.field_id.model,
                      model=self.relation, label=label))

        children._validate_for_creation()

    # ------------------------------------------------------------------
    # value resolution
    # ------------------------------------------------------------------
    def _resolve_one2many(self, field):
        """One ``(0, 0, vals)`` command per child record to create.

        A child record that ends up with no values at all is dropped rather
        than sent as ``(0, 0, {})``: a permissive child model would create it
        silently, and nobody asked for a blank record. Values are resolved
        per child record, so one iteration can come up empty while its
        neighbours do not - a random Reference picks a different model each
        time, and that model can turn out to have no readable records. If
        every iteration comes up empty, or no child field is configured at
        all, the One2many is left out of the values entirely.
        """
        self.ensure_one()
        children = self.child_line_ids
        count = self.value_count
        if count <= 0 or not children:
            return SKIP
        commands = []
        for _index in range(count):
            child_vals = {}
            for child in children:
                value = child._resolve_value()
                if value is SKIP:
                    continue
                child_vals[child.field_name] = value
            if child_vals:
                commands.append((0, 0, child_vals))
        return commands or SKIP

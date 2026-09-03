"""The value half of a configuration line.

One real, typed column per input shape, so every field type is edited with its
own native Odoo widget instead of a single stringly-typed box. The view shows
exactly one of them per row, driven by :attr:`value_widget`.
"""

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from . import demo_field_utils as futils
from . import demo_random as rnd

# Returned by _resolve_value() to mean "write nothing, let Odoo decide".
SKIP = object()


class DemoValueMixin(models.AbstractModel):
    _name = 'tl.demo.value.mixin'
    _description = 'Demo Record Value Configuration'
    _order = 'sequence, id'

    sequence = fields.Integer(default=10)

    field_id = fields.Many2one(
        'ir.model.fields',
        string="Field",
        required=True,
        ondelete='cascade',
        help="The field to populate. Only writable, non-computed fields of a "
             "supported type are offered.",
    )
    field_name = fields.Char(related='field_id.name', string="Technical Name")
    ttype = fields.Selection(related='field_id.ttype', string="Type")
    relation = fields.Char(related='field_id.relation', string="Related Model")
    field_required = fields.Boolean(related='field_id.required', string="Required")
    field_help = fields.Text(related='field_id.help', string="Field Help")

    comodel_id = fields.Many2one(
        'ir.model', string="Target Model",
        compute='_compute_comodel_id',
        help="Model the related records are taken from.")
    comodel_hint = fields.Char(compute='_compute_comodel_id')

    value_widget = fields.Selection(
        selection=[
            ('char', 'Text'),
            ('text', 'Multiline Text'),
            ('integer', 'Integer'),
            ('float', 'Decimal'),
            ('boolean', 'Checkbox'),
            ('date', 'Date'),
            ('datetime', 'Date & Time'),
            ('selection', 'Selection'),
            ('reference', 'Record'),
            ('many2many', 'Records'),
            ('one2many', 'Child Records'),
            ('binary', 'File'),
            ('unsupported', 'Unsupported'),
        ],
        compute='_compute_value_widget',
        string="Input",
        help="Which input is shown for the selected field.")

    use_random = fields.Boolean(
        string="Random",
        default=True,
        help="Generate a fresh value for every record instead of repeating one "
             "value.\n\n"
             "Untick Random to enter a specific fixed value.")
    can_use_random = fields.Boolean(compute='_compute_value_widget')

    # --- one typed column per input shape --------------------------------
    value_char = fields.Char(string="Text Value", trim=False)
    value_text = fields.Text(string="Long Text Value")
    value_integer = fields.Integer(string="Integer Value")
    value_float = fields.Float(string="Decimal Value")
    value_boolean = fields.Boolean(string="Checked")
    value_date = fields.Date(string="Date Value")
    value_datetime = fields.Datetime(string="Date & Time Value")

    value_selection_id = fields.Many2one(
        'ir.model.fields.selection', string="Option",
        ondelete='cascade',
        help="One of the selected field's own options.")
    value_selection_free = fields.Char(
        string="Option Value",
        help="Technical value of the option, for Selection fields whose "
             "options are computed at runtime.")
    selection_is_dynamic = fields.Boolean(compute='_compute_selection_hint')
    selection_hint = fields.Char(compute='_compute_selection_hint')

    value_reference = fields.Reference(
        selection='_selection_reference_models',
        string="Record",
        help="Pick the model, then search the record.")

    value_binary = fields.Binary(string="File", attachment=False)
    value_binary_filename = fields.Char(string="File Name")

    value_count = fields.Integer(
        string="Number of Values",
        default=1,
        help="Many2many: how many records to link when the value is left to "
             "random. One2many: how many child records to create for each "
             "parent record.")

    value_display = fields.Char(compute='_compute_value_display', string="Value")

    # ------------------------------------------------------------------
    # selections
    # ------------------------------------------------------------------
    @api.model
    def _selection_reference_models(self):
        models_ = self.env['ir.model'].sudo().search(
            [('transient', '=', False)], order='name')
        return [(m.model, m.name) for m in models_]

    # ------------------------------------------------------------------
    # computes
    # ------------------------------------------------------------------
    @api.depends('ttype')
    def _compute_value_widget(self):
        for line in self:
            widget = futils.WIDGET_BY_TTYPE.get(line.ttype, 'unsupported')
            line.value_widget = widget if line.ttype else 'unsupported'
            line.can_use_random = line.ttype in futils.RANDOMISABLE_TTYPES

    @api.depends('relation')
    def _compute_comodel_id(self):
        IrModel = self.env['ir.model']
        for line in self:
            model = IrModel.sudo().search(
                [('model', '=', line.relation)], limit=1) if line.relation else IrModel
            line.comodel_id = model.id if model else False
            line.comodel_hint = (
                _("Records are taken from %(name)s (%(model)s)",
                  name=model.name, model=model.model)
                if model else False
            )

    @api.depends('field_id')
    def _compute_selection_hint(self):
        for line in self:
            if line.ttype != 'selection' or not line.field_id:
                line.selection_is_dynamic = False
                line.selection_hint = False
                continue
            stored = bool(line.field_id.selection_ids)
            line.selection_is_dynamic = not stored
            if stored:
                line.selection_hint = False
            else:
                options = line._selection_options()
                line.selection_hint = (
                    _("Available values: %s", ', '.join(v for v, _lbl in options))
                    if options else
                    _("This field's options are computed at runtime and could "
                      "not be read. Enter the technical value manually.")
                )

    @api.depends('value_widget', 'use_random', 'can_use_random', 'value_char', 'value_text',
                 'value_integer', 'value_float', 'value_boolean', 'value_date',
                 'value_datetime', 'value_selection_id', 'value_selection_free',
                 'value_reference', 'value_binary_filename', 'value_count')
    def _compute_value_display(self):
        for line in self:
            line.value_display = line._value_display_string()

    def _value_display_string(self):
        self.ensure_one()
        widget = self.value_widget
        if widget == 'unsupported':
            return _("Unsupported field type")
        if widget == 'one2many':
            return _("%s child record(s) per parent", max(self.value_count, 0))
        if self._will_randomise():
            if widget == 'many2many':
                return _("Random (%s record(s))", max(self.value_count, 1))
            return _("Random")
        if widget == 'char':
            return self.value_char or _("(empty)")
        if widget == 'text':
            text = (self.value_text or '').strip().replace('\n', ' ')
            return (text[:60] + '...') if len(text) > 60 else (text or _("(empty)"))
        if widget == 'integer':
            return str(self.value_integer)
        if widget == 'float':
            return '%g' % self.value_float
        if widget == 'boolean':
            return _("Yes") if self.value_boolean else _("No")
        if widget == 'date':
            return fields.Date.to_string(self.value_date) if self.value_date else _("(empty)")
        if widget == 'datetime':
            return fields.Datetime.to_string(self.value_datetime) if self.value_datetime else _("(empty)")
        if widget == 'selection':
            if self.value_selection_id:
                return '%s (%s)' % (self.value_selection_id.name,
                                    self.value_selection_id.value)
            return self.value_selection_free or _("(empty)")
        if widget == 'reference':
            record = self.value_reference
            return record.display_name if record else _("(empty)")
        if widget == 'many2many':
            names = [ref.record_ref.display_name
                     for ref in self._explicit_ref_records()
                     if ref.record_ref]
            return ', '.join(names) if names else _("(empty)")
        if widget == 'binary':
            return self.value_binary_filename or (
                _("File attached") if self.value_binary else _("(empty)"))
        return _("(empty)")

    # ------------------------------------------------------------------
    # onchange
    # ------------------------------------------------------------------
    @api.onchange('field_id')
    def _onchange_field_id_reset_value(self):
        """Clear values that make no sense for the newly selected field."""
        for line in self:
            if not line.field_id:
                continue
            widget = futils.WIDGET_BY_TTYPE.get(line.field_id.ttype, 'unsupported')
            keep = {
                'char': 'value_char',
                'text': 'value_text',
                'integer': 'value_integer',
                'float': 'value_float',
                'boolean': 'value_boolean',
                'date': 'value_date',
                'datetime': 'value_datetime',
            }.get(widget)
            for fname in ('value_char', 'value_text', 'value_integer',
                          'value_float', 'value_boolean', 'value_date',
                          'value_datetime'):
                if fname != keep:
                    line[fname] = False
            # relational and selection values can never survive a field change
            line.value_selection_id = False
            line.value_selection_free = False
            line.value_reference = False
            line.value_binary = False
            line.value_binary_filename = False
            if line.field_id.ttype not in futils.RANDOMISABLE_TTYPES:
                line.use_random = False
            if line.field_id.ttype in ('many2many', 'one2many') and line.value_count <= 0:
                line.value_count = 1

    @api.onchange('value_binary')
    def _onchange_value_binary(self):
        for line in self:
            if line.value_binary and not line.value_binary_filename:
                line.value_binary_filename = '%s.bin' % (line.field_name or 'upload')

    def _creator(self):
        """Hook: the demo record creator template that owns this configuration line."""
        self.ensure_one()
        if hasattr(self, 'creator_id') and self.creator_id:
            return self.creator_id
        if hasattr(self, 'line_id') and self.line_id and self.line_id.creator_id:
            return self.line_id.creator_id
        return self.env['tl.demo.record.creator']

    def _explicit_ref_records(self):
        """Records explicitly chosen for this Many2many field."""
        self.ensure_one()
        creator = self._creator()
        if not creator or not self.field_id:
            return self.env['tl.demo.record.creator.ref']
        return creator.ref_ids.filtered(
            lambda ref: ref.field_id.id == self.field_id.id)

    # ------------------------------------------------------------------
    # constraints
    # ------------------------------------------------------------------
    @api.constrains('value_count', 'ttype')
    def _check_value_count(self):
        for line in self:
            if line.ttype in ('one2many', 'many2many') and line.value_count < 0:
                raise ValidationError(
                    _("Number of Values on '%s' must be zero or more.",
                      line.field_id.field_description or line.field_name))
            if line.ttype == 'one2many' and line.value_count > 200:
                raise ValidationError(
                    _("Number of Values on '%s' is capped at 200 child records "
                      "per parent record.",
                      line.field_id.field_description or line.field_name))

    @api.constrains('field_id')
    def _check_field_is_configurable(self):
        for line in self:
            if not line.field_id:
                continue
            model = self.env.get(line.field_id.model)
            if model is None:
                raise ValidationError(
                    _("Model '%s' does not exist in this database.",
                      line.field_id.model))
            field = model._fields.get(line.field_id.name)
            if field is None:
                raise ValidationError(
                    _("Field '%(field)s' does not exist on %(model)s.",
                      field=line.field_id.name, model=line.field_id.model))
            reason = futils.unsupported_reason(field)
            if reason:
                raise ValidationError(
                    _("'%(label)s' cannot be used because %(reason)s.",
                      label=line.field_id.field_description or field.name,
                      reason=reason))

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------
    def _target_model(self):
        """The model recordset the configured field belongs to."""
        self.ensure_one()
        model = self.env.get(self.field_id.model)
        if model is None:
            raise UserError(_("Model '%s' does not exist in this database.",
                              self.field_id.model))
        return model

    def _odoo_field(self):
        self.ensure_one()
        model = self._target_model()
        field = model._fields.get(self.field_id.name)
        if field is None:
            raise UserError(
                _("Field '%(field)s' does not exist on %(model)s.",
                  field=self.field_id.name, model=self.field_id.model))
        return field

    def _label(self):
        self.ensure_one()
        return self.field_id.field_description or self.field_id.name or ''

    def _selection_options(self):
        self.ensure_one()
        if self.field_id.selection_ids:
            return [(s.value, s.name)
                    for s in self.field_id.selection_ids.sorted('sequence')]
        return futils.selection_options(self._target_model(), self.field_id.name)

    def _reference_models(self):
        """Models a Reference field is allowed to point at."""
        self.ensure_one()
        field = self._odoo_field()
        selection = getattr(field, 'selection', None)
        model = self._target_model()
        try:
            if callable(selection):
                selection = selection(model)
            elif isinstance(selection, str):
                selection = getattr(model, selection)()
        except Exception:
            selection = None
        return [value for value, _label in (selection or [])]

    def _blank(self):
        """Is the explicitly configured value empty for this widget?"""
        self.ensure_one()
        widget = self.value_widget
        if widget == 'char':
            return not self.value_char
        if widget == 'text':
            return not self.value_text
        if widget == 'selection':
            return not (self.value_selection_id or self.value_selection_free)
        if widget == 'reference':
            return not self.value_reference
        if widget == 'many2many':
            return not self._explicit_ref_records()
        if widget == 'binary':
            return not self.value_binary
        if widget in ('date', 'datetime'):
            return not (self.value_date if widget == 'date' else self.value_datetime)
        # integer, float and boolean: 0 / False are legitimate values
        return False

    def _will_randomise(self):
        """Is this line configured to generate random values?"""
        self.ensure_one()
        if self.value_widget in ('one2many', 'unsupported'):
            return False
        return bool(self.use_random and self.can_use_random)

    # ------------------------------------------------------------------
    # validation
    # ------------------------------------------------------------------
    def _validate_for_creation(self):
        """Raise a readable error for anything that cannot produce a value."""
        for line in self:
            line._check_field_is_configurable()
            widget = line.value_widget
            label = line._label()

            if widget == 'unsupported':
                raise UserError(
                    _("'%(label)s' has the unsupported type '%(ttype)s'. "
                      "Remove the line to continue.",
                      label=label, ttype=line.ttype or '?'))

            if line.field_required and not line._will_randomise() and line._blank():
                raise UserError(
                    _("'%s' is required on the target model. Enter a value "
                      "or tick Random.", label))

            if widget == 'selection':
                line._validate_selection()
            elif widget == 'reference':
                line._validate_reference()
            elif widget == 'many2many':
                line._validate_many2many()
            elif widget == 'one2many':
                line._validate_one2many()

    def _validate_selection(self):
        self.ensure_one()
        options = self._selection_options()
        label = self._label()
        if self._will_randomise():
            if not options and self.field_required:
                raise UserError(
                    _("The options of '%s' could not be read, so no random "
                      "value can be generated. Enter the technical value "
                      "manually.", label))
            return
        value = (self.value_selection_id.value
                 or (self.value_selection_free or '').strip())
        if not value:
            return
        allowed = [option for option, _lbl in options]
        if allowed and value not in allowed:
            raise UserError(
                _("'%(value)s' is not a valid option for '%(label)s'.\n"
                  "Available options: %(options)s",
                  value=value, label=label, options=', '.join(allowed)))

    def _validate_reference(self):
        self.ensure_one()
        label = self._label()
        if self.ttype == 'many2one':
            comodel_name = self.relation
            if not comodel_name or self.env.get(comodel_name) is None:
                raise UserError(
                    _("The related model of '%s' could not be resolved.", label))
            if self._will_randomise():
                if not rnd.random_record_ids(self.env, comodel_name, 1):
                    raise UserError(
                        _("'%(label)s' points at %(model)s, which has no "
                          "records you can read, so no random record can be "
                          "picked. Create one first, or configure the value "
                          "explicitly.", label=label, model=comodel_name))
                return
            record = self.value_reference
            if not record:
                return
            if record._name != comodel_name:
                raise UserError(
                    _("'%(label)s' only accepts %(expected)s records, but "
                      "%(got)s was selected.",
                      label=label, expected=comodel_name, got=record._name))
            if not record.exists():
                raise UserError(
                    _("The record selected for '%s' no longer exists.", label))
            return

        # true Reference field
        allowed = self._reference_models()
        if self._will_randomise():
            if not rnd.random_reference_model(self.env, allowed):
                raise UserError(
                    _("No readable record could be found for the reference "
                      "field '%s'. Configure the value explicitly.", label))
            return
        record = self.value_reference
        if not record:
            return
        if allowed and record._name not in allowed:
            raise UserError(
                _("'%(label)s' does not accept %(got)s records.\n"
                  "Allowed models: %(allowed)s",
                  label=label, got=record._name, allowed=', '.join(allowed)))
        if not record.exists():
            raise UserError(
                _("The record selected for '%s' no longer exists.", label))

    def _validate_many2many(self):
        self.ensure_one()
        label = self._label()
        comodel_name = self.relation
        if not comodel_name or self.env.get(comodel_name) is None:
            raise UserError(
                _("The related model of '%s' could not be resolved.", label))
        if self._will_randomise():
            wanted = max(self.value_count, 1)
            available = self.env[comodel_name].search_count([])
            if not available:
                raise UserError(
                    _("'%(label)s' points at %(model)s, which has no records "
                      "you can read, so no random records can be linked.",
                      label=label, model=comodel_name))
            if wanted > available:
                raise UserError(
                    _("'%(label)s' asks for %(wanted)s random %(model)s "
                      "record(s) but only %(available)s exist. Lower Number of "
                      "Values.", label=label, wanted=wanted,
                      model=comodel_name, available=available))
            return
        for ref in self._explicit_ref_records():
            record = ref.record_ref
            if not record:
                raise UserError(
                    _("One of the records configured for '%s' is empty.", label))
            if record._name != comodel_name:
                raise UserError(
                    _("'%(label)s' only accepts %(expected)s records, but "
                      "%(got)s was selected.",
                      label=label, expected=comodel_name, got=record._name))
            if not record.exists():
                raise UserError(
                    _("A record configured for '%s' no longer exists.", label))

    def _validate_one2many(self):
        """Overridden by the parent-level line, which owns the child config."""
        return

    # ------------------------------------------------------------------
    # value resolution
    # ------------------------------------------------------------------
    def _resolve_value(self):
        """The value to write for this line, or :data:`SKIP`.

        Called once per generated record, so random values differ between
        records of the same batch.
        """
        self.ensure_one()
        widget = self.value_widget
        field = self._odoo_field()

        if widget == 'one2many':
            return self._resolve_one2many(field)

        if self._will_randomise():
            return self._random_value(widget, field)

        if self._blank():
            return SKIP

        return self._explicit_value(widget, field)

    def _explicit_value(self, widget, field):
        self.ensure_one()
        if widget == 'char':
            return self.value_char
        if widget == 'text':
            return self.value_text
        if widget == 'integer':
            return self.value_integer
        if widget == 'float':
            return self.value_float
        if widget == 'boolean':
            return self.value_boolean
        if widget == 'date':
            return self.value_date
        if widget == 'datetime':
            return self.value_datetime
        if widget == 'selection':
            return (self.value_selection_id.value
                    or (self.value_selection_free or '').strip())
        if widget == 'reference':
            record = self.value_reference
            if self.ttype == 'many2one':
                return record.id
            return '%s,%s' % (record._name, record.id)
        if widget == 'many2many':
            # a Reference field is not relational to the ORM, so mapped() would
            # hand back a list of recordsets rather than one recordset
            return [(6, 0, [ref.record_ref.id
                            for ref in self._explicit_ref_records()
                            if ref.record_ref])]
        if widget == 'binary':
            return self.value_binary
        return SKIP

    def _random_value(self, widget, field):
        self.ensure_one()
        if widget == 'char':
            return rnd.random_char(field)
        if widget == 'text':
            return (rnd.random_html(field) if self.ttype == 'html'
                    else rnd.random_text(field))
        if widget == 'integer':
            return rnd.random_integer(field)
        if widget == 'float':
            return rnd.random_float(field)
        if widget == 'boolean':
            return rnd.random_boolean(field)
        if widget == 'date':
            return rnd.random_date(field)
        if widget == 'datetime':
            return rnd.random_datetime(field)
        if widget == 'selection':
            value = rnd.random_selection(self._target_model(), self.field_id.name)
            return value if value is not None else SKIP
        if widget == 'binary':
            return rnd.random_binary(field)
        if widget == 'reference':
            return self._random_relational_value()
        if widget == 'many2many':
            ids = rnd.random_record_ids(
                self.env, self.relation, max(self.value_count, 1))
            return [(6, 0, ids)] if ids else SKIP
        return SKIP

    def _random_relational_value(self):
        self.ensure_one()
        if self.ttype == 'many2one':
            ids = rnd.random_record_ids(self.env, self.relation, 1)
            return ids[0] if ids else SKIP
        model_name = rnd.random_reference_model(self.env, self._reference_models())
        if not model_name:
            return SKIP
        ids = rnd.random_record_ids(self.env, model_name, 1)
        return '%s,%s' % (model_name, ids[0]) if ids else SKIP

    def _resolve_one2many(self, field):
        """Overridden by the parent-level line, which owns the child config."""
        return SKIP

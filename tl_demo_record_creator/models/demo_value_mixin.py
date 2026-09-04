"""The value half of a configuration line.

One real, typed column per input shape, so every field type is edited with its
own native Odoo widget instead of a single stringly-typed box. The view shows
exactly one of them per row, driven by :attr:`value_widget`.
"""

import logging
from datetime import date, datetime, timedelta

import psycopg2

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools.safe_eval import safe_eval

from . import demo_field_utils as futils
from . import demo_random as rnd

_logger = logging.getLogger(__name__)

# Returned by _resolve_value() to mean "write nothing, let Odoo decide".
SKIP = object()

# The only strings that may stand alone in a domain.
DOMAIN_OPERATORS = ('&', '|', '!')


def reference_state(record, field_name):
    """``(target, broken)`` for a ``fields.Reference`` value - never raises.

    Reading a Reference is not safe. ``convert_to_record`` does
    ``env[model].browse(id)`` on the stored ``'model,id'`` text, and that text
    is a plain varchar that outlives whatever it points at: uninstall the
    module and ``env[model]`` raises ``KeyError`` on the *read*, before any
    ``exists()`` can be reached. Even a live model can raise ``AccessError``
    for a user who may not read it. Since these values are shown in a column
    of the lines list on the template form, one stale reference would
    otherwise make the form itself impossible to open.

    ``target`` is the usable recordset, or ``None``. ``broken`` says whether
    something was stored that cannot be used - as opposed to nothing having
    been chosen at all.
    """
    try:
        target = record[field_name]
    except Exception:  # the model is no longer in the registry
        return None, True
    if not target:
        return None, False
    try:
        if not target.exists():
            return None, True
    except Exception:  # not readable by this user
        return None, True
    return target, False


def clear_stale_references(env, table, column, delete_row=False):
    """Drop stored ``'model,id'`` values whose model is no longer installed.

    A Reference is stored as plain text, and nothing cleans it up when the
    module owning the target model is uninstalled. Reading such a value
    raises ``KeyError`` inside ``convert_to_record`` - that is, inside the
    ORM's own read, before any guard in this addon can see it - so a single
    stale row makes the configuration form impossible to open, and therefore
    impossible to fix from the interface. A module update is the moment to
    sweep them.

    Set ``delete_row`` for a column that is ``required``: its SQL column is
    NOT NULL, so blanking it would abort the update. A row of the selected
    records table means nothing without its record anyway.

    **Which models count as installed is asked of ``ir_model``, not of the
    registry.** At module load time the registry holds only the packages
    processed so far in this pass, in dependency order; this addon depends on
    nothing deeper than ``web``, so ``sale``, ``product``, ``stock`` and
    everything else are still absent from it. ``env`` would happily report
    them missing and the sweep would wipe exactly the demo targets the addon
    exists for. ``ir_model`` holds a row for everything installed at the end
    of the previous run, and loses it on uninstall, which is the question
    actually being asked - and being one statement it needs no Python-side
    membership test at all.

    Raw SQL on purpose: the whole point is that these values cannot be read
    through the ORM. It therefore writes behind the ORM's caches, which is
    safe here only because this runs during module loading, before anything
    has read them.
    """
    condition = (
        "%(col)s IS NOT NULL AND split_part(%(col)s, ',', 1) NOT IN "
        "(SELECT model FROM ir_model)" % {'col': column})
    if delete_row:
        env.cr.execute('DELETE FROM %s WHERE %s' % (table, condition))
    else:
        env.cr.execute(
            'UPDATE %s SET %s = NULL WHERE %s' % (table, column, condition))
    if env.cr.rowcount:
        _logger.info(
            "%s: %s row(s) referred to a model that is no longer installed "
            "and were %s", table, env.cr.rowcount,
            "deleted" if delete_row else "cleared")


def reference_display(record, field_name):
    """A printable name for a ``fields.Reference`` value - never raises."""
    target, broken = reference_state(record, field_name)
    if broken:
        return _("(no longer available)")
    if not target:
        return None
    try:
        return target.display_name
    except Exception:
        return _("(not readable)")


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
        help="The record to write. The model is filled in from the selected "
             "field, so normally only the record itself has to be changed.")

    value_domain = fields.Char(
        string="Domain",
        help="Restricts which records this line may draw on, e.g. "
             "[('state', '=', 'done')].\n\n"
             "It filters the records Random picks, and the record pre-filled "
             "for you when Random is off. A record you go on to choose "
             "yourself is used as chosen. Leave it empty to draw from every "
             "record you can read.")
    domain_model = fields.Char(
        compute='_compute_domain_model',
        string="Domain Model",
        help="The model the domain above is written against. Feeds the domain "
             "editor; declared in the view so it is always read back.")

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

    @api.depends('field_id', 'ttype', 'relation', 'value_reference',
                 'use_random', 'can_use_random')
    def _compute_domain_model(self):
        """The model a domain on this line would be written against.

        Straightforward for a Many2one or Many2many - it is the comodel. A
        true Reference field has no single target, so the model of the chosen
        record is used. With neither, there is no model to write a domain
        against and the input stays hidden.

        While the line will randomise, the chosen record is deliberately
        ignored in favour of the field's first declared model. The record
        picker is off screen in that state, and its model is what a domain
        would be bound to and what Random would draw from - a decision nobody
        can see being made by a control nobody can see is how a template ends
        up quietly generating records from one model only.
        """
        for line in self:
            model = False
            if line.ttype in ('many2one', 'many2many'):
                model = line.relation or False
            elif line.ttype == 'reference':
                record = None
                if not line._will_randomise():
                    record, _broken = line._reference_state()
                if record:
                    model = record._name
                else:
                    allowed = line._declared_reference_models()
                    model = allowed[0] if allowed else False
            line.domain_model = model

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
                 'value_reference', 'value_binary_filename', 'value_count',
                 'value_domain')
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
                label = _("Random (%s record(s))", max(self.value_count, 1))
            else:
                label = _("Random")
            if self._has_domain():
                label = _("%s, filtered", label)
            return label
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
            return reference_display(self, 'value_reference') or _("(empty)")
        if widget == 'many2many':
            names = [name for name in (reference_display(ref, 'record_ref')
                                       for ref in self._explicit_ref_records())
                     if name]
            return ', '.join(names) if names else _("(empty)")
        if widget == 'binary':
            return self.value_binary_filename or (
                _("File attached") if self.value_binary else _("(empty)"))
        return _("(empty)")

    # ------------------------------------------------------------------
    # module update
    # ------------------------------------------------------------------
    def init(self):
        """Called on install and on every module update.

        ``init()`` is called for **every** model in the registry, this
        abstract mixin included, and an abstract model still gets a ``_table``
        name - one with no table behind it. Querying it would abort the whole
        module load, so the concrete models are the only ones that do work
        here.
        """
        super().init()
        if self._abstract or not self._auto:
            return
        clear_stale_references(self.env, self._table, 'value_reference')

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
            # relational and selection values can never survive a field
            # change, and neither can a domain written for another model
            line.value_selection_id = False
            line.value_selection_free = False
            line.value_reference = False
            line.value_domain = False
            line.value_binary = False
            line.value_binary_filename = False
            if line.field_id.ttype not in futils.RANDOMISABLE_TTYPES:
                line.use_random = False
            if line.field_id.ttype in ('many2many', 'one2many') and line.value_count <= 0:
                line.value_count = 1
            line._seed_value_reference()

    @api.onchange('use_random')
    def _onchange_use_random_seed(self):
        """Fill the record picker in as it becomes the thing that matters.

        This is the moment the picker appears, and the moment the user needs
        the model already chosen for them.
        """
        for line in self:
            line._seed_value_reference()

    @api.onchange('value_domain')
    def _onchange_value_domain_clear(self):
        """Drop a chosen record the domain no longer admits.

        Cleared, not replaced. Substituting another record would contradict
        the promise that a record you choose yourself is the record that gets
        used, and would do it invisibly; an empty picker says plainly that the
        new domain ruled the old choice out. A picker the user emptied on
        purpose stays empty too - editing the domain is not a request to put a
        record back.
        """
        for line in self:
            if line.ttype not in ('many2one', 'reference'):
                continue
            record, _broken = line._reference_state()
            if not record or line._reference_matches_domain():
                continue
            line.value_reference = False

    def _seed_value_reference(self):
        """Fill the record picker with a concrete record of the right model.

        A ``fields.Reference`` stores ``'model,id'``, so there is no way to
        set the model half on its own and leave the record empty - the value
        is either a whole record or nothing. Writing the first record of the
        comodel is therefore how the model gets filled in for the user: the
        picker opens on the right model, already searchable, and only the
        record has to be changed. It respects the line's domain, so the
        pre-filled record and Random agree about what is in scope.

        Nothing is seeded while the line will randomise - the picker is not
        even on screen then, and a value nobody can see becoming the value
        that gets written is how a template ends up with a record the user
        never chose. Nothing is seeded over an existing value either, so a
        picker emptied on purpose stays empty.
        """
        self.ensure_one()
        if self.ttype not in ('many2one', 'reference'):
            return
        if self._will_randomise():
            return
        record, _broken = self._reference_state()
        if record:
            return
        domain = self._domain_or_empty()
        comodel_name = (self.relation if self.ttype == 'many2one'
                        else self._first_reference_model(domain))
        if not self._is_referenceable(comodel_name):
            return
        record_id = rnd.first_record_id(self.env, comodel_name, domain)
        if record_id:
            self.value_reference = '%s,%s' % (comodel_name, record_id)

    def _reference_state(self):
        """``(record, broken)`` for the chosen record - see
        :func:`reference_state`."""
        self.ensure_one()
        return reference_state(self, 'value_reference')

    def _declared_reference_models(self):
        """The models a Reference field declares, or ``[]`` - never raises."""
        self.ensure_one()
        try:
            return self._reference_models()
        except Exception:
            return []

    def _first_reference_model(self, domain=()):
        """The model to seed a true Reference field with.

        With a domain in force, only :attr:`domain_model` will do. That is the
        model the domain editor is bound to, so seeding from any other would
        re-point the editor - and the domain the user just wrote - at a model
        they never chose.

        Without one, the field's **first** declared model that actually holds
        a record. Deliberately first and not random, for the same reason:
        :attr:`domain_model` follows whatever lands here.

        A Reference field that declares no models at all is left alone.
        Searching every model in the database to guess one would cost far more
        than it is worth.
        """
        self.ensure_one()
        if domain:
            candidates = [self.domain_model] if self.domain_model else []
        else:
            candidates = self._declared_reference_models()
        for model_name in candidates:
            if not self._is_referenceable(model_name):
                continue
            if rnd.first_record_id(self.env, model_name, domain):
                return model_name
        return False

    def _is_referenceable(self, model_name):
        """Can ``model_name`` be stored in :attr:`value_reference`?

        ``fields.Reference`` validates the model half against its own
        selection and raises a bare ``ValueError`` otherwise. That selection
        excludes transient models, while a configurable Many2one may well
        point at one, so the check has to happen before the assignment.
        """
        self.ensure_one()
        if not model_name:
            return False
        comodel = self.env.get(model_name)
        return comodel is not None and not comodel._transient

    def _reference_matches_domain(self):
        """Does the chosen record still satisfy the line's domain?"""
        self.ensure_one()
        record, _broken = self._reference_state()
        if not record:
            return False
        domain = self._domain_or_empty()
        if not domain:
            return True
        try:
            return bool(record.filtered_domain(domain))
        except Exception:
            # a domain that cannot be run against this model tells us nothing
            # about the record, so leave the record alone
            return True

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
    @api.constrains('value_count', 'field_id')
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

    @api.constrains('value_domain', 'field_id')
    def _check_value_domain(self):
        """Catch a malformed domain at save time, not mid-run."""
        for line in self:
            if line.value_domain:
                line._eval_domain()

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

    def _eval_domain(self):
        """The domain typed on this line, as a list. Raises if it is malformed.

        Evaluated with ``safe_eval`` so the usual domain vocabulary works -
        ``uid``, ``today``, ``datetime``, ``ref('module.xmlid')`` - without
        letting arbitrary code run.
        """
        self.ensure_one()
        text = (self.value_domain or '').strip()
        if not text:
            return []
        try:
            domain = safe_eval(text, {
                'date': date,
                'datetime': datetime,
                'timedelta': timedelta,
                'today': fields.Date.context_today(self),
                'context_today': lambda: fields.Date.context_today(self),
                'now': fields.Datetime.now(),
                'uid': self.env.uid,
                'company_id': self.env.company.id,
                'ref': lambda xmlid: self.env.ref(xmlid).id,
            })
        except Exception as exc:
            raise ValidationError(
                _("The domain on '%(label)s' could not be read:\n\n%(err)s\n\n"
                  "A domain is a list of conditions, for example\n"
                  "[('state', '=', 'done')]",
                  label=self._label(), err=exc)) from exc
        if not isinstance(domain, (list, tuple)):
            raise ValidationError(
                _("The domain on '%(label)s' must be a list of conditions, "
                  "for example [('state', '=', 'done')], not %(got)s.",
                  label=self._label(), got=type(domain).__name__))
        domain = list(domain)
        self._check_domain_shape(domain)
        return domain

    def _check_domain_shape(self, domain):
        """Reject a domain that would only fail later, inside ``search()``.

        Being a list is not enough: a bare leaf written without its
        surrounding brackets, a two-element condition or a stray number all
        get through that test and then blow up mid-run, which is exactly what
        checking the domain at save time is supposed to prevent.
        """
        self.ensure_one()
        for item in domain:
            if isinstance(item, str):
                if item in DOMAIN_OPERATORS:
                    continue
                raise ValidationError(
                    _("'%(item)s' is not a valid part of the domain on "
                      "'%(label)s'. Conditions go in brackets and only "
                      "'&', '|' and '!' may stand on their own, as in\n"
                      "['&', ('state', '=', 'done'), ('active', '=', True)]\n\n"
                      "A single condition still needs its outer brackets: "
                      "[('state', '=', 'done')].",
                      item=item, label=self._label()))
            if not isinstance(item, (list, tuple)) or len(item) != 3:
                raise ValidationError(
                    _("Every condition in the domain on '%(label)s' needs "
                      "exactly three parts - field, operator, value - but "
                      "%(item)r was given.",
                      label=self._label(), item=item))
            field_name, operator = item[0], item[1]
            if not isinstance(field_name, str) or not isinstance(operator, str):
                raise ValidationError(
                    _("The field name and the operator of a condition must "
                      "both be text, but %(item)r was given in the domain on "
                      "'%(label)s'.", item=item, label=self._label()))
        if domain and not self._domain_arity_ok(domain):
            raise ValidationError(
                _("The domain on '%(label)s' has an operator with nothing to "
                  "apply it to. '&' and '|' each need two conditions after "
                  "them and '!' needs one, as in\n"
                  "['&', ('state', '=', 'done'), ('active', '=', True)]",
                  label=self._label()))
        self._check_domain_with_orm(domain)

    def _check_domain_with_orm(self, domain):
        """Let the ORM's own parser have a look, if it is reachable.

        ``odoo.fields.Domain`` knows things this addon should not try to
        duplicate - which operators exist, above all - and a hardcoded list
        would reject the next operator Odoo adds. It is belt and braces
        rather than the mechanism, though: the checks above stand on their
        own, so this quietly doing nothing on a version without that class
        costs nothing.
        """
        self.ensure_one()
        try:
            from odoo.fields import Domain
        except ImportError:
            return
        try:
            Domain(domain)
        except Exception as exc:
            raise ValidationError(
                _("The domain on '%(label)s' was not accepted:\n\n%(err)s\n\n"
                  "A domain is a list of conditions, for example\n"
                  "[('state', '=', 'done')]",
                  label=self._label(), err=exc)) from exc

    @api.model
    def _domain_arity_ok(self, domain):
        """Does the prefix notation of ``domain`` balance?

        Walked right to left: a condition puts one term on the stack, '&' and
        '|' each take two and give one back, '!' takes one and gives one back.
        Anything left over at the end is fine - Odoo joins leftovers with an
        implicit AND, which is what makes ``[cond, cond]`` legal - but running
        out mid-way is not, and that is what ``['&', cond]`` does.
        """
        stack = 0
        for item in reversed(domain):
            if item == '!':
                if stack < 1:
                    return False
            elif item in ('&', '|'):
                if stack < 2:
                    return False
                stack -= 1
            else:
                stack += 1
        return stack >= 1

    def _has_domain(self):
        """Is there a domain on this line that actually filters anything?

        The domain editor writes the string ``"[]"`` when its conditions are
        all removed, which is truthy but filters nothing, so the text alone
        cannot answer this - but a textual test still can, and this runs on
        the display path for every line in the list, so it must not evaluate
        anything.
        """
        self.ensure_one()
        if self.ttype not in futils.RELATIONAL_TTYPES:
            return False
        return (self.value_domain or '').strip() not in ('', '[]', '()', 'None')

    def _domain_or_empty(self):
        """Like :meth:`_eval_domain`, but never raises.

        Used on the paths where a bad domain must not be fatal - seeding the
        record picker from an onchange, for instance, where the user is very
        likely still typing it.
        """
        self.ensure_one()
        try:
            return self._eval_domain()
        except Exception:
            return []

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
            record, _broken = self._reference_state()
            return not record
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
        """Raise a readable error for a line that is configured wrongly.

        "Wrongly" means the configuration itself is inconsistent - a record of
        the wrong model, an option the field does not have, a type the creator
        cannot build a value for. A line left empty is not an error, however
        the model flags the field: many required fields are filled in by the
        model itself, and a blank line simply writes nothing and lets it.
        """
        for line in self:
            line._check_field_is_configurable()
            widget = line.value_widget
            label = line._label()

            if widget == 'unsupported':
                raise UserError(
                    _("'%(label)s' has the unsupported type '%(ttype)s'. "
                      "Remove the line to continue.",
                      label=label, ttype=line.ttype or '?'))

            # a domain that cannot be read is a configuration mistake, and a
            # silently ignored filter is worse than a stopped run
            line._eval_domain()

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
        label = self._label()
        if self._will_randomise():
            # options that could not be read simply produce no value; if the
            # field turns out to need one, the model will say so
            return
        value = (self.value_selection_id.value
                 or (self.value_selection_free or '').strip())
        if not value:
            return
        # reading the options can mean running the field's own selection
        # method, so leave it until there is a value to check
        allowed = [option for option, _lbl in self._selection_options()]
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
                # nothing to pick from means no value is written, not a
                # failure: the model decides whether it needed one
                return
            record, broken = self._reference_state()
            if broken:
                raise UserError(
                    _("The record selected for '%s' can no longer be read. It "
                      "was deleted, or you do not have access to it. Choose "
                      "another one, or clear the line.", label))
            if not record:
                return
            if record._name != comodel_name:
                raise UserError(
                    _("'%(label)s' only accepts %(expected)s records, but "
                      "%(got)s was selected.",
                      label=label, expected=comodel_name, got=record._name))
            return

        # true Reference field
        if self._will_randomise():
            return
        record, broken = self._reference_state()
        if broken:
            raise UserError(
                _("The record selected for '%s' can no longer be read. It was "
                  "deleted, its model was uninstalled, or you do not have "
                  "access to it. Choose another one, or clear the line.",
                  label))
        if not record:
            return
        # _reference_models() can run the field's own selection method, so it
        # is only worth asking for once there is a record to check against
        allowed = self._reference_models()
        if allowed and record._name not in allowed:
            raise UserError(
                _("'%(label)s' does not accept %(got)s records.\n"
                  "Allowed models: %(allowed)s",
                  label=label, got=record._name, allowed=', '.join(allowed)))

    def _validate_many2many(self):
        self.ensure_one()
        label = self._label()
        comodel_name = self.relation
        if not comodel_name or self.env.get(comodel_name) is None:
            raise UserError(
                _("The related model of '%s' could not be resolved.", label))
        if self._will_randomise():
            # fewer records available than asked for links what there is; an
            # empty comodel links nothing at all
            return
        for ref in self._explicit_ref_records():
            record, broken = reference_state(ref, 'record_ref')
            if broken:
                raise UserError(
                    _("A record configured for '%s' can no longer be read. It "
                      "was deleted, or you do not have access to it. Remove "
                      "that row from the Selected Records table.", label))
            if not record:
                raise UserError(
                    _("One of the records configured for '%s' is empty.", label))
            if record._name != comodel_name:
                raise UserError(
                    _("'%(label)s' only accepts %(expected)s records, but "
                      "%(got)s was selected.",
                      label=label, expected=comodel_name, got=record._name))

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
            record, _broken = self._reference_state()
            if not record:
                return SKIP
            if self.ttype == 'many2one':
                return record.id
            return '%s,%s' % (record._name, record.id)
        if widget == 'many2many':
            # a Reference field is not relational to the ORM, so mapped() would
            # hand back a list of recordsets rather than one recordset
            ids = []
            for ref in self._explicit_ref_records():
                record, _broken = reference_state(ref, 'record_ref')
                if record:
                    ids.append(record.id)
            return [(6, 0, ids)]
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
            ids = self._random_ids(self.relation, max(self.value_count, 1),
                                   self._eval_domain())
            return [(6, 0, ids)] if ids else SKIP
        return SKIP

    def _random_ids(self, comodel_name, count, domain):
        """Random ids of ``comodel_name`` matching ``domain``.

        A domain the ORM will not accept - an operator that does not exist, a
        field the comodel does not have - only shows up here, when it reaches
        ``search()``, and left to itself it would surface as a generic "the
        values could not be generated". So it is named: the line, the model
        and the domain that was tried.

        Only failures that are actually about the domain are reworded.
        Anything Odoo already words better keeps its own class and message -
        an ``AccessError`` for a comodel the user may not read (which is why
        ``random_record_ids`` deliberately does not ``sudo``), and a
        ``psycopg2`` error, which the run's own handler passes through so a
        serialisation failure or deadlock can still be retried.
        """
        self.ensure_one()
        try:
            ids = rnd.random_record_ids(self.env, comodel_name, count, domain)
        except (UserError, ValidationError, psycopg2.Error):
            raise
        except Exception as exc:
            if not domain:
                raise
            raise UserError(
                _("The domain on '%(label)s' could not be applied to "
                  "%(model)s:\n\n%(err)s\n\nDomain: %(domain)s",
                  label=self._label(), model=comodel_name, err=exc,
                  domain=self.value_domain or '[]')) from exc
        if domain and not ids:
            # asked for a filter and got nothing back: that is the user's own
            # instruction failing, not the model declining a value, so it is
            # said out loud rather than quietly writing nothing
            raise UserError(
                _("No %(model)s record matches the domain on '%(label)s', so "
                  "Random has nothing to pick.\n\nDomain: %(domain)s\n\n"
                  "Widen it, or clear it to draw from every record.",
                  model=comodel_name, label=self._label(),
                  domain=self.value_domain or '[]'))
        return ids

    def _random_relational_value(self):
        self.ensure_one()
        domain = self._eval_domain()
        if self.ttype == 'many2one':
            ids = self._random_ids(self.relation, 1, domain)
            return ids[0] if ids else SKIP

        # A true Reference field can point at several models, and a domain
        # written for one of them means nothing on the others - it would
        # either fail, or worse, quietly match on a same-named field. So with
        # a domain, the model it was written against is the only one
        # considered, and no model means no value: falling through to the
        # unrestricted search would scan every model in the database and
        # apply the domain to whichever one it happened to run on.
        if domain:
            model_name = self.domain_model
            if not model_name:
                raise UserError(
                    _("There is a domain on '%(label)s' but no model to apply "
                      "it to - the field declares none, so there is nothing "
                      "to filter. Clear the domain.", label=self._label()))
        else:
            model_name = rnd.random_reference_model(
                self.env, self._declared_reference_models())
        if not model_name:
            return SKIP
        ids = self._random_ids(model_name, 1, domain)
        return '%s,%s' % (model_name, ids[0]) if ids else SKIP

    def _resolve_one2many(self, field):
        """Overridden by the parent-level line, which owns the child config."""
        return SKIP

"""Demo record templates.

Pick a model, configure the fields you care about, say how many records you
want, press Create Records. Everything else is either taken from the model's
own defaults or generated at random, per record.

This is a **saved** record rather than a transient wizard, so a configuration
can be named, kept, duplicated and re-run.

Nothing is loaded into the tables on your behalf, and nothing is checked
against the model's ``required`` flags before the run. A field flagged
required in Python is very often filled in by the model itself
(``sale.order.name`` comes from a sequence, ``date_order`` from a default), so
demanding a value for it would block perfectly valid configurations. The run
sends what you configured and lets the model answer; whatever it objects to is
reported back verbatim, with the values that were attempted.
"""

import logging

import psycopg2

from odoo import _, api, fields, models
from odoo.exceptions import RedirectWarning, UserError, ValidationError

from . import demo_field_utils as futils
from .demo_value_mixin import SKIP

_logger = logging.getLogger(__name__)

MAX_RECORDS = 1000
MAX_CHILD_RECORDS = 10000


class DemoRecordCreator(models.Model):
    _name = 'tl.demo.record.creator'
    _description = 'Demo Record Template'
    _order = 'name'

    name = fields.Char(
        string="Template Name",
        required=True,
        default=lambda self: self._default_name(),
        help="What this configuration is for, so it can be found and re-run.")
    active = fields.Boolean(default=True)

    last_run_date = fields.Datetime(
        string="Last Run", readonly=True, copy=False)
    last_created_count = fields.Integer(
        string="Records Created", readonly=True, copy=False,
        help="How many records the last run created.")

    model_id = fields.Many2one(
        'ir.model',
        string="Model",
        required=True,
        ondelete='cascade',
        domain=[('transient', '=', False)],
        help="The model records will be created in.")
    model_name = fields.Char(related='model_id.model', string="Technical Model")

    record_count = fields.Integer(
        string="Number of Records",
        default=1,
        required=True,
        help="How many records to create in the selected model.")

    line_ids = fields.One2many(
        'tl.demo.record.creator.line', 'creator_id', string="Fields")
    ref_ids = fields.One2many(
        'tl.demo.record.creator.ref', 'creator_id',
        string="Selected Records")

    line_count = fields.Integer(compute='_compute_summary')
    o2m_line_count = fields.Integer(compute='_compute_summary')
    m2m_line_count = fields.Integer(compute='_compute_summary')
    total_child_count = fields.Integer(compute='_compute_summary')

    allowed_field_ids = fields.Many2many(
        'ir.model.fields', compute='_compute_allowed_field_ids',
        string="Selectable Fields",
        help="Feeds the Field dropdown of the Fields table.")

    m2m_field_ids = fields.Many2many(
        'ir.model.fields', compute='_compute_relational_fields',
        string="Configured Many2many Fields",
        help="Feeds the domain of the selected records table.")

    apply_model_defaults = fields.Boolean(
        string="Apply Model Defaults",
        default=True,
        help="Let the model compute its own defaults and dependent values for "
             "every field you did not configure, the way the form view would.")
    open_records = fields.Boolean(
        string="Open Created Records",
        default=True,
        help="Show the created records in a list view once the creator is done.")

    # ------------------------------------------------------------------
    # defaults
    # ------------------------------------------------------------------
    @api.model
    def _default_name(self):
        return _("New Demo Template")

    @api.onchange('model_id')
    def _onchange_model_id_name(self):
        """Name the template after its model until the user renames it."""
        for template in self:
            if template.model_id and template.name in (False, '', self._default_name()):
                template.name = _("%s demo", template.model_id.name)

    # ------------------------------------------------------------------
    # computes
    # ------------------------------------------------------------------
    @api.depends('line_ids.ttype', 'line_ids.value_count',
                 'line_ids.child_line_ids', 'record_count')
    def _compute_summary(self):
        for creator in self:
            lines = creator.line_ids
            o2m = lines.filtered(lambda line: line.ttype == 'one2many')
            creator.line_count = len(lines)
            creator.o2m_line_count = len(o2m)
            creator.m2m_line_count = len(
                lines.filtered(lambda line: line.ttype == 'many2many'))
            # a One2many with no child field configured creates no children,
            # so counting its Number of Values here would promise records
            # that the run will not write
            configured = o2m.filtered(lambda line: line.child_line_ids)
            creator.total_child_count = (
                max(creator.record_count, 0)
                * sum(configured.mapped('value_count')))

    @api.depends('model_id')
    def _compute_allowed_field_ids(self):
        for creator in self:
            creator.allowed_field_ids = [(6, 0, futils.selectable_field_ids(
                self.env, creator.model_id.model))]

    @api.depends('line_ids.ttype', 'line_ids.field_id')
    def _compute_relational_fields(self):
        for creator in self:
            lines = creator.line_ids
            creator.m2m_field_ids = lines.filtered(
                lambda line: line.ttype == 'many2many').mapped('field_id')

    # ------------------------------------------------------------------
    # constraints
    # ------------------------------------------------------------------
    @api.constrains('record_count')
    def _check_record_count(self):
        for creator in self:
            if creator.record_count < 1:
                raise ValidationError(
                    _("Number of Records must be a positive integer."))
            if creator.record_count > MAX_RECORDS:
                raise ValidationError(
                    _("Number of Records is capped at %s per run. Run again for more.",
                      MAX_RECORDS))

    # ------------------------------------------------------------------
    # onchange
    # ------------------------------------------------------------------
    @api.onchange('model_id')
    def _onchange_model_id(self):
        """Empty the tables - lines of the old model cannot apply to the new one.

        Deliberately loads nothing in their place: use the Load buttons to pull
        in the fields you want.
        """
        for creator in self:
            creator.ref_ids = [(5, 0, 0)]
            creator.line_ids = [(5, 0, 0)]

    @api.onchange('line_ids')
    def _onchange_line_ids(self):
        """Keep the selected records table in step with the field lines."""
        for creator in self:
            m2m_field_ids = set(
                creator.line_ids.filtered(lambda l: l.ttype == 'many2many')
                .mapped('field_id').ids)
            stale_refs = creator.ref_ids.filtered(
                lambda ref: ref.field_id.id not in m2m_field_ids)
            if stale_refs:
                creator.ref_ids = creator.ref_ids - stale_refs

    # ------------------------------------------------------------------
    # buttons
    # ------------------------------------------------------------------
    def action_load_required_fields(self):
        self.ensure_one()
        self.ref_ids = [(5, 0, 0)]
        self.line_ids = [(5, 0, 0)] + self._line_vals(required_only=True)

    def action_load_all_fields(self):
        self.ensure_one()
        self.ref_ids = [(5, 0, 0)]
        self.line_ids = [(5, 0, 0)] + self._line_vals(required_only=False)

    def action_clear_fields(self):
        self.ensure_one()
        self.ref_ids = [(5, 0, 0)]
        self.line_ids = [(5, 0, 0)]

    # ------------------------------------------------------------------
    # line building
    # ------------------------------------------------------------------
    def _target_model(self):
        self.ensure_one()
        if not self.model_id:
            raise UserError(_("Select a model first."))
        model = self.env.get(self.model_id.model)
        if model is None:
            raise UserError(
                _("Model '%s' does not exist in this database.",
                  self.model_id.model))
        if model._transient:
            raise UserError(
                _("'%s' is a transient model, its records would be deleted "
                  "again shortly. Pick another model.", self.model_id.model))
        return model

    def _line_vals(self, required_only=True):
        """``[(0, 0, vals)]`` commands for the fields a Load button asked for.

        One2many lines are created bare. Their child configuration is loaded
        only when you ask for it inside the line, so a nested table is never
        filled in behind your back.
        """
        self.ensure_one()
        model = self._target_model()
        candidates = (futils.required_fields(model) if required_only
                      else futils.configurable_fields(model))
        IrModelFields = self.env['ir.model.fields']
        commands = []
        for index, field in enumerate(candidates):
            field_rec = IrModelFields._get(model._name, field.name)
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
    def _validate(self):
        """Structural checks only.

        This looks for configuration that could not possibly work - a field
        from another model, the same field twice, a run size over the caps -
        and stops there. It deliberately does **not** check the model's
        ``required`` fields: whether a value is really needed is the model's
        call, made during the run, not a guess made here.
        """
        self.ensure_one()
        model = self._target_model()

        if self.record_count < 1:
            raise UserError(_("Number of Records must be a positive integer."))
        if self.record_count > MAX_RECORDS:
            raise UserError(
                _("Number of Records is capped at %s per run.", MAX_RECORDS))
        if self.total_child_count > MAX_CHILD_RECORDS:
            raise UserError(
                _("This configuration would create %(total)s child records, "
                  "over the %(cap)s limit. Lower Number of Records or Number "
                  "of Values.",
                  total=self.total_child_count, cap=MAX_CHILD_RECORDS))

        self._check_create_access(model)

        # one line per field, otherwise the last one silently wins
        seen = {}
        for line in self.line_ids:
            if not line.field_id:
                raise UserError(
                    _("One configuration line has no field selected."))
            if line.field_id.model != model._name:
                raise UserError(
                    _("'%(field)s' belongs to %(other)s, not to %(model)s.",
                      field=line._label(), other=line.field_id.model,
                      model=model._name))
            if line.field_name in seen:
                raise UserError(
                    _("'%s' is configured twice. Remove one of the lines.",
                      line._label()))
            seen[line.field_name] = line

        for ref in self.ref_ids:
            if not ref.field_id or ref.field_id.id not in self.m2m_field_ids.ids:
                raise UserError(
                    _("A selected record refers to '%s', which is not a "
                      "Many2many field configured above.",
                      ref.field_id.field_description or _("(no field)")))

        self.line_ids._validate_for_creation()

    def _check_create_access(self, model):
        self.ensure_one()
        try:
            if hasattr(model, 'check_access'):
                model.check_access('create')
            else:  # Odoo <= 17
                model.check_access_rights('create')
        except UserError:
            raise
        except Exception as exc:
            raise UserError(
                _("You are not allowed to create %(model)s records.\n\n%(err)s",
                  model=model._name, err=exc)) from exc

    # ------------------------------------------------------------------
    # creation
    # ------------------------------------------------------------------
    def action_create_records(self):
        self.ensure_one()
        self._validate()
        model = self._target_model()

        try:
            vals_list = [self._build_vals(model, index)
                         for index in range(self.record_count)]
        except (UserError, ValidationError, RedirectWarning,
                psycopg2.OperationalError, psycopg2.IntegrityError):
            # already readable, or a database failure Odoo words better than
            # this addon can
            raise
        except Exception as exc:
            _logger.warning(
                "Demo Record Creator could not build values for %s",
                model._name, exc_info=True)
            raise UserError(
                _("The values for %(model)s could not be generated:\n\n"
                  "%(err)s\n\nNothing was created.",
                  model=self.model_id.name or model._name,
                  err=self._error_message(exc))) from exc

        try:
            with self.env.cr.savepoint():
                records = model.create(vals_list)
                if hasattr(records, 'flush_recordset'):
                    records.flush_recordset()
                elif hasattr(self.env, 'flush_all'):
                    self.env.flush_all()
        except Exception as exc:
            # Odoo's own UserError and ValidationError come through here too,
            # so the message always arrives with the values that produced it.
            # _creation_error hands back the exception to raise, which for a
            # few kinds of failure is the original one, untouched.
            error = self._creation_error(model, exc, vals_list)
            if error is exc:
                raise
            raise error from exc

        self.write({
            'last_run_date': fields.Datetime.now(),
            'last_created_count': len(records),
        })
        return self._result_action(model, records)

    # ------------------------------------------------------------------
    # error reporting
    # ------------------------------------------------------------------
    def _creation_error(self, model, exc, vals_list):
        """The exception to raise for a failed run - not always a ``UserError``.

        The message the model gave is reproduced as-is - it names the field it
        is unhappy about - followed by the values that were actually sent, so
        the offending line can be found without guessing.

        Two kinds of failure are handed back untouched instead, because
        rewriting them would lose something the client or the server needs:

        * ``RedirectWarning`` carries an action, its "go and fix it here"
          button, in ``args`` beyond the message;
        * ``psycopg2.OperationalError`` is how a serialisation failure or a
          deadlock arrives, and Odoo retries the whole request when it sees
          one. Turning it into a ``UserError`` would defeat that retry.

        A ``psycopg2`` constraint violation is the interesting one. A
        ``required`` field is a NOT NULL column, so a value that really was
        needed arrives here as one, and raw psycopg2 text is no way to say
        so: it is turned into a sentence naming the model and the field.

        Everything else keeps its own class, so an ``AccessError`` is still
        rendered as an access problem and a ``ValidationError`` as a
        constraint; only the message is enriched.
        """
        self.ensure_one()
        _logger.warning(
            "Demo Record Creator failed on %s", model._name, exc_info=True)

        if isinstance(exc, (RedirectWarning, psycopg2.OperationalError)):
            return exc

        # A failure that already changed the in-memory registry - a template
        # targeting ir.model.fields, say - has to reach Odoo's own request
        # handler, because resetting the registry is something only it can do.
        if getattr(self.env.registry, 'registry_invalidated', False):
            return exc

        # the savepoint rolled back and invalidated the caches already; this
        # is belt and braces, and must not flush from inside an exception
        # handler nor raise anything of its own
        try:
            self.env.invalidate_all(flush=False)
        except Exception:  # older signature, or no such method
            _logger.debug("Could not invalidate the cache", exc_info=True)

        try:
            return self._describe_creation_error(model, exc, vals_list)
        except Exception:
            # reading the configuration back needs the database, and the
            # failure that brought us here may have taken the connection with
            # it. The model's own message still has to get through.
            _logger.warning(
                "Demo Record Creator could not describe its own failure",
                exc_info=True)
            return UserError(self._error_message(exc))

    def _describe_creation_error(self, model, exc, vals_list):
        """The enriched exception - the part of :meth:`_creation_error` that
        needs the database, so that its caller can fall back if it fails."""
        self.ensure_one()
        detail = None
        error_class = UserError
        if isinstance(exc, psycopg2.Error):
            detail = self._constraint_message(exc)
            if detail:
                error_class = ValidationError
        if detail is None:
            detail = self._error_message(exc)
            if isinstance(exc, UserError):
                error_class = type(exc)

        message = _(
            "%(model)s refused the values, so nothing was created.\n\n"
            "%(detail)s\n\n"
            "Values sent for the first record:\n%(attempted)s\n\n"
            "Configure the field the message names, or remove its line from "
            "the template, and run again.",
            model=self.model_id.name or model._name,
            detail=detail,
            attempted=self._describe_vals(model, vals_list[0] if vals_list else {}),
        )
        try:
            return error_class(message)
        except Exception:  # a subclass with a different signature
            return UserError(message)

    def _constraint_message(self, exc):
        """A readable sentence for a database constraint violation, or ``None``.

        Built from psycopg2's own diagnostics - ``exc.diag`` is public API -
        rather than from ``odoo.service.model._as_validation_error``, which is
        private and whose signature has moved between versions. The four
        states below are the ones a generated value can realistically hit.
        """
        self.ensure_one()
        diag = getattr(exc, 'diag', None)
        state = getattr(diag, 'sqlstate', None)
        if not state:
            return None
        table = getattr(diag, 'table_name', None)
        target = self._model_from_table(table)
        model_label = (
            (target._description or target._name) if target is not None
            else table or _("the model"))
        column = getattr(diag, 'column_name', None)
        field = target._fields.get(column) if (target is not None and column) else None
        field_label = ('%s (%s)' % (field.string, column) if field
                       else column or _("one of the columns"))
        constraint = getattr(diag, 'constraint_name', None) or _("(unnamed)")

        if state == '23502':  # not_null_violation
            return _("%(model)s requires a value for %(field)s, and none was "
                     "sent. Configure that line, or tick Random on it.",
                     model=model_label, field=field_label)
        if state == '23505':  # unique_violation
            return _("Another %(model)s record already exists with these "
                     "values (constraint %(constraint)s). Vary the values, or "
                     "tick Random so each record differs.",
                     model=model_label, constraint=constraint)
        if state == '23503':  # foreign_key_violation
            return _("A record referenced by %(model)s does not exist "
                     "(constraint %(constraint)s). One of the relational "
                     "lines points at a record that has since been deleted.",
                     model=model_label, constraint=constraint)
        if state == '23514':  # check_violation
            return _("The values break a constraint of %(model)s "
                     "(%(constraint)s).",
                     model=model_label, constraint=constraint)
        return None

    def _model_from_table(self, table):
        """The model stored in ``table``, or ``None``."""
        if not table:
            return None
        for model_class in self.env.registry.values():
            if getattr(model_class, '_table', None) == table:
                return self.env[model_class._name]
        return None

    @api.model
    def _error_message(self, exc):
        """The text of ``exc``, unwrapped from Odoo's exception classes.

        An Odoo message is written for a person to read and is kept whole. A
        raw database or Python error is not: psycopg2 in particular appends a
        ``DETAIL: Failing row contains (...)`` dump of the entire row, which
        is unreadable and can be enormous, so those are capped.
        """
        if isinstance(exc, (UserError, ValidationError)) and exc.args:
            return str(exc.args[0]).strip() or exc.__class__.__name__
        message = str(exc).strip()
        if len(message) > 2000:
            message = message[:2000] + '...'
        return message or exc.__class__.__name__

    def _describe_vals(self, model, vals):
        """The generated values of one record, one readable line per field.

        Every configured line gets a row, including the ones that produced
        nothing - a line left blank is the most likely reason the model
        objected, so it has to be visible. Values the model filled in for
        itself are counted rather than listed: there can be dozens, and they
        are not what the user can act on.
        """
        self.ensure_one()
        rows = []
        configured = []
        for line in self.line_ids:
            name = line.field_name
            if not name:
                continue
            configured.append(name)
            field = model._fields.get(name)
            label = (field.string if field else False) or line._label() or name
            described = (self._describe_value(vals[name]) if name in vals
                         else _("nothing was sent - the line is blank"))
            rows.append('- %s (%s): %s' % (label, name, described))
        if not rows:
            rows.append(_("- (no field is configured on this template)"))
        from_model = len(set(vals) - set(configured))
        if from_model > 0:
            rows.append(_("- plus %s value(s) the model supplied itself",
                          from_model))
        return '\n'.join(rows)

    @api.model
    def _describe_value(self, value):
        """One short, printable line for a generated value."""
        if isinstance(value, bool):
            return _("Yes") if value else _("No")
        if isinstance(value, (list, tuple)):
            commands = [c for c in value
                        if isinstance(c, (list, tuple)) and len(c) == 3]
            linked = [c for c in commands if c[0] == 6]
            if linked:
                return _("%s linked record(s)", len(linked[0][2] or []))
            children = [c for c in commands if c[0] == 0]
            if children:
                return _("%(count)s child record(s), each with %(keys)s",
                         count=len(children),
                         keys=', '.join(sorted(children[0][2] or {}))
                              or _("no value"))
            return _("(empty)")
        if isinstance(value, bytes):
            return _("%s byte(s) of file data", len(value))
        if value is None:  # False is a bool, handled above
            return _("(empty)")
        text = str(value)
        if len(text) > 120:
            text = text[:120] + '...'
        return text

    def _build_vals(self, model, index):
        """Values for one generated record."""
        self.ensure_one()
        vals = {}
        for line in self.line_ids:
            value = line._resolve_value()
            if value is SKIP:
                continue
            vals[line.field_name] = value
        return self._merge_model_defaults(model, vals)

    def _merge_model_defaults(self, model, vals):
        """Let the model fill in what the user did not configure."""
        self.ensure_one()
        if not self.apply_model_defaults:
            return vals
        try:
            record = model.new(dict(vals))
        except Exception:
            _logger.debug("Could not build an in-memory %s", model._name,
                          exc_info=True)
            return vals

        extra = {}
        for name, field in model._fields.items():
            if name in vals or name in futils.MAGIC_FIELDS:
                continue
            if field.readonly or field.related or not field.store:
                continue
            if field.compute and not field.inverse:
                continue
            if field.type in ('one2many', 'many2many', 'binary',
                              'json', 'properties', 'properties_definition'):
                continue
            try:
                value = record[name]
            except Exception:
                continue
            if not value:
                continue
            extra[name] = value.id if field.type == 'many2one' else value

        extra.update(vals)
        return extra

    def _result_action(self, model, records):
        self.ensure_one()
        if not self.open_records:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'type': 'success',
                    'title': _("Records created"),
                    'message': _("%(count)s %(model)s record(s) created.",
                                 count=len(records), model=self.model_id.name),
                },
            }
        return {
            'type': 'ir.actions.act_window',
            'name': _("Created %s Records", self.model_id.name),
            'res_model': model._name,
            'view_mode': 'list,form',
            'domain': [('id', 'in', records.ids)],
            'target': 'current',
        }

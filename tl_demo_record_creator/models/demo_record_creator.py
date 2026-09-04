"""Demo record templates.

Pick a model, configure the fields you care about, say how many records you
want, press Create Records. Everything else is either taken from the model's
own defaults or generated at random, per record.

This is a **saved** record rather than a transient wizard, so a configuration
can be named, kept, duplicated and re-run.
"""

import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

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
    @api.depends('line_ids.ttype', 'line_ids.value_count', 'record_count')
    def _compute_summary(self):
        for creator in self:
            lines = creator.line_ids
            o2m = lines.filtered(lambda line: line.ttype == 'one2many')
            creator.line_count = len(lines)
            creator.o2m_line_count = len(o2m)
            creator.m2m_line_count = len(
                lines.filtered(lambda line: line.ttype == 'many2many'))
            creator.total_child_count = (
                max(creator.record_count, 0) * sum(o2m.mapped('value_count')))

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
        """Start from the model's required fields."""
        for creator in self:
            creator.ref_ids = [(5, 0, 0)]
            creator.line_ids = [(5, 0, 0)]
            if creator.model_id:
                creator.line_ids = creator._line_vals(required_only=True)

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
            line_vals = {
                'sequence': (index + 1) * 10,
                'field_id': field_rec.id,
                'use_random': field.type in futils.RANDOMISABLE_TTYPES,
                'value_count': 1,
            }
            if field.type == 'one2many' and field.comodel_name:
                child_model = self.env.get(field.comodel_name)
                if child_model:
                    inverse = getattr(field, 'inverse_name', False)
                    child_candidates = (
                        futils.required_fields(child_model) if required_only
                        else futils.configurable_fields(child_model))
                    child_commands = []
                    for c_idx, c_field in enumerate(child_candidates):
                        if inverse and c_field.name == inverse:
                            continue
                        c_rec = IrModelFields._get(field.comodel_name, c_field.name)
                        if not c_rec:
                            continue
                        child_commands.append((0, 0, {
                            'sequence': (c_idx + 1) * 10,
                            'field_id': c_rec.id,
                            'use_random': c_field.type in futils.RANDOMISABLE_TTYPES,
                            'value_count': 1,
                        }))
                    if child_commands:
                        line_vals['child_line_ids'] = child_commands
            commands.append((0, 0, line_vals))
        return commands

    # ------------------------------------------------------------------
    # validation
    # ------------------------------------------------------------------
    def _validate(self):
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

        missing = [
            f for f in futils.required_fields(model) if f.name not in seen
        ]
        if missing:
            raise UserError(
                _("These required fields of %(model)s are not configured:\n"
                  "%(fields)s\n\nUse 'Load Required Fields' to add them.",
                  model=model._name,
                  fields='\n'.join(
                      '- %s (%s)' % (f.string, f.name) for f in missing)))

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

        vals_list = [self._build_vals(model, index)
                     for index in range(self.record_count)]

        try:
            with self.env.cr.savepoint():
                records = model.create(vals_list)
                if hasattr(records, 'flush_recordset'):
                    records.flush_recordset()
                elif hasattr(self.env, 'flush_all'):
                    self.env.flush_all()
        except (UserError, ValidationError):
            raise
        except Exception as exc:
            _logger.warning(
                "Demo Record Creator failed on %s", model._name,
                exc_info=True)
            raise UserError(
                _("%(model)s refused the generated values:\n\n%(err)s\n\n"
                  "Nothing was created. Adjust the configuration and try "
                  "again.", model=model._name, err=exc)) from exc

        self.write({
            'last_run_date': fields.Datetime.now(),
            'last_created_count': len(records),
        })
        return self._result_action(model, records)

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

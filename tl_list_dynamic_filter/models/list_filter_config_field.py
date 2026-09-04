from datetime import datetime, time

import pytz
from markupsafe import escape

from odoo import api, fields, models
from odoo.exceptions import ValidationError

from . import list_filter_operators as ops

WIZARD_MODEL = 'list.filter.wizard'


class ListFilterConfigField(models.Model):
    """One filterable field exposed by a configuration.

    Each record materialises one (or two, for ranges) *real* manual field(s) on
    the wizard model, so the popup can use native Odoo widgets.
    """

    _name = 'list.filter.config.field'
    _description = 'List Filter Configured Field'
    _order = 'sequence, id'

    sequence = fields.Integer(default=10)

    config_id = fields.Many2one(
        'list.filter.configuration',
        string="Configuration",
        required=True,
        ondelete='cascade',
        index=True,
    )
    model_id = fields.Many2one(related='config_id.model_id', store=True)

    field_id = fields.Many2one(
        'ir.model.fields',
        string="Field",
        required=True,
        ondelete='cascade',
        domain="[('model_id', '=', model_id),"
               " ('store', '=', True),"
               " ('ttype', 'not in', ['binary', 'image', 'json', 'properties',"
               " 'properties_definition', 'reference', 'many2one_reference'])]",
    )

    label = fields.Char(
        string="Label",
        help="Shown next to the input in the filter popup. "
             "Defaults to the field label.",
    )
    display_label = fields.Char(compute='_compute_display_label')
    placeholder = fields.Char(help="Hint text shown inside the input.")

    ttype = fields.Selection(related='field_id.ttype', store=True, string="Type")
    relation = fields.Char(related='field_id.relation', store=True)
    field_family = fields.Char(compute='_compute_field_family', store=True)

    operator = fields.Selection(
        selection=ops.OPERATORS,
        string="Condition",
        required=True,
        default='ilike',
        help="How the value entered by the user is matched.",
    )
    operator_hint = fields.Char(compute='_compute_operator_hint')
    is_range = fields.Boolean(compute='_compute_field_family', store=True)

    # --- generated wizard fields -----------------------------------------
    wizard_field_id = fields.Many2one(
        'ir.model.fields', string="Wizard Field",
        readonly=True, copy=False, ondelete='set null')
    wizard_field_to_id = fields.Many2one(
        'ir.model.fields', string="Wizard Field (to)",
        readonly=True, copy=False, ondelete='set null')

    _sql_constraints = [
        ('field_uniq', 'unique(config_id, field_id)',
         'This field is already part of the filter configuration.'),
    ]

    # ------------------------------------------------------------------
    # compute / constraints
    # ------------------------------------------------------------------
    @api.depends('ttype', 'operator')
    def _compute_field_family(self):
        for rec in self:
            rec.field_family = ops.family_of(rec.ttype) or False
            rec.is_range = ops.needs_range(rec.operator)

    @api.depends('label', 'field_id')
    def _compute_display_label(self):
        for rec in self:
            rec.display_label = rec.label or rec.field_id.field_description or ''

    @api.depends('field_id', 'label')
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = rec.label or rec.field_id.field_description or ''

    @api.depends('ttype')
    def _compute_operator_hint(self):
        for rec in self:
            allowed = [ops.OPERATOR_LABELS[o] for o in ops.allowed_operators(rec.ttype)]
            rec.operator_hint = ', '.join(allowed) if allowed else ''

    @api.constrains('field_id', 'operator')
    def _check_field_and_operator(self):
        for rec in self:
            if not rec.field_id:
                continue
            if not ops.family_of(rec.field_id.ttype):
                raise ValidationError(
                    "Field '%s' (%s) cannot be used as a filter."
                    % (rec.field_id.field_description, rec.field_id.ttype)
                )
            allowed = ops.allowed_operators(rec.field_id.ttype)
            if rec.operator not in allowed:
                raise ValidationError(
                    "'%s' is not a valid condition for the %s field '%s'.\n"
                    "Available: %s"
                    % (ops.OPERATOR_LABELS.get(rec.operator, rec.operator),
                       rec.field_id.ttype, rec.field_id.field_description,
                       ', '.join(ops.OPERATOR_LABELS[o] for o in allowed))
                )

    @api.onchange('field_id')
    def _onchange_field_id(self):
        for rec in self:
            rec.operator = ops.default_operator(rec.field_id.ttype)

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('field_id') and not vals.get('operator'):
                field = self.env['ir.model.fields'].browse(vals['field_id'])
                vals['operator'] = ops.default_operator(field.ttype)
        records = super().create(vals_list)
        records._sync_wizard_fields()
        return records

    def write(self, vals):
        res = super().write(vals)
        if {'field_id', 'operator'} & set(vals):
            # the shape of the generated field changes -> rebuild it
            self._sync_wizard_fields()
        elif 'label' in vals:
            # only the caption moved: rename in place, no schema churn
            self._rename_wizard_fields()
        return res

    def _rename_wizard_fields(self):
        for rec in self:
            if rec.wizard_field_id:
                rec.wizard_field_id.sudo().write(
                    {'field_description': rec.display_label})
            if rec.wizard_field_to_id:
                rec.wizard_field_to_id.sudo().write(
                    {'field_description': '%s (to)' % rec.display_label})
        self.mapped('config_id')._build_wizard_view()

    def unlink(self):
        generated = self.mapped('wizard_field_id') | self.mapped('wizard_field_to_id')
        configs = self.mapped('config_id')
        configs._blank_wizard_views()
        res = super().unlink()
        generated.sudo().unlink()
        configs._build_wizard_view()
        return res

    # ------------------------------------------------------------------
    # wizard field generation
    # ------------------------------------------------------------------
    def _wizard_field_name(self, suffix=''):
        self.ensure_one()
        return 'x_flt_%s%s' % (self.id, suffix)

    def _sync_wizard_fields(self):
        """Create / refresh the real fields backing these rows in the popup.

        Everything is created in a single ``ir.model.fields.create`` call: each
        one triggers a registry reload, so batching keeps configuring 50 fields
        fast instead of painful.
        """
        if not self:
            return
        IrModelFields = self.env['ir.model.fields'].sudo()
        wizard_model = self.env['ir.model']._get(WIZARD_MODEL)

        # start from a clean slate -- the field shape depends on the operator
        stale = self.mapped('wizard_field_id') | self.mapped('wizard_field_to_id')
        if stale:
            self.mapped('config_id')._blank_wizard_views()
            stale.sudo().unlink()

        vals_list, owners = [], []
        for rec in self:
            shape = ops.shape_of(rec.ttype, rec.operator)
            if not shape:
                continue
            base = rec._field_values(shape, wizard_model)
            vals_list.append(dict(
                base,
                name=rec._wizard_field_name(),
                field_description=rec.display_label,
            ))
            owners.append((rec, 'wizard_field_id'))

            if ops.needs_range(rec.operator):
                vals_list.append(dict(
                    base,
                    name=rec._wizard_field_name('_to'),
                    field_description='%s (to)' % rec.display_label,
                    **rec._m2m_table_values(shape, suffix='_to')
                ))
                owners.append((rec, 'wizard_field_to_id'))

        if vals_list:
            created = IrModelFields.create(vals_list)
            for (rec, target), field in zip(owners, created):
                rec.write({target: field.id})

        self.mapped('config_id')._build_wizard_view()

    def _m2m_table_values(self, shape, suffix=''):
        """A Many2many needs its own relation table per generated field."""
        self.ensure_one()
        if shape != 'm2m':
            return {}
        return {
            'relation_table': 'x_flt_%s%s_rel' % (self.id, suffix),
            'column1': 'wizard_id',
            'column2': 'record_id',
        }

    def _field_values(self, shape, wizard_model):
        """Base ``ir.model.fields`` values for the generated wizard field."""
        self.ensure_one()
        vals = {
            'model_id': wizard_model.id,
            'model': WIZARD_MODEL,
            'state': 'manual',
            'store': True,
            'required': False,
            'copied': False,
        }

        if shape == 'char':
            vals['ttype'] = 'char'
        elif shape == 'same':
            # numbers and dates keep their native type and widget
            if self.ttype == 'datetime':
                vals['ttype'] = 'date'
            elif self.ttype == 'monetary':
                vals['ttype'] = 'float'
            else:
                vals['ttype'] = self.ttype
        elif shape == 'bool':
            vals['ttype'] = 'selection'
            vals['selection_ids'] = [
                (0, 0, {'value': 'yes', 'name': 'Yes', 'sequence': 10}),
                (0, 0, {'value': 'no', 'name': 'No', 'sequence': 20}),
            ]
        elif shape == 'select':
            vals['ttype'] = 'selection'
            vals['selection_ids'] = [
                (0, 0, {'value': value, 'name': label, 'sequence': (i + 1) * 10})
                for i, (value, label) in enumerate(self._read_selection_options())
            ]
        elif shape == 'm2o':
            vals['ttype'] = 'many2one'
            vals['relation'] = self.relation
            vals['on_delete'] = 'set null'
        elif shape == 'm2m':
            vals['ttype'] = 'many2many'
            vals['relation'] = self.relation
            vals.update(self._m2m_table_values(shape))

        return vals

    def _read_selection_options(self):
        """Return ``[(value, label)]`` of a Selection field, whatever its origin."""
        self.ensure_one()
        if self.field_id.selection_ids:
            return [(s.value, s.name)
                    for s in self.field_id.selection_ids.sorted('sequence')]
        model = self.env.get(self.field_id.model)
        if model is None:
            return []
        field = model._fields.get(self.field_id.name)
        if field is None:
            return []
        try:
            selection = field.selection
            if callable(selection):
                selection = selection(model)
            elif isinstance(selection, str):
                selection = getattr(model, selection)()
            return [(str(v), str(lbl)) for v, lbl in (selection or [])]
        except Exception:
            return []

    # ------------------------------------------------------------------
    # domain
    # ------------------------------------------------------------------
    def _build_leaf(self, wizard):
        """Translate what the user typed in ``wizard`` into domain leaves."""
        self.ensure_one()
        fname = self.field_id.name
        main = self.wizard_field_id.name
        if not main or main not in wizard._fields:
            return []

        value = wizard[main]
        value_to = False
        if self.wizard_field_to_id and self.wizard_field_to_id.name in wizard._fields:
            value_to = wizard[self.wizard_field_to_id.name]

        shape = ops.shape_of(self.ttype, self.operator)

        if shape == 'bool':
            if not value:
                return []
            return [(fname, '=', value == 'yes')]

        if shape in ('m2o',):
            if not value:
                return []
            return [(fname, self.operator, value.id)]

        if shape == 'm2m':
            if not value:
                return []
            return [(fname, self.operator, value.ids)]

        if self.field_family == 'date':
            return self._date_leaves(fname, value, value_to)

        if self.field_family == 'number':
            if self.operator == 'between':
                low, high = value or 0.0, value_to or 0.0
                if not low and not high:
                    return []
                if high < low:
                    low, high = high, low
                return ['&', (fname, '>=', low), (fname, '<=', high)]
            if not value:
                return []
            return [(fname, self.operator, value)]

        # text, selection and display-name searches
        if not value:
            return []
        return [(fname, self.operator, value)]

    def _date_leaves(self, fname, value, value_to):
        self.ensure_one()
        start = end = None
        if self.operator == 'between':
            start, end = value, value_to
            if start and end and end < start:
                start, end = end, start
        elif self.operator == '=':
            start = end = value
        elif self.operator == '>=':
            start = value
        elif self.operator == '<=':
            end = value

        if not start and not end:
            return []

        if self.ttype == 'date':
            low = fields.Date.to_string(start) if start else None
            high = fields.Date.to_string(end) if end else None
        else:
            low = self._day_start_utc(start) if start else None
            high = self._day_end_utc(end) if end else None

        leaves = []
        if low:
            leaves.append((fname, '>=', low))
        if high:
            leaves.append((fname, '<=', high))
        return (['&'] + leaves) if len(leaves) == 2 else leaves

    def _tz(self):
        return pytz.timezone(self.env.context.get('tz') or self.env.user.tz or 'UTC')

    def _day_start_utc(self, day):
        naive = datetime.combine(day, time.min)
        return fields.Datetime.to_string(
            self._tz().localize(naive).astimezone(pytz.utc).replace(tzinfo=None))

    def _day_end_utc(self, day):
        naive = datetime.combine(day, time.max)
        return fields.Datetime.to_string(
            self._tz().localize(naive).astimezone(pytz.utc).replace(tzinfo=None))

    # ------------------------------------------------------------------
    # arch fragment rendered inside the generated popup view
    # ------------------------------------------------------------------
    def _field_options(self):
        self.ensure_one()
        shape = ops.shape_of(self.ttype, self.operator)
        attrs = []
        if shape == 'm2m':
            attrs.append('widget="many2many_tags"')
        if shape in ('m2o', 'm2m'):
            attrs.append("options=\"{'no_create': True, 'no_quick_create': True}\"")
        return ' '.join(attrs)

    def _arch_row(self):
        """One ``label + input`` row of the popup, as an XML string."""
        self.ensure_one()
        name = self.wizard_field_id.name
        if not name:
            return ''

        label = escape(self.display_label)
        options = self._field_options()

        if not self.wizard_field_to_id:
            placeholder = (' placeholder="%s"' % escape(self.placeholder)
                           if self.placeholder else '')
            return ('<field name="%s" string="%s"%s %s/>'
                    % (name, label, placeholder, options))

        # range placed on a single line: kept for a range that ends up outside
        # the dedicated from/to block
        return (
            '<label for="{main}" string="{label}"/>'
            '<div class="o_row">'
            '<field name="{main}" nolabel="1" placeholder="From" {opts}/>'
            '<span class="mx-2 text-muted">to</span>'
            '<field name="{second}" nolabel="1" placeholder="To" {opts}/>'
            '</div>'
        ).format(
            main=name,
            second=self.wizard_field_to_id.name,
            label=label,
            opts=options,
        )

    def _arch_range_from(self):
        """The lower bound of a range, for the left column of the popup."""
        self.ensure_one()
        if not self.wizard_field_id.name or not self.wizard_field_to_id:
            return ''
        return '<field name="%s" string="%s From" %s/>' % (
            self.wizard_field_id.name,
            escape(self.display_label),
            self._field_options(),
        )

    def _arch_range_to(self):
        """The upper bound of a range, for the right column of the popup."""
        self.ensure_one()
        if not self.wizard_field_to_id.name:
            return ''
        return '<field name="%s" string="%s To" %s/>' % (
            self.wizard_field_to_id.name,
            escape(self.display_label),
            self._field_options(),
        )

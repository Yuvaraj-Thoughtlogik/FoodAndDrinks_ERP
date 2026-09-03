"""Which fields the wizard is allowed to touch, and how each type is rendered.

Kept as plain module-level helpers so both the models and the views can agree
on one single definition of "configurable field".
"""

# Fields Odoo maintains itself - never offered for configuration.
MAGIC_FIELDS = (
    'id',
    'create_uid',
    'create_date',
    'write_uid',
    'write_date',
    'display_name',
    '__last_update',
)

# Technical types the wizard knows how to build a value for.
SUPPORTED_TTYPES = (
    'char',
    'text',
    'html',
    'integer',
    'float',
    'monetary',
    'boolean',
    'date',
    'datetime',
    'selection',
    'many2one',
    'many2many',
    'one2many',
    'binary',
    'reference',
)

# ttype -> the input the line should show. Several types share an input.
WIDGET_BY_TTYPE = {
    'char': 'char',
    'text': 'text',
    'html': 'text',
    'integer': 'integer',
    'float': 'float',
    'monetary': 'float',
    'boolean': 'boolean',
    'date': 'date',
    'datetime': 'datetime',
    'selection': 'selection',
    'many2one': 'reference',
    'reference': 'reference',
    'many2many': 'many2many',
    'one2many': 'one2many',
    'binary': 'binary',
}

# Types for which "leave it empty and let the wizard invent one" is meaningful.
RANDOMISABLE_TTYPES = (
    'char', 'text', 'html',
    'integer', 'float', 'monetary',
    'boolean', 'date', 'datetime',
    'selection', 'many2one', 'many2many', 'reference',
    'binary',
)

RELATIONAL_TTYPES = ('many2one', 'many2many', 'one2many', 'reference')

# x2many fields carry their values in a relation table or the inverse model
# rather than a column of their own, so the "has a column" test does not apply.
_X2MANY_TTYPES = ('one2many', 'many2many')


def is_computed_but_writable(field):
    """Is a computed field still something ``create()`` will accept?

    Two shapes qualify. A computed field with an ``inverse`` writes through
    it. A *stored* computed field left editable (``readonly=False``) is the
    modern replacement for an onchange - ``sale.order.line.product_uom_qty``
    is one - and takes a written value perfectly well.

    A computed field that is neither, such as
    ``sale.order.line.product_template_id``, has nowhere to put a value.
    """
    if not field.compute:
        return True
    return bool(field.inverse) or bool(field.store)


def needs_a_column(field):
    """Does writing this field require a column of its own to land in?

    x2many fields keep their values in a relation table or in the inverse
    model, and a computed field with an ``inverse`` writes through that
    inverse. Everything else needs to be stored.
    """
    if field.type in _X2MANY_TTYPES:
        return False
    if field.compute and field.inverse:
        return False
    return True


def is_configurable(field):
    """Can the wizard write ``field`` (an Odoo ``Field`` instance) on create?"""
    if field.name in MAGIC_FIELDS:
        return False
    if field.type not in SUPPORTED_TTYPES:
        return False
    if field.readonly:
        return False
    if field.related:
        return False
    if not is_computed_but_writable(field):
        return False
    if needs_a_column(field) and not field.store:
        return False
    if field.type == 'one2many' and not getattr(field, 'inverse_name', None):
        return False
    return True


def configurable_fields(model):
    """All configurable fields of ``model``, ordered by field label."""
    fields_ = [f for f in model._fields.values() if is_configurable(f)]
    return sorted(fields_, key=lambda f: (str(f.string or ''), f.name))


def required_fields(model):
    """Configurable fields that the model refuses to create without."""
    return [f for f in configurable_fields(model) if f.required]


def selection_options(model, field_name):
    """``[(value, label)]`` of a Selection field, whatever the origin.

    Handles the three ways a selection can be declared: a literal list, the
    name of a model method, or a callable.
    """
    field = model._fields.get(field_name)
    if field is None or field.type != 'selection':
        return []
    selection = getattr(field, 'selection', None)
    try:
        if callable(selection):
            selection = selection(model)
        elif isinstance(selection, str):
            selection = getattr(model, selection)()
        return [(value, str(label)) for value, label in (selection or [])]
    except Exception:  # a selection method that needs a real record
        return []


def unsupported_reason(field):
    """Human readable reason a field cannot be used, or ``None``."""
    if field.name in MAGIC_FIELDS:
        return "it is maintained by Odoo itself"
    if field.type not in SUPPORTED_TTYPES:
        return "the '%s' type is not supported by this wizard" % field.type
    if field.readonly:
        return "it is read-only"
    if field.related:
        return "it is a related field"
    if not is_computed_but_writable(field):
        return ("it is computed without being stored, so a written value "
                "would have nowhere to go")
    if needs_a_column(field) and not field.store:
        return "it is not stored"
    if field.type == 'one2many' and not getattr(field, 'inverse_name', None):
        return "it is a One2many with no inverse field"
    return None


def selectable_field_ids(env, model_name, excluded=(), skip_types=()):
    """``ir.model.fields`` ids of the fields the wizard can write on a model.

    Built from :func:`is_configurable` rather than from a domain on
    ``ir.model.fields``, because that table cannot express the rule: its
    ``compute`` column only holds code for *custom* fields, so a domain has no
    way to tell a Python computed field from a plain one. Feeding the Field
    dropdown from the same function that validates the choice is what keeps
    the two from disagreeing.
    """
    if not model_name:
        return []
    model = env.get(model_name)
    if model is None:
        return []
    names = [
        field.name for field in configurable_fields(model)
        if field.name not in excluded and field.type not in skip_types
    ]
    if not names:
        return []
    return env['ir.model.fields'].sudo().search([
        ('model', '=', model_name),
        ('name', 'in', names),
    ]).ids

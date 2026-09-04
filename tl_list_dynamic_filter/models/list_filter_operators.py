"""Operators offered by the dynamic filter, and how each one is rendered.

Every configured field is turned into a *real* field on the wizard model, so
the popup uses native Odoo widgets: a Many2one dropdown for a Many2one source,
a tags widget for "is one of", a date picker for a date, and so on.

``FIELD_SHAPE`` says which kind of wizard field an (family, operator) pair
needs:

    'same'   -> mirror the source field type (char, integer, float, date...)
    'char'   -> a plain text input (display-name search)
    'm2o'    -> Many2one to the source field's comodel
    'm2m'    -> Many2many to the source field's comodel
    'select' -> Selection mirroring the source field's own options
    'bool'   -> yes / no Selection (so "unset" still means "don't care")
"""

# --- operator catalogue ------------------------------------------------------
OPERATORS = [
    ('ilike', 'Contains'),
    ('not ilike', 'Does not contain'),
    ('=', 'Is equal to'),
    ('!=', 'Is not equal to'),
    ('>', 'Greater than'),
    ('>=', 'From'),
    ('<', 'Less than'),
    ('<=', 'Until'),
    ('between', 'Is between'),
    ('in', 'Is one of'),
    ('not in', 'Is none of'),
]

OPERATOR_LABELS = dict(OPERATORS)

#: operators needing a second input ("from ... to ...")
RANGE_OPERATORS = ('between',)

# --- field type families -----------------------------------------------------
TEXT_TYPES = ('char', 'text', 'html')
NUMBER_TYPES = ('integer', 'float', 'monetary')
DATE_TYPES = ('date', 'datetime')
BOOL_TYPES = ('boolean',)
SELECTION_TYPES = ('selection',)
RELATIONAL_TYPES = ('many2one', 'one2many', 'many2many')

#: Operators allowed per family; the first entry is the default.
ALLOWED_OPERATORS = {
    'text': ['ilike', 'not ilike', '=', '!='],
    'number': ['=', 'between', '!=', '>', '>=', '<', '<='],
    'date': ['between', '=', '>=', '<='],
    'boolean': ['='],
    'selection': ['=', '!='],
    'relational': ['in', '=', 'ilike', 'not in', '!='],
}

#: How the wizard field is built for each (family, operator).
FIELD_SHAPE = {
    ('text', 'ilike'): 'char',
    ('text', 'not ilike'): 'char',
    ('text', '='): 'char',
    ('text', '!='): 'char',

    ('number', '='): 'same',
    ('number', '!='): 'same',
    ('number', '>'): 'same',
    ('number', '>='): 'same',
    ('number', '<'): 'same',
    ('number', '<='): 'same',
    ('number', 'between'): 'same',

    ('date', '='): 'same',
    ('date', '>='): 'same',
    ('date', '<='): 'same',
    ('date', 'between'): 'same',

    ('boolean', '='): 'bool',

    ('selection', '='): 'select',
    ('selection', '!='): 'select',

    ('relational', 'in'): 'm2m',
    ('relational', 'not in'): 'm2m',
    ('relational', '='): 'm2o',
    ('relational', '!='): 'm2o',
    ('relational', 'ilike'): 'char',
}

#: field types the module refuses to expose
UNSUPPORTED_TYPES = (
    'binary', 'image', 'json', 'properties', 'properties_definition',
    'reference', 'many2one_reference',
)


def family_of(ttype):
    """Return the operator family for an ``ir.model.fields`` ttype."""
    if ttype in TEXT_TYPES:
        return 'text'
    if ttype in NUMBER_TYPES:
        return 'number'
    if ttype in DATE_TYPES:
        return 'date'
    if ttype in BOOL_TYPES:
        return 'boolean'
    if ttype in SELECTION_TYPES:
        return 'selection'
    if ttype in RELATIONAL_TYPES:
        return 'relational'
    return False


def allowed_operators(ttype):
    return ALLOWED_OPERATORS.get(family_of(ttype), [])


def default_operator(ttype):
    ops = allowed_operators(ttype)
    return ops[0] if ops else False


def operator_selection(ttype):
    """Selection list restricted to what makes sense for ``ttype``."""
    allowed = allowed_operators(ttype)
    return [(code, OPERATOR_LABELS[code]) for code in allowed]


def shape_of(ttype, operator):
    return FIELD_SHAPE.get((family_of(ttype), operator))


def needs_range(operator):
    return operator in RANGE_OPERATORS

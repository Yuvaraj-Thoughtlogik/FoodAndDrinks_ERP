"""Random value generation, one generator per technical field type.

Values are shaped to the field they are going into: a Char never overflows its
``size``, a Float honours the field's ``digits``, a Selection only ever gets
one of its own options, and a relational field only ever gets an id that
really exists in the related model.
"""

import base64
import random
import string
from datetime import date, datetime, timedelta

from . import demo_field_utils as futils

ADJECTIVES = (
    'Bright', 'Calm', 'Clever', 'Coastal', 'Crimson', 'Dapper', 'Eager',
    'Fabled', 'Gentle', 'Golden', 'Harbour', 'Ivory', 'Jolly', 'Keen',
    'Lucid', 'Mellow', 'Noble', 'Olive', 'Prime', 'Quiet', 'Rustic',
    'Silver', 'Swift', 'Tidal', 'Urban', 'Vivid', 'Warm', 'Zesty',
)

NOUNS = (
    'Anchor', 'Basket', 'Beacon', 'Cabin', 'Compass', 'Crate', 'Dock',
    'Ferry', 'Garden', 'Harbour', 'Island', 'Jetty', 'Kite', 'Lantern',
    'Market', 'Net', 'Orchard', 'Pallet', 'Quay', 'Reef', 'Sail',
    'Trawler', 'Vessel', 'Wharf', 'Yard',
)

WORDS = (
    'demo', 'sample', 'generated', 'record', 'batch', 'value', 'fixture',
    'placeholder', 'dataset', 'seeded', 'trial', 'draft', 'mock', 'test',
)

# Char fields whose name hints at a specific shape get a matching value.
_NAME_HINTS = (
    (('email', 'email_from', 'email_normalized'), 'email'),
    (('phone', 'mobile', 'phone_sanitized', 'fax'), 'phone'),
    (('website', 'url', 'website_url'), 'url'),
    (('zip', 'postcode', 'post_code'), 'zip'),
    (('vat', 'siret', 'company_registry'), 'vat'),
    (('color', 'colour'), 'colour'),
    (('code', 'ref', 'reference', 'barcode', 'default_code'), 'code'),
    (('city',), 'city'),
    (('street', 'street2'), 'street'),
    (('name', 'display_name', 'title', 'subject', 'label'), 'name'),
)

CITIES = ('Grimsby', 'Peterhead', 'Newlyn', 'Brixham', 'Fraserburgh',
          'Milford Haven', 'Whitby', 'Kilkeel')

STREETS = ('Quay Road', 'Harbour Way', 'Market Street', 'Dock Lane',
           'Pier Approach', 'Fish Dock Road')


def _token(length=6):
    alphabet = string.ascii_uppercase + string.digits
    return ''.join(random.choice(alphabet) for _ in range(length))


def _letters(length=2):
    return ''.join(random.choice(string.ascii_uppercase) for _ in range(length))


def _phrase():
    return '%s %s' % (random.choice(ADJECTIVES), random.choice(NOUNS))


def _hint_for(field_name):
    lowered = (field_name or '').lower()
    for names, hint in _NAME_HINTS:
        if lowered in names:
            return hint
    for names, hint in _NAME_HINTS:
        if any(part in lowered for part in names):
            return hint
    return None


def _clip(value, field):
    size = getattr(field, 'size', None)
    if size and len(value) > size:
        return value[:size]
    return value


def random_char(field):
    """A plausible short string, tailored to the field name where possible."""
    hint = _hint_for(field.name)
    if hint == 'email':
        value = '%s.%s@example.com' % (
            random.choice(WORDS), _token(4).lower())
    elif hint == 'phone':
        value = '+44 1%03d %06d' % (random.randint(0, 999),
                                    random.randint(0, 999999))
    elif hint == 'url':
        value = 'https://www.%s-%s.example.com' % (
            random.choice(WORDS), _token(3).lower())
    elif hint == 'zip':
        value = '%s%d %d%s' % (_letters(2), random.randint(1, 99),
                               random.randint(1, 9), _letters(2))
    elif hint == 'vat':
        value = 'GB%09d' % random.randint(0, 999999999)
    elif hint == 'colour':
        value = '#%06X' % random.randint(0, 0xFFFFFF)
    elif hint == 'code':
        value = '%s-%s' % (_token(3), random.randint(1000, 9999))
    elif hint == 'city':
        value = random.choice(CITIES)
    elif hint == 'street':
        value = '%d %s' % (random.randint(1, 250), random.choice(STREETS))
    elif hint == 'name':
        value = _phrase()
    else:
        value = '%s %s' % (_phrase(), _token(4))
    return _clip(value, field)


def random_text(field):
    sentences = [
        '%s %s generated for demonstration purposes.' % (
            random.choice(ADJECTIVES).lower(), random.choice(NOUNS).lower()),
        'Created by the Demo Record Creation Wizard on %s.' % date.today(),
        'Batch token %s.' % _token(8),
    ]
    random.shuffle(sentences)
    return _clip(' '.join(sentences), field)


def random_html(field):
    return '<p>%s</p>' % random_text(field)


def random_integer(field, low=1, high=999):
    if low > high:
        low, high = high, low
    return random.randint(low, high)


def random_float(field, low=1.0, high=999.0, whole_only=False):
    if low > high:
        low, high = high, low
    if whole_only:
        return float(random.randint(round(low), round(high)))
    digits = getattr(field, 'digits', None)
    precision = digits[1] if isinstance(digits, (tuple, list)) and len(digits) > 1 else 2
    return round(random.uniform(low, high), precision)


def random_boolean(field):
    return random.choice([True, False])


def random_date(low=None, high=None):
    if not low or not high:
        low, high = date.today() - timedelta(days=180), date.today() + timedelta(days=180)
    elif low > high:
        low, high = high, low
    span = (high - low).days
    return low + timedelta(days=random.randint(0, span) if span > 0 else 0)


def random_datetime(low=None, high=None):
    if not low or not high:
        low, high = datetime.now() - timedelta(days=180), datetime.now() + timedelta(days=180)
    elif low > high:
        low, high = high, low
    span_seconds = (high - low).total_seconds()
    offset = random.uniform(0, span_seconds) if span_seconds > 0 else 0
    return (low + timedelta(seconds=offset)).replace(second=0, microsecond=0)


def random_count(low, high):
    """A random integer count, clamped to zero or more."""
    low, high = max(low, 0), max(high, 0)
    if low > high:
        low, high = high, low
    return random.randint(low, high)


def random_selection(model, field_name):
    """One of the field's own options, or ``None`` when it has none."""
    options = futils.selection_options(model, field_name)
    if not options:
        return None
    return random.choice(options)[0]


def random_binary(field):
    payload = (
        'Demo Record Creation Wizard\r\n'
        'field: %s\r\n'
        'token: %s\r\n'
        'generated: %s\r\n'
    ) % (field.name, _token(12), datetime.now().isoformat(timespec='seconds'))
    return base64.b64encode(payload.encode('utf-8'))


def random_record_ids(env, comodel_name, count=1, domain=None):
    """``count`` ids picked at random from ``comodel_name``.

    ``domain`` narrows the pool - it is the domain typed on the line, so a
    Random value can be restricted to, say, only confirmed orders.

    Reads with ``sudo`` deliberately left off: if the user cannot see the
    related records, the wizard should say so rather than quietly linking
    records they have no access to.
    """
    comodel = env.get(comodel_name)
    if comodel is None:
        return []
    records = comodel.search(domain or [])
    if not records:
        return []
    count = max(1, min(count or 1, len(records)))
    return random.sample(records.ids, count)


def first_record_id(env, comodel_name, domain=None):
    """The id of the first record of ``comodel_name``, or ``None``.

    Used to seed a relational line with something concrete, so the model half
    of the record picker is filled in and only the record itself has to be
    chosen. Follows the model's own ``_order``, so "first" is what the user
    would see at the top of a list view.
    """
    comodel = env.get(comodel_name)
    if comodel is None:
        return None
    try:
        record = comodel.search(domain or [], limit=1)
    except Exception:
        return None
    return record.id or None


def random_reference_model(env, allowed_models=None):
    """A model name usable as the target of a Reference field.

    Takes no domain on purpose. A domain is written against one model and
    means nothing on the others, so a line that has one narrows itself to that
    model rather than asking for a model here - see
    ``_random_relational_value``.
    """
    candidates = list(allowed_models or [])
    if not candidates:
        models = env['ir.model'].sudo().search([('transient', '=', False)])
        candidates = models.mapped('model')
    random.shuffle(candidates)
    for model_name in candidates:
        comodel = env.get(model_name)
        if comodel is None:
            continue
        try:
            if comodel.search_count([], limit=1):
                return model_name
        except Exception:
            continue
    return None

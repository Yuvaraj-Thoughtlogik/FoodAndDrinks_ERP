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


def random_integer(field):
    return random.randint(1, 999)


def random_float(field):
    digits = getattr(field, 'digits', None)
    precision = digits[1] if isinstance(digits, (tuple, list)) and len(digits) > 1 else 2
    return round(random.uniform(1.0, 999.0), precision)


def random_boolean(field):
    return random.choice([True, False])


def random_date(field=None):
    return date.today() + timedelta(days=random.randint(-180, 180))


def random_datetime(field=None):
    base = datetime.now() + timedelta(days=random.randint(-180, 180))
    return base.replace(
        hour=random.randint(0, 23),
        minute=random.choice([0, 15, 30, 45]),
        second=0,
        microsecond=0,
    )


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


def random_reference_model(env, allowed_models=None):
    """A model name usable as the target of a Reference field."""
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

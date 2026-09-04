# Demo Record Creator

Generate demo records for **any** model in the database, with a value input
that adapts to each field's technical type.

Templates are **saved records**, not a throwaway wizard: name a configuration,
keep it, duplicate it, re-run it whenever you need more demo data.

*Odoo 19 · Thoughtlogik Technology Solutions · LGPL-3*

---

## Where to find it

**Settings → Technical → Demo Record Templates** (System Administrator only).

## How it works

1. **Pick a model.** The tables start empty - nothing is loaded on your behalf.
   Add the lines you want by hand, or press *Load Required Fields* / *Load All
   Fields* to pull them in and delete what you do not need.
2. **Click a line to configure it.** Each line is one field, and its dialog
   shows exactly the input that field's type calls for, full width - a date
   picker for a Date, a dropdown of the field's own options for a Selection, a
   searchable record selector for a Many2one, a checkbox for a Boolean. Every
   other input stays hidden, so there is one thing to fill in and no guessing
   which column belongs to which type.
3. **Configure One2many child records directly within the field.** When configuring
   a One2many field line, its child fields are configured directly within the
   field's configuration area using the same Field, Value, and Number of Values approach.
   That table starts empty too, with its own Load buttons; leave it empty and the
   One2many is left out of the values entirely.
4. **Set the number of records** and press *Create Records*. The created
   records open in a list view, and the template notes when it ran and how
   many it produced.
5. **Re-run or duplicate** it later. Duplicating copies every line, so one
   template can seed several variations.

### The Value cell and Random

**A value you enter always wins.** Set the value in the dialog and that value
is used; Random switches itself off as you type. Random only applies while the
value is empty, and then it generates a *fresh* value for every record in the
batch - a hundred records are a hundred different records, not a hundred
copies.

Integer, Decimal and Checkbox are the exception: `0` and an unticked box are
indistinguishable from "nothing entered", so for those three untick Random to
use the number or the tick you entered.

The tables themselves are read-only summaries - field, type, whether it is
random, and the value in words. All editing is in the dialogs, which is also
why the tables stay narrow enough to read.

### Relational lines: the model is chosen for you, and Random can be filtered

The record selector is a `fields.Reference`, which stores `'model,id'`. There
is no way to set the model half on its own and leave the record empty - the
value is either a whole record or nothing at all - so a Many2one line would
otherwise open asking which model to search, when the field already answers
that.

The line is therefore **seeded** with the first record of the comodel: the
picker opens on the right model, already searchable, and only the record has
to be changed.

**Seeding happens when the picker appears, and never over an existing value.**
That timing is the whole design. Seeding in `create` instead - so that lines
made by the Load buttons got a record too, since onchanges never run for
`(0, 0, vals)` commands - looked tidier and was wrong twice over. A value
nobody can see (the picker is hidden while Random is on) would become the
value written the moment Random was unticked, giving the record a row the user
never chose; and `create` cannot tell "never set" from "cleared on purpose",
so emptying the picker in a dialog and saving the parent would put the record
straight back. The triggers are therefore the two onchanges that mean "the
picker now matters": choosing the field, and unticking Random. Both skip a
line that will randomise, and both skip a line that already has a value.

A true Reference field has no single target, so it is seeded with the first
model the field *declares* that holds a matching record - first and not
random, because `domain_model` is derived from whatever lands there and the
domain editor is bound to it; a random model would re-point that editor under
the user on every re-seed. A Reference field that declares no models at all is
left alone: searching every model in the database to guess one would cost far
more than it is worth. The model is also checked against `fields.Reference`'s
own selection first, which excludes transient models - a configurable Many2one
can point at one, and assigning it raises a bare `ValueError` from inside the
ORM.

Relational lines also take a **Domain**, edited with Odoo's own domain editor.
It restricts the pool for a Many2one and a Many2many, and the seeded record
respects it too, so the pre-filled record and Random agree about what is in
scope. A record you go on to choose yourself is used as chosen; tighten the
domain past it and the picker is cleared rather than quietly swapped for
another record. For a true Reference field a domain written for one model
means nothing on the others, so once there is a domain only `domain_model` is
considered - otherwise a leaf that happens to exist on another model would
quietly match there, and with no model at all the unrestricted search would
scan every model in the database looking for one the domain happens to run
on. The model the domain applies to is named under the editor, because for a
Reference line it is otherwise invisible.

The domain is evaluated with `safe_eval`, so the usual vocabulary works -
`uid`, `today`, `now`, `company_id`, `datetime`, `ref('module.xmlid')`.
**Not `user`.** `safe_eval` blocks any name containing a dunder, which stops
the usual escapes, but handing over a full recordset is a way straight out:
`user.env.cr.execute(...)` needs no dunder, and calls are allowed. Core does
pass `user` into `ir.rule` domains - but only system administrators can write
those, and a domain box on a template is not the same thing.

Being a list is not enough either. `_check_domain_shape` rejects a bare leaf
written without its outer brackets, a two-part condition, a stray number, a
non-text field or operator, and an operator with nothing to apply it to
(`['&', cond]`) - all of which pass an `isinstance(list)` test and then fail
inside `search()` mid-run, which is exactly what checking at save time is
meant to prevent. Odoo's own `fields.Domain` is then given a look too, behind
an `ImportError` guard, because it knows which operators exist and a
hardcoded list here would reject the next one Odoo adds. It is belt and
braces, not the mechanism: the checks above stand on their own, so it quietly
doing nothing on a version without that class costs nothing.

What cannot be checked at save time is a field name the comodel does not
have. That surfaces from `search()` during the run, so `_random_ids` catches
it and names the line, the model and the domain instead of letting it arrive
as a generic "the values could not be generated". It reworders only failures
that are actually about the domain - an `AccessError` for a comodel the user
may not read keeps its own class and message, and so does a `psycopg2` error,
which the run's handler passes through so a deadlock can still be retried.

A domain that matches nothing is an error, not a silence. Everywhere else a
value that cannot be produced simply is not written, on the grounds that the
model knows better; a filter the user typed themselves returning no rows is
their own instruction failing, and saying so beats generating a hundred
records with the field empty.

Two smaller traps here take the *template form itself* down rather than merely
failing a run, since `value_display` is a column of the lines list:

- The domain editor writes the string `"[]"` when its last condition is
  removed. That is truthy and filters nothing, so `_has_domain()` tests for
  the empty spellings rather than trusting the text - and does it without
  evaluating anything, because it runs for every line on every re-render.
- Reading a `fields.Reference` is not safe. `convert_to_record` does
  `env[model].browse(id)` on the stored `'model,id'` text, so a deleted
  record yields a truthy recordset whose `display_name` raises
  `MissingError`, and a model whose module was uninstalled raises `KeyError`
  from the read itself. `reference_state()` and `reference_display()` wrap the
  read, the `exists()` and the `display_name`, and return
  `(target, broken)` so a caller can tell "nothing chosen" from "chosen and
  unusable" - the run reports the latter instead of writing a dangling id.

That last one has a limit worth knowing: the guards cover this addon's own
reads, but `value_reference` is declared in the row dialogs, so the ORM's
`_read_format` would still raise `KeyError` on a stale row before any of them
ran - leaving a line that cannot be opened to be fixed. Since a Reference is
stored as plain text that nothing cleans up on uninstall, `init()` sweeps it:
on every module update, raw SQL nulls any `'model,id'` naming a model that is
no longer in the registry. Raw SQL on purpose - the whole point is that those
values cannot be read through the ORM.

### "Required" is information, not a rule

A field's `required` flag is shown on the line and used to highlight the row,
and that is all it does. Nothing is pre-loaded because of it, and nothing is
blocked because of it.

The flag is simply not a reliable statement about what `create()` needs.
`sale.order.name` is required and comes from a sequence; `date_order` is
required and comes from a default; a stored computed field left editable is
required and computes itself. Demanding a value for those blocks
configurations that would have worked perfectly. So a blank line writes
nothing and lets the model do what it was going to do anyway.

What *is* checked before a run is the configuration's own consistency: a field
that belongs to another model, the same field configured twice, a record of the
wrong model chosen for a relation, an option a Selection does not have, a type
the creator cannot build a value for, create access on the target model, and
the run-size caps.

### When the model says no

Everything else is the model's verdict, delivered during the run. The batch
goes in inside one savepoint, so a refusal leaves nothing half-created, and the
message you get back carries:

- the model's own error text, verbatim - it names the field it is unhappy about;
- the values that were actually sent for the first record, field by field, with
  values the model supplied for itself counted rather than listed.

That is usually enough to go straight to the line that needs a value. Odoo's
own `UserError` and `ValidationError` come through the same path, so a Python
constraint reads the same way as a database one, and each keeps its own class
so the client still renders an access problem as an access problem.

A `required` field is a NOT NULL column, so a value that really was needed
arrives as a database constraint violation rather than a Python error. Raw
psycopg2 text is no way to report that - it appends a dump of the whole
failing row - so the four states a generated value can realistically hit
(not-null, unique, foreign key, check) are turned into a sentence naming the
model and the field, built from psycopg2's own public `exc.diag` rather than
from Odoo's private error formatter, whose signature has moved between
versions.

Three failures are passed through untouched instead, because rewriting them
would lose something: a `RedirectWarning` (its "go and fix it here" button
lives in the exception's own arguments), a serialisation failure or deadlock
(Odoo retries the request when it sees one), and any failure that happened
after the in-memory registry was already changed - a template targeting
`ir.model.fields` can do that, and only Odoo's request handler can reset it.

### One2many child record configuration

One2many field configurations do not require a separate page or tab on the template.
Instead, the child fields are embedded and configured directly inside the One2many field's
configuration area.

When selecting a One2many field:
- *Number of Values* determines how many child records to create per parent record.
- The child fields (e.g., lines for Sale Order) are displayed directly in the inline
  section of the field dialog.
- Child fields support the exact same Field, Value, and Number of Values configuration
  using `tl.demo.value.mixin`.

### Why a dialog rather than an editable table

A line carries one column per input shape - text, number, decimal, date,
datetime, option, record, file - because each type needs its own widget. Put
all of them in one editable table and it is thirteen columns wide with twelve
of them blank on any given row. The row dialog shows one input at a time
instead.

**Visibility is driven by `ttype`, never by a computed field.** That is not a
style preference. A computed field is only present in a record the client has
actually read *with that field in its spec*; a value group hidden behind a
`value_widget` the client never fetched renders completely empty. `ttype` is a
related field on `ir.model.fields` and is in every table's field list, so it
is always there.

The template and lines are saved models (`models.Model`), allowing dialogs to
reliably read back values, persist configurations, and support duplication.

## Input per field type

| Field type | Input shown | Random value when left blank |
| --- | --- | --- |
| Char | text input, clipped to the column size | name-aware string (email, phone, url, postcode, code, city, street) |
| Text | multiline text | a few generated sentences |
| Html | multiline text | the same, wrapped in `<p>` |
| Integer | integer input | 1 - 999 |
| Float / Monetary | decimal input, field's own precision | 1.00 - 999.00 |
| Boolean | checkbox | true or false |
| Date | date picker | today ± 180 days |
| Datetime | datetime picker | today ± 180 days, on a quarter hour |
| Selection | dropdown of the field's own options | one of those options |
| Many2one | record selector, model pre-filled from the field | a random record matching the line's Domain |
| Many2many | list of searchable record selectors | *Number of Values* random records matching the Domain |
| One2many | inline child field/value configuration | *Number of Values* child records per parent |
| Binary | file upload | a small generated text payload |
| Reference | record selector, seeded with a declared model | a random record of an allowed model, matching the Domain |

## Structure

```
models/
  demo_field_utils.py               which fields are usable, type -> input mapping
  demo_random.py                    one random generator per technical type
  demo_value_mixin.py               the typed value columns, validation and resolution
  demo_record_creator.py            the template: model, count, validation, run
  demo_record_creator_line.py       one configured field of the target model
  demo_record_creator_child_line.py one configured field of a One2many child
  demo_record_creator_ref.py        one explicitly chosen related record
views/
  demo_record_creator_views.xml     views for template, lines, child lines, and refs
  demo_record_creator_menus.xml     menu definition
security/
  ir.model.access.csv               model access rights
```

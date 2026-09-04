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

1. **Pick a model.** The template immediately loads every *required, writable*
   field of that model as a configuration line, so the shortest possible run is
   "choose model, choose count, Create Records".
2. **Click a line to configure it.** Each line is one field, and its dialog
   shows exactly the input that field's type calls for, full width - a date
   picker for a Date, a dropdown of the field's own options for a Selection, a
   searchable record selector for a Many2one, a checkbox for a Boolean. Every
   other input stays hidden, so there is one thing to fill in and no guessing
   which column belongs to which type.
3. **Configure One2many child records directly within the field.** When configuring
   a One2many field line, its child fields are configured directly within the
   field's configuration area using the same Field, Value, and Number of Values approach.
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
| Many2one | model + record selector, searchable | a random existing record |
| Many2many | list of searchable record selectors | *Number of Values* random records |
| One2many | inline child field/value configuration | *Number of Values* child records per parent |
| Binary | file upload | a small generated text payload |
| Reference | model selector, then record search | a random record of an allowed model |

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

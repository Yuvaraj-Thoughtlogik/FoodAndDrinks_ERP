# Generic List Dynamic Filter

Adds a configurable **filter button** to any list view. The popup is a normal
Odoo form — `Label   [ input ]` rows in one or two columns — generated from the
fields you list on the configuration record, exactly like a hand-written wizard.

```
Filter Batch                                     ✕
──────────────────────────────────────────────────
  Round Code      [ 0001                     ▾ ]
  Round Batches   [ 000004 ×                   ]
  Delivery Date   [ 03/09/2026                 ]
──────────────────────────────────────────────────
  [ Apply ]  [ Clear ]  [ Cancel ]
```

## How the popup gets native widgets

Every configured field materialises a **real manual field** on the wizard model
(`x_flt_<line id>`), and each configuration owns a generated primary form view
plus its own action. So the dialog is a plain Odoo form:

* a Many2one source field → a real **dropdown of that model's records**
* `Is one of` → a **tags input** (Many2many to the same comodel)
* a Selection source field → a **dropdown of that field's own options**
* `Is between` → **two date/number pickers** on one row
* a Boolean → a **Yes / No dropdown**, so "unset" still means *don't care*

No javascript, no custom widgets, no view-cache tricks — the arch is static per
configuration, written to `ir.ui.view` when you save.

## The condition drives the widget

The **Condition** you pick per field decides both how the value is matched and
what the user sees:

| Field type | Conditions | Input rendered |
| --- | --- | --- |
| Char / Text / Html | Contains, Does not contain, Is equal to, Is not equal to | text |
| Integer / Float / Monetary | Is equal to, Is between, ≠, >, ≥, <, ≤ | number (two for *between*) |
| Date / Datetime | Is between, Is equal to, From, Until | date picker (two for *between*) |
| Boolean | Is equal to | Yes / No dropdown |
| Selection | Is equal to, Is not equal to | dropdown of the field's options |
| Many2one / One2many / Many2many | Is one of, Is equal to, Contains, Is none of, ≠ | tags, dropdown, or text |

Datetime fields are filtered by **date**, and the user's timezone is converted
to UTC before comparison — the original module compared naive local dates to
UTC-stored datetimes, which shifted results by the timezone offset.

Blank inputs are skipped, so the popup behaves like a search form: fill in what
you care about, leave the rest empty.

## Configure

Settings → Technical → Automation → **List Dynamic Filters**

| Field | Meaning |
| --- | --- |
| Button Name | label of the button on the list view |
| Model | model to filter |
| List View | optional; the model's default list view is used when empty |
| Extra Domain | always ANDed with what the user enters |
| Popup Title / Apply Button | dialog wording |
| Open Results In | same window or new window |

Then add the **Filter Fields**: field, label and condition. They are rendered
as a single column of `label + input` lines, in the order of the list.
`Preview Popup` opens the dialog as users will see it.

Date and datetime inputs open on **today** — both ends of a `Is between` range —
so the popup is usable straight away. `Clear` resets them to today rather than
emptying them.

Saving generates four things: the manual wizard fields, the popup form view,
the popup action, and an inherited list view that injects the button into the
list header (creating the header if the view has none).

## What changed vs. the date-only version

| Area | Before | Now |
| --- | --- | --- |
| Fields | one `date_field_id` | any number, any type |
| Popup | two hard-coded dates, one of them `invisible="1"` | generated form, one row per field |
| Widgets | date inputs only | native dropdowns, tags, dates, numbers |
| Timezone | naive local date vs. UTC datetime | converted through the user's timezone |
| Recursion | `write()` always regenerated the view | guarded, only on relevant changes |
| Header detection | found its own `<header>` on the 2nd save and broke the xpath | own view is disabled while probing |
| Missing view | crashed when `view_id` was empty | falls back to the default list view |
| Button label | injected raw into the arch | XML-escaped |
| Manifest | duplicate `version` key | fixed |

## Upgrade

The module is named `tl_list_dynamic_filter`. Odoo treats a renamed folder as a
**different module**, so an existing `tl_list_date_filter` installation will not
upgrade into it on its own. Two options:

* **Fresh install** — uninstall `tl_list_date_filter` (which removes its
  configurations and generated views), then install this one. Simplest.
* **Keep the data** — rename the module record before updating:

  ```sql
  UPDATE ir_module_module   SET name = 'tl_list_dynamic_filter'
   WHERE name = 'tl_list_date_filter';
  UPDATE ir_model_data      SET module = 'tl_list_dynamic_filter'
   WHERE module = 'tl_list_date_filter';
  ```

  then restart with `-u tl_list_dynamic_filter`. The bundled migrations then run:

  * `19.0.2.0.0` converts each old `date_field_id` into a filter field with the
    `Is between` condition and rebuilds every button;
  * `19.0.2.1.0` drops the short-lived condition-grid models
    (`list.filter.wizard.line`, `list.filter.field.option`) and regenerates the
    form popups.

The generated arch is a standard `form > sheet > group` skeleton with the group
named `filter_fields`, which is what Studio expects to drop widgets into and
what any inheriting view can anchor an xpath on.

## Designing the popup by hand (optional)

The generated layout is deliberately plain: one field per line, in order. If you
want full control -- sections, columns, notebooks, custom widgets -- install the
bridge module from **Settings → List Dynamic Filters → Design with Studio**,
which is the `module_tl_list_dynamic_filter_studio` checkbox.

Once installed, each configuration gains two buttons:

* **Design with Studio** — marks the configuration as Studio designed (from
  then on the layout is never regenerated) and opens its popup **as a full
  page**, so you can click the Studio icon in the top bar and edit exactly that
  view. Studio's editor is registered in javascript and its entry point differs
  between versions, so the module deliberately does not call into it. If your
  build does expose a client action that opens the Studio *view editor*, put
  its tag in the system parameter `tl_list_dynamic_filter.studio_action_tag`
  and it will be used instead.
* **Reset Design** — removes the Studio layers and hands the popup back to the
  generator.

While a configuration is Studio designed, changing *which* fields it exposes
(adding, removing, or changing a Condition) is refused with a clear message,
because that would require rewriting the arch Studio owns. Renaming a label is
still fine. Reset the design, change the fields, and design again.

The bridge is a separate addon so the base module keeps depending only on
Community modules; Studio is an Enterprise feature.

## Models

| Model | Purpose |
| --- | --- |
| `list.filter.configuration` | one button on one list view |
| `list.filter.config.field` | one row of the popup, and the generated field(s) behind it |
| `list.filter.wizard` | the popup; carries `config_id` plus the generated `x_flt_*` fields |

Modules:

| Module | Purpose |
| --- | --- |
| `tl_list_dynamic_filter` | the filter itself (Community only) |
| `tl_list_dynamic_filter_studio` | optional Studio bridge, installed from Settings |

## Notes

* All configurations share the `list.filter.wizard` table, so each configured
  field adds a column there. That is fine for normal use; if you plan to expose
  many hundreds of fields across many configurations, keep Postgres' 1600-column
  limit in mind.
* Deleting a configuration removes its generated fields, views and action.

{
    'name': 'Demo Record Creator',
    'version': '19.0.5.0.0',
    'summary': 'Saved, re-runnable templates that create demo records for any model',
    'description': """
Demo Record Creator
===================

Model-agnostic templates that generate records for any model in the database.

* Pick a model, pick how many records you want, press Create Records.
* Templates are saved records, so a configuration can be named, kept,
  duplicated and re-run whenever more demo data is needed.
* Nothing is loaded for you. Add the fields you want to control, or use
  *Load Required Fields* / *Load All Fields* to pull them in, and remove any
  line you do not need. The same is true of a One2many's child fields: they
  are loaded only when you ask for them inside the line.
* Each line renders the *native* Odoo input for the selected field's technical
  type - no single generic text box:

  ===============================  ==========================================
  Field type                       Input
  ===============================  ==========================================
  Char / Text / Html               text input
  Integer                          integer input
  Float / Monetary                 decimal input
  Boolean                          checkbox
  Date                             date picker
  Datetime                         datetime picker
  Selection                        dropdown of the field's own options
  Many2one                         searchable record selector
  Many2many                        list of searchable record selectors
  One2many                         inline child field/value configuration
  Binary                           file upload
  Reference                        model selector + searchable record selector
  ===============================  ==========================================

* Click a line and its dialog shows exactly the input that field's type calls
  for, full width, with every other input hidden. A value you enter always
  wins over Random.
* Leave a value empty and tick *Random* to let the creator invent a sensible
  value for that type, freshly generated for every record: random text sized
  to the column, random numbers, random dates, a random option of a Selection,
  a random existing record for a relation.
* Relational lines pick their own model. Untick Random on a Many2one or
  Reference line and the record selector is already pointing at the right
  model, with its first record filled in, so only the record itself has to be
  changed. Empty the selector and it stays empty.
* Relational lines also take a **Domain**, edited with Odoo's own domain
  editor, restricting the records the line may draw on - both the ones Random
  picks and the one filled in for you. A Many2one can be filled from confirmed
  orders only, or a Many2many from active partners.
* One2many relations are configured directly within the field configuration area
  (inline without separate pages or tabs), with child records using the same
  Field, Value, and Number of Values approach.
* A field's *Required* flag is shown for information but never enforced here.
  Plenty of required fields are filled in by the model itself
  (``sale.order.name`` comes from a sequence), so a blank line writes nothing
  and lets the model decide.
* Only the configuration itself is checked before the run - types, Selection
  options, relational models, duplicate lines, access rights. Everything else
  is the model's verdict: the batch runs in a single transaction, and if the
  model refuses, its own message is shown together with the values that were
  sent, so the line to fix is obvious. A failure leaves nothing half-created.
* Each template records when it last ran and how many records it produced.
    """,
    'author': "Thoughtlogik Technology Solutions",
    'website': "https://thoughtlogik.com/",
    'category': 'Tools',
    'license': 'LGPL-3',
    'depends': [
        'base',
        'web',
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/demo_record_creator_views.xml',
        'views/demo_record_creator_menus.xml',
    ],
    'installable': True,
    'application': False,
}

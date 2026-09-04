{
    'name': 'Demo Record Creator',
    'version': '19.0.3.0.0',
    'summary': 'Saved, re-runnable templates that create demo records for any model',
    'description': """
Demo Record Creator
===================

Model-agnostic templates that generate records for any model in the database.

* Pick a model, pick how many records you want, press Create Records.
* Templates are saved records, so a configuration can be named, kept,
  duplicated and re-run whenever more demo data is needed.
* The required fields of the model are loaded automatically as configuration
  lines; add or remove any other writable field.
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
* One2many relations are configured directly within the field configuration area
  (inline without separate pages or tabs), with child records using the same
  Field, Value, and Number of Values approach.
* Everything is validated before the first record is written - types,
  Selection options, relational models, required fields, access rights - and
  the whole batch runs in a single transaction, so a failure leaves nothing
  half-created.
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

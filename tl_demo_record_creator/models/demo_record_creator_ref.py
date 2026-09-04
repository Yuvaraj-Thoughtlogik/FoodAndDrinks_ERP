"""One explicitly chosen record for a Many2many field."""

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class DemoRecordCreatorRef(models.Model):
    _name = 'tl.demo.record.creator.ref'
    _description = 'Demo Record Selected Record'
    _order = 'field_id, sequence, id'

    sequence = fields.Integer(default=10)

    creator_id = fields.Many2one(
        'tl.demo.record.creator',
        string="Template",
        required=True,
        ondelete='cascade',
        index=True,
    )
    field_id = fields.Many2one(
        'ir.model.fields',
        string="Field",
        required=True,
        ondelete='cascade',
        help="The Many2many field this record is linked to.")
    comodel_name = fields.Char(
        related='field_id.relation', string="Expected Model", readonly=True)

    record_ref = fields.Reference(
        selection='_selection_reference_models',
        string="Record",
        required=True,
        help="Pick the model the field points at, then search the record.")

    @api.model
    def _selection_reference_models(self):
        models_ = self.env['ir.model'].sudo().search(
            [('transient', '=', False)], order='name')
        return [(m.model, m.name) for m in models_]

    @api.constrains('record_ref', 'field_id')
    def _check_record_model(self):
        for ref in self:
            record = ref.record_ref
            expected = ref.comodel_name
            if not record or not expected:
                continue
            if record._name != expected:
                raise ValidationError(
                    _("'%(field)s' only accepts %(expected)s records, but "
                      "%(got)s was selected.",
                      field=ref.field_id.field_description or ref.field_id.name,
                      expected=expected, got=record._name))

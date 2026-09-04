"""Field/value configuration for the child records of a One2many field.

Owned directly by the One2many field configuration line.
"""

from odoo import api, fields, models


class DemoRecordCreatorChildLine(models.Model):
    _name = 'tl.demo.record.creator.child.line'
    _inherit = ['tl.demo.value.mixin']
    _description = 'Demo Record Child Field Configuration'
    _order = 'sequence, id'

    line_id = fields.Many2one(
        'tl.demo.record.creator.line',
        string="Parent Line",
        required=True,
        ondelete='cascade',
        index=True,
    )
    parent_field_id = fields.Many2one(
        'ir.model.fields',
        related='line_id.field_id',
        string="One2many Field",
        store=True,
        readonly=True,
        help="The One2many field whose child records this line configures.")

    creator_id = fields.Many2one(
        'tl.demo.record.creator',
        related='line_id.creator_id',
        string="Template",
        store=True,
        readonly=True,
    )

    model_id = fields.Many2one(
        'ir.model', string="Child Model",
        compute='_compute_parent_context',
        help="Model the child records are created in.")
    inverse_name = fields.Char(
        compute='_compute_parent_context',
        help="Field pointing back at the parent record. Odoo fills it in, so "
             "it is never offered for configuration.")

    @api.depends('line_id.relation', 'line_id.field_id')
    def _compute_parent_context(self):
        IrModel = self.env['ir.model']
        for child in self:
            comodel = inverse = False
            line = child.line_id
            if line and line.relation:
                comodel = IrModel.sudo().search([('model', '=', line.relation)], limit=1)
                inverse = line._child_inverse_name()
            child.model_id = comodel.id if comodel else False
            child.inverse_name = inverse or False

    def _creator(self):
        self.ensure_one()
        if self.creator_id:
            return self.creator_id
        if self.line_id and self.line_id.creator_id:
            return self.line_id.creator_id
        return self.env['tl.demo.record.creator']

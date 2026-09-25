from odoo import api, fields, models, _

class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    requirement_line_ids = fields.One2many(
        'requirement.report.line',
        'purchase_order_id',
        string='Requirement Lines'
    )
    requirement_line_count = fields.Integer(
        string='Requirement Count',
        compute='_compute_requirement_line_count'
    )

    @api.depends('requirement_line_ids')
    def _compute_requirement_line_count(self):
        for order in self:
            order.requirement_line_count = len(order.requirement_line_ids)

    def action_view_requirement_lines(self):
        """Smart button action on Purchase Order to view linked Requirement Lines."""
        self.ensure_one()
        return {
            'name': _('Requirement Lines'),
            'type': 'ir.actions.act_window',
            'res_model': 'requirement.report.line',
            'view_mode': 'list,form',
            'domain': [('purchase_order_id', '=', self.id)],
            'context': {'default_purchase_order_id': self.id},
            'target': 'current',
        }

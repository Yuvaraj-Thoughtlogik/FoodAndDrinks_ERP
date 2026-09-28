from odoo import api, fields, models, _

class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    requirement_line_count = fields.Integer(
        string='Requirement Count',
        compute='_compute_requirement_line_count'
    )

    def _requirement_line_domain(self):
        # A requirement line can be spread over several POs (a balance ordered
        # after the first PO was confirmed), so match through its PO lines.
        return [('purchase_line_ids.order_id', 'in', self.ids)]

    @api.depends('order_line')
    def _compute_requirement_line_count(self):
        Line = self.env['requirement.report.line']
        for order in self:
            order.requirement_line_count = Line.search_count(order._requirement_line_domain()) if order.id else 0

    def action_view_requirement_lines(self):
        """Smart button action on Purchase Order to view linked Requirement Lines."""
        self.ensure_one()
        return {
            'name': _('Requirement Lines'),
            'type': 'ir.actions.act_window',
            'res_model': 'requirement.report.line',
            'view_mode': 'list,form',
            'domain': self._requirement_line_domain(),
            'target': 'current',
        }

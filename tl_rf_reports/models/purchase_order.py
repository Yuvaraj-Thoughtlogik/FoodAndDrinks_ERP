from odoo import api, fields, models, _

class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    prediction_line_ids = fields.One2many(
        'prediction.report.line',
        'purchase_order_id',
        string='Prediction Lines'
    )
    prediction_line_count = fields.Integer(
        string='Prediction Count',
        compute='_compute_prediction_line_count'
    )

    @api.depends('prediction_line_ids')
    def _compute_prediction_line_count(self):
        for order in self:
            order.prediction_line_count = len(order.prediction_line_ids)

    def action_view_prediction_lines(self):
        """Smart button action on Purchase Order to view linked Prediction Lines."""
        self.ensure_one()
        return {
            'name': _('Prediction Lines'),
            'type': 'ir.actions.act_window',
            'res_model': 'prediction.report.line',
            'view_mode': 'list,form',
            'domain': [('purchase_order_id', '=', self.id)],
            'context': {'default_purchase_order_id': self.id},
            'target': 'current',
        }


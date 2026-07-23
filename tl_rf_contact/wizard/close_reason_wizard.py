from odoo import api, fields, models


class CloseReasonWizard(models.TransientModel):
    _name = 'close.reason.wizard'
    _description = 'Close Reason Wizard'

    partner_ids = fields.Many2many(
        'res.partner',
        string='Customers',
        required=True,
        default=lambda self: [
            (6, 0, self.env.context.get(
                'active_ids',
                [self.env.context.get('active_id')]
                if self.env.context.get('active_id')
                else []
            ))
        ],
    )

    reason = fields.Text(
        string='Reason',
        required=True,
    )

    def confirm(self):
        self.partner_ids.write({
            'is_closed': True,
            'is_reopened': False,
            'account_reopen_date': False,
            'closed_reason': self.reason,
            'customer_lifecycle_status': 'closed',
            'account_closed_date': fields.Datetime.now(),
        })
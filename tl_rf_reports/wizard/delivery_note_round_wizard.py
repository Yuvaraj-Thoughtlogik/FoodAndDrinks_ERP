# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class DeliveryNoteRoundWizard(models.TransientModel):
    _name = 'delivery.note.round.wizard'
    _description = 'Delivery Note Round Report Wizard'

    delivery_channel = fields.Selection(
        selection=[
            ('regal_van', 'Regal Van Delivery'),
            ('courier', 'Courier Delivery'),
        ],
        string='Delivery Channel',
        required=True,
        default='courier',
        help="Select delivery channel for the delivery note report."
    )
    delivery_date_from = fields.Date(
        string='Deliver From',
        required=True,
        default=fields.Date.context_today,
        help="Starting delivery date for delivery note selection."
    )
    delivery_date_to = fields.Date(
        string='Deliver To',
        required=True,
        default=fields.Date.context_today,
        help="Ending delivery date for delivery note selection."
    )

    @api.constrains('delivery_date_from', 'delivery_date_to')
    def _check_dates(self):
        for record in self:
            if record.delivery_date_from and record.delivery_date_to and record.delivery_date_to < record.delivery_date_from:
                raise ValidationError(_("Deliver To date cannot be earlier than Deliver From date."))

    def action_print_report(self):
        """Lightning-fast validation using search_count before triggering report."""
        self.ensure_one()

        if self.delivery_channel == 'courier':
            order_count = self.env['sale.order'].search_count([
                ('delivery_channel', '=', 'courier'),
                ('state', 'in', ['sale', 'done']),
                ('delivery_date', '>=', self.delivery_date_from),
                ('delivery_date', '<=', self.delivery_date_to),
            ])
            if not order_count:
                raise UserError(_(
                    "No confirmed Courier Delivery orders found between %s and %s."
                ) % (
                    self.delivery_date_from.strftime('%d/%m/%Y'),
                    self.delivery_date_to.strftime('%d/%m/%Y'),
                ))
            return self.env.ref('tl_rf_reports.action_report_delivery_note_round_courier').report_action(self)

        # Handle Regal Van Delivery
        batch_count = self.env['round.management.batch'].search_count([
            ('delivery_date', '>=', self.delivery_date_from),
            ('delivery_date', '<=', self.delivery_date_to),
        ])
        if not batch_count:
            raise UserError(_(
                "No batches found with delivery dates between %s and %s."
            ) % (
                self.delivery_date_from.strftime('%d/%m/%Y'),
                self.delivery_date_to.strftime('%d/%m/%Y'),
            ))

        return self.env.ref('tl_rf_reports.action_report_delivery_note_round_van').report_action(self)

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
        default='regal_van',
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
                raise ValidationError(_("Deliver To cannot be earlier than Deliver From."))

    def action_print_report(self):
        """Validates batches or orders for the selected delivery channel and triggers the Delivery Note Round Report."""
        self.ensure_one()

        if self.delivery_channel == 'courier':
            order_domain = [
                ('delivery_channel', '=', 'courier'),
                ('state', 'in', ['sale', 'done']),
                ('delivery_date', '>=', self.delivery_date_from),
                ('delivery_date', '<=', self.delivery_date_to),
            ]
            matching_orders = self.env['sale.order'].search(order_domain)
            if not matching_orders:
                raise UserError(_(
                    "No confirmed Courier Delivery orders found with delivery dates between %s and %s."
                ) % (
                    self.delivery_date_from.strftime('%d/%m/%Y'),
                    self.delivery_date_to.strftime('%d/%m/%Y'),
                ))
            return self.env.ref('tl_rf_reports.action_report_delivery_note_round_courier').report_action(self)

        # Regal Van Delivery
        domain = [
            ('delivery_date', '>=', self.delivery_date_from),
            ('delivery_date', '<=', self.delivery_date_to),
        ]

        batches = self.env['round.management.batch'].search(domain)
        if not batches:
            raise UserError(_(
                "No batches found with delivery dates between %s and %s."
            ) % (
                self.delivery_date_from.strftime('%d/%m/%Y'),
                self.delivery_date_to.strftime('%d/%m/%Y'),
            ))

        # Check if batches contain matching Regal Van Delivery orders
        eligible_orders = batches.mapped('order_ids').filtered(
            lambda so: so.state in ('sale', 'done') and getattr(so, 'delivery_channel', False) in ('regal_van', False)
        )

        if not eligible_orders:
            raise UserError(_(
                "Eligible batches were found, but they do not contain any matching Regal Van Delivery sale orders within the selected criteria."
            ))

        return self.env.ref('tl_rf_reports.action_report_delivery_note_round_van').report_action(self)
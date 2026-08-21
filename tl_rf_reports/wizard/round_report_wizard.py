# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class BatchReportWizard(models.TransientModel):
    _name = 'batch.report.wizard'
    _description = 'Dock Weight Breakdown Report Wizard'

    delivery_date_from = fields.Date(
        string='Delivery Date From',
        required=True,
        default=fields.Date.context_today,
        help="Starting delivery date for batch selection."
    )
    delivery_date_to = fields.Date(
        string='Delivery Date To',
        required=True,
        default=fields.Date.context_today,
        help="Ending delivery date for batch selection."
    )
    depot_ids = fields.Many2many(
        'stock.warehouse',
        'batch_report_wizard_warehouse_rel',
        'wizard_id',
        'warehouse_id',
        string='Depot',
        help="Select one or more depots. Leave unselected to include all depots."
    )
    include_late_orders = fields.Boolean(
        string='Late Order',
        default=False,
        help="When checked, Late Sale Orders are included in the report alongside normal orders."
    )

    # Legacy / alias compatibility
    start_date = fields.Date(
        related='delivery_date_from',
        readonly=False,
        string='Start Date'
    )
    end_date = fields.Date(
        related='delivery_date_to',
        readonly=False,
        string='End Date'
    )

    @api.constrains('delivery_date_from', 'delivery_date_to')
    def _check_dates(self):
        for record in self:
            if record.delivery_date_from and record.delivery_date_to and record.delivery_date_to < record.delivery_date_from:
                raise ValidationError(_("Delivery Date To cannot be earlier than Delivery Date From."))

    def action_print_report(self):
        """Validates eligible batches and triggers the Dock Weight Breakdown Report."""
        self.ensure_one()

        # Build domain to verify eligible batches
        domain = [
            ('delivery_date', '>=', self.delivery_date_from),
            ('delivery_date', '<=', self.delivery_date_to),
        ]
        if self.depot_ids:
            domain.append(('depot_id', 'in', self.depot_ids.ids))

        batches = self.env['round.management.batch'].search(domain)
        if not batches:
            depot_names = ", ".join(self.depot_ids.mapped('name')) if self.depot_ids else ""
            depot_label = f" for depot(s) '{depot_names}'" if depot_names else ""
            raise UserError(_(
                "No batches found with delivery dates between %s and %s%s."
            ) % (
                self.delivery_date_from.strftime('%d/%m/%Y'),
                self.delivery_date_to.strftime('%d/%m/%Y'),
                depot_label
            ))

        # Check if batches have linked sale orders
        eligible_orders = batches.mapped('order_ids').filtered(lambda so: so.state != 'cancel')
        if not self.include_late_orders:
            eligible_orders = eligible_orders.filtered(lambda so: not getattr(so, 'is_late_order', False))

        if not eligible_orders:
            raise UserError(_("Eligible batches were found, but they do not contain any matching sale orders."))

        return self.env.ref('tl_rf_reports.action_report_dock_weight_breakdown').report_action(self)

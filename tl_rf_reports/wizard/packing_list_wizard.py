# -*- coding: utf-8 -*-
from datetime import timedelta
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class PackingListWizard(models.TransientModel):
    _name = 'packing.list.wizard'
    _description = 'Packing List Report Wizard'

    driver_packing_list = fields.Boolean(
        string='Driver Packing List',
        default=False,
        help="When checked, generates the Driver Packing List report. This report is always "
             "restricted to Regal Van Delivery, filtered only by Delivery Date and Depot. "
             "The Late Order option is hidden and not used to filter this report, and the "
             "Delivery Channel is locked to Regal Van Delivery."
    )
    delivery_channel = fields.Selection(
        selection=[
            ('regal_van', 'Regal Van Delivery'),
            ('courier', 'Courier Delivery'),
        ],
        string='Delivery Channel',
        required=True,
        default='regal_van',
        help="Select delivery channel for the packing list report."
    )

    def _default_packing_date(self):
        return fields.Date.context_today(self) - timedelta(days=1)

    delivery_date_from = fields.Date(
        string='Delivery Date From',
        required=True,
        default=fields.Date.context_today,
        help="Starting delivery date for packing list selection."
    )
    delivery_date_to = fields.Date(
        string='Delivery Date To',
        required=True,
        default=fields.Date.context_today,
        help="Ending delivery date for packing list selection."
    )
    packing_date_from = fields.Date(
        string='Packing Date From',
        default=_default_packing_date,
        help="Starting packing date for packing list selection."
    )
    packing_date_to = fields.Date(
        string='Packing Date To',
        default=_default_packing_date,
        help="Ending packing date for packing list selection."
    )

    @api.model
    def _default_depot_ids(self):
        return self.env['stock.warehouse'].search([])

    depot_ids = fields.Many2many(
        'stock.warehouse',
        'packing_list_wizard_warehouse_rel',
        'wizard_id',
        'warehouse_id',
        string='Depot',
        default=_default_depot_ids,
        help="Select one or more depots. Leave unselected to include all depots."
    )
    include_late_orders = fields.Boolean(
        string='Late Order',
        default=False,
        help="When unchecked, normal Packing List is generated. When checked, separate Late Order Packing List is generated."
    )

    @api.onchange('driver_packing_list')
    def _onchange_driver_packing_list(self):
        """Driver Packing List only ever applies to Regal Van Delivery and does not
        distinguish Late Orders, so lock/hide those fields as soon as it's enabled."""
        if self.driver_packing_list:
            self.delivery_channel = 'regal_van'
            self.include_late_orders = False

    @api.onchange('delivery_date_from')
    def _onchange_delivery_date_from(self):
        if self.delivery_date_from:
            self.packing_date_from = self.delivery_date_from - timedelta(days=1)

    @api.onchange('delivery_date_to')
    def _onchange_delivery_date_to(self):
        if self.delivery_date_to:
            self.packing_date_to = self.delivery_date_to - timedelta(days=1)

    @api.onchange('packing_date_from')
    def _onchange_packing_date_from(self):
        if self.packing_date_from:
            self.delivery_date_from = self.packing_date_from + timedelta(days=1)

    @api.onchange('packing_date_to')
    def _onchange_packing_date_to(self):
        if self.packing_date_to:
            self.delivery_date_to = self.packing_date_to + timedelta(days=1)

    @api.constrains('delivery_date_from', 'delivery_date_to')
    def _check_delivery_dates(self):
        for record in self:
            if record.delivery_date_from and record.delivery_date_to and record.delivery_date_to < record.delivery_date_from:
                raise ValidationError(_("Delivery Date To cannot be earlier than Delivery Date From."))

    @api.constrains('packing_date_from', 'packing_date_to')
    def _check_packing_dates(self):
        for record in self:
            if record.packing_date_from and record.packing_date_to and record.packing_date_to < record.packing_date_from:
                raise ValidationError(_("Packing Date To cannot be earlier than Packing Date From."))

    def _wizard_vals(self):
        return {
            'driver_packing_list': self.driver_packing_list,
            'delivery_channel': self.delivery_channel,
            'delivery_date_from': self.delivery_date_from,
            'delivery_date_to': self.delivery_date_to,
            'packing_date_from': self.packing_date_from,
            'packing_date_to': self.packing_date_to,
            'depot_ids': [(6, 0, self.depot_ids.ids)],
            'include_late_orders': self.include_late_orders,
        }

    def action_print_report(self):
        """Validates eligible batches or courier orders and triggers the Packing List Report.

        For a large number of records, rendering the PDF (thousands of
        wkhtmltopdf pages) can take many minutes - too long to hold open the
        HTTP request that triggered the Print button. Past a configurable
        threshold (tl.report.generation.job._get_async_threshold), the report
        is instead generated in the background and the user is notified with
        a Download button once it's ready, so the click always returns
        immediately."""
        self.ensure_one()

        # Defensive: Driver Packing List is always Regal Van Delivery, regardless of what
        # was stored on the record (UI already enforces this via onchange + readonly).
        if self.driver_packing_list and self.delivery_channel != 'regal_van':
            self.delivery_channel = 'regal_van'

        if self.driver_packing_list:
            return self._action_print_driver_packing_list()

        job_model = self.env['tl.report.generation.job']

        if self.delivery_channel == 'courier':
            order_domain = [
                ('delivery_channel', '=', 'courier'),
                ('state', 'in', ['sale', 'done']),
                ('delivery_date', '>=', self.delivery_date_from),
                ('delivery_date', '<=', self.delivery_date_to),
            ]
            if not self.include_late_orders:
                order_domain.append(('is_late_order', '=', False))
            else:
                order_domain.append(('is_late_order', '=', True))

            matching_orders = self.env['sale.order'].search(order_domain)
            if not matching_orders:
                order_type_str = _("Late Courier Delivery") if self.include_late_orders else _("Courier Delivery")
                raise UserError(_(
                    "No confirmed %s orders found with delivery dates between %s and %s."
                ) % (
                    order_type_str,
                    self.delivery_date_from.strftime('%d/%m/%Y'),
                    self.delivery_date_to.strftime('%d/%m/%Y'),
                ))
            return job_model.dispatch_report(
                wizard=self,
                report_xmlid='tl_rf_reports.action_report_packing_list',
                wizard_vals=self._wizard_vals(),
                display_name=_('Courier Packing List Report'),
                record_count=len(matching_orders),
            )

        # Regal Van Delivery (Batch-based)
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
        eligible_orders = batches.mapped('order_ids').filtered(
            lambda so: so.state in ('sale', 'done') and getattr(so, 'delivery_channel', False) in ('regal_van', False)
        )
        if not self.include_late_orders:
            eligible_orders = eligible_orders.filtered(lambda so: not getattr(so, 'is_late_order', False))
        else:
            eligible_orders = eligible_orders.filtered(lambda so: getattr(so, 'is_late_order', False))

        if not eligible_orders:
            raise UserError(_("Eligible batches were found, but they do not contain any matching Regal Van Delivery sale orders."))

        return job_model.dispatch_report(
            wizard=self,
            report_xmlid='tl_rf_reports.action_report_packing_list',
            wizard_vals=self._wizard_vals(),
            display_name=_('Packing List Report'),
            record_count=len(eligible_orders),
        )

    def _action_print_driver_packing_list(self):
        """Driver Packing List: Regal Van Delivery only, filtered by Delivery Date and
        Depot. Late Order status is intentionally NOT used as a filter here."""
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

        eligible_orders = batches.mapped('order_ids').filtered(
            lambda so: so.state in ('sale', 'done') and getattr(so, 'delivery_channel', False) in ('regal_van', False)
        )
        if not eligible_orders:
            raise UserError(_(
                "Eligible batches were found, but they do not contain any matching Regal Van Delivery sale orders."
            ))

        return self.env['tl.report.generation.job'].dispatch_report(
            wizard=self,
            report_xmlid='tl_rf_reports.action_report_driver_packing_list',
            wizard_vals=self._wizard_vals(),
            display_name=_('Driver Packing List Report'),
            record_count=len(eligible_orders),
        )
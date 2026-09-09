# -*- coding: utf-8 -*-
from datetime import timedelta
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class ProductionReportWizard(models.TransientModel):
    _name = 'production.report.wizard'
    _description = 'Production Report Wizard'

    delivery_channel = fields.Selection(
        selection=[
            ('regal_van', 'Regal Van Delivery'),
            ('courier', 'Courier Delivery'),
        ],
        string='Delivery Channel',
        required=True,
        default='regal_van',
        help="Select delivery channel for the production report."
    )

    def _default_packing_date(self):
        return fields.Date.context_today(self) - timedelta(days=1)

    delivery_date_from = fields.Date(
        string='Delivery Date From',
        required=True,
        default=fields.Date.context_today,
        help="Starting delivery date for production report selection."
    )
    delivery_date_to = fields.Date(
        string='Delivery Date To',
        required=True,
        default=fields.Date.context_today,
        help="Ending delivery date for production report selection."
    )
    packing_date_from = fields.Date(
        string='Packing Date From',
        default=_default_packing_date,
        help="Starting packing date for production report selection."
    )
    packing_date_to = fields.Date(
        string='Packing Date To',
        default=_default_packing_date,
        help="Ending packing date for production report selection."
    )

    @api.model
    def _default_depot_ids(self):
        return self.env['stock.warehouse'].search([])

    depot_ids = fields.Many2many(
        'stock.warehouse',
        'production_report_wizard_warehouse_rel',
        'wizard_id',
        'warehouse_id',
        string='Depot',
        default=_default_depot_ids,
        help="Select one or more depots. Leave unselected to include all depots."
    )
    include_late_orders = fields.Boolean(
        string='Late Order',
        default=False,
        help="When unchecked, normal Production Report is generated. When checked, separate Late Order Production Report is generated."
    )

    @api.model
    def _default_category_ids(self):
        return self.env['product.category'].search([('name', 'in', ['Fresh', 'Chilled'])])

    category_ids = fields.Many2many(
        'product.category',
        'production_report_wizard_category_rel',
        'wizard_id',
        'category_id',
        string='Categories',
        domain=[('name', 'in', ['Fresh', 'Chilled'])],
        default=_default_category_ids,
        help="Select Fresh, Chilled, or both product categories to include in the report."
    )

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

    def _get_matching_orders(self):
        """Shared logic: returns the eligible sale.order recordset based on current wizard filters."""
        self.ensure_one()

        if self.delivery_channel == 'courier':
            order_domain = [
                ('delivery_channel', '=', 'courier'),
                ('state', 'in', ['sale', 'done']),
                ('delivery_date', '>=', self.delivery_date_from),
                ('delivery_date', '<=', self.delivery_date_to),
            ]
            order_domain.append(('is_late_order', '=', self.include_late_orders))
            return self.env['sale.order'].search(order_domain)

        domain = [
            ('delivery_date', '>=', self.delivery_date_from),
            ('delivery_date', '<=', self.delivery_date_to),
        ]
        if self.depot_ids:
            domain.append(('depot_id', 'in', self.depot_ids.ids))

        batches = self.env['round.management.batch'].search(domain)
        if not batches:
            return self.env['sale.order']

        eligible_orders = batches.mapped('order_ids').filtered(
            lambda so: so.state in ('sale', 'done') and getattr(so, 'delivery_channel', False) in ('regal_van', False)
        )
        eligible_orders = eligible_orders.filtered(
            lambda so: getattr(so, 'is_late_order', False) == self.include_late_orders
        )
        return eligible_orders

    def action_print_report(self):
        """Validates eligible batches or courier orders and triggers the Production Report."""
        self.ensure_one()

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
            return self.env.ref('tl_rf_reports.action_report_production_report').report_action(self)

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
        if not self.include_late_orders:
            eligible_orders = eligible_orders.filtered(lambda so: not getattr(so, 'is_late_order', False))
        else:
            eligible_orders = eligible_orders.filtered(lambda so: getattr(so, 'is_late_order', False))

        if not eligible_orders:
            raise UserError(_("Eligible batches were found, but they do not contain any matching Regal Van Delivery sale orders."))

        return self.env.ref('tl_rf_reports.action_report_production_report').report_action(self)

    def action_print_label(self):
        """Triggers the channel-specific Production Label report."""
        self.ensure_one()
        label_lines = self._get_label_data()
        if not label_lines:
            raise UserError(_("No matching records found to generate labels for the selected criteria."))

        if self.delivery_channel == 'courier':
            report_action = self.env.ref('tl_rf_reports.action_report_production_label_courier')
        else:
            report_action = self.env.ref('tl_rf_reports.action_report_production_label_regal_van')

        return report_action.report_action(self)

    def _get_label_data(self):
        """Returns a list of dicts, one per label to print, based on the current wizard filters."""
        self.ensure_one()
        label_lines = []
        orders = self._get_matching_orders()
        category_ids = self.category_ids.ids

        for order in orders:
            batch = order.batch_id
            warehouse = batch.depot_id if batch else False

            for line in order.order_line:
                product = line.product_id

                if not product or not product.categ_id:
                    continue

                if category_ids and product.categ_id.id not in category_ids:
                    continue

                # Calculate Fresh Use By date
                # Delivery Date + Product Expiration Time (days)
                use_by_date = False

                if order.delivery_date and product.expiration_time:
                    use_by_date = order.delivery_date + timedelta(
                        days=product.expiration_time
                    )

                label_lines.append({
                    'customer_name': order.partner_id.name or '',
                    'customer_code': order.partner_id.customer_code or '',

                    'delivery_date_display': (
                        order.delivery_date.strftime('%a, %d %B %Y')
                        if order.delivery_date else ''
                    ),

                    'delivery_day_display': (
                        order.delivery_date.strftime('%A')
                        if order.delivery_date else ''
                    ),

                    'batch_code': batch.code if batch else '',
                    'category_name': product.categ_id.name or '',
                    'warehouse_name': warehouse.name if warehouse else '',
                    'product_name': product.name or '',
                    'origin_country': product.origin_country or '',

                    # Fresh Use By:
                    # Delivery Date + Product Expiration Time
                    'use_by_display': (
                        use_by_date.strftime('%d %B %Y')
                        if use_by_date else ''
                    ),
                })

        return label_lines

# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class BatchReportWizard(models.TransientModel):
    _name = 'batch.report.wizard'
    _description = 'Dock Weight Breakdown Report Wizard'

    delivery_channel = fields.Selection(
        selection=[
            ('regal_van', 'Regal Van Delivery'),
            ('courier', 'Courier Delivery'),
        ],
        string='Delivery Channel',
        required=True,
        default='regal_van',
        help="Select delivery channel for the report."
    )
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
    @api.model
    def _default_depot_ids(self):
        return self.env['stock.warehouse'].search([])

    depot_ids = fields.Many2many(
        'stock.warehouse',
        'batch_report_wizard_warehouse_rel',
        'wizard_id',
        'warehouse_id',
        string='Depot',
        default=_default_depot_ids,
        help="Select one or more depots. Leave unselected to include all depots."
    )
    include_late_orders = fields.Boolean(
        string='Late Order',
        default=False,
        help="When unchecked, Late Orders are excluded. When checked, Late Orders are filtered."
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
        """Validates eligible batches or courier orders and triggers the Dock Weight Breakdown Report."""
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
                raise UserError(_(
                    "No confirmed Courier Delivery orders found with delivery dates between %s and %s."
                ) % (
                    self.delivery_date_from.strftime('%d/%m/%Y'),
                    self.delivery_date_to.strftime('%d/%m/%Y'),
                ))
            report_act = self.env.ref('tl_rf_reports.action_report_dock_weight_breakdown').report_action(self)
            lines_act = self.action_view_lines()
            return {
                'type': 'ir.actions.client',
                'tag': 'print_and_open_lines',
                'params': {
                    'report_action': report_act,
                    'lines_action': lines_act,
                }
            }
            # return self.env.ref('tl_rf_reports.action_report_dock_weight_breakdown').report_action(self)

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

        report_act = self.env.ref('tl_rf_reports.action_report_dock_weight_breakdown').report_action(self)
        lines_act = self.action_view_lines()
        return {
            'type': 'ir.actions.client',
            'tag': 'print_and_open_lines',
            'params': {
                'report_action': report_act,
                'lines_action': lines_act,
            }
        }
        # return self.env.ref('tl_rf_reports.action_report_dock_weight_breakdown').report_action(self)

    def action_view_lines(self):
        """Opens the Sale Order Line list view with grouping by category (Courier) or depot and category (Regal Van)."""
        self.ensure_one()

        if self.delivery_channel == 'courier':
            domain = [
                ('delivery_channel', '=', 'courier'),
                ('order_id.state', 'in', ['sale', 'done']),
                ('order_id.delivery_date', '>=', self.delivery_date_from),
                ('order_id.delivery_date', '<=', self.delivery_date_to),
                ('display_type', '=', False),
                ('product_id', '!=', False),
            ]
            if not self.include_late_orders:
                domain.append(('is_late_order', '=', False))
            else:
                domain.append(('is_late_order', '=', True))

            matching_lines = self.env['sale.order.line'].search_count(domain)
            if not matching_lines:
                raise UserError(_(
                    "No confirmed Courier Delivery order lines found with delivery dates between %s and %s."
                ) % (
                    self.delivery_date_from.strftime('%d/%m/%Y'),
                    self.delivery_date_to.strftime('%d/%m/%Y'),
                ))

            context = {
                'search_default_group_by_category': 1,
            }
            return {
                'name': _('Courier Dock Weight - Order Lines'),
                'type': 'ir.actions.act_window',
                'res_model': 'sale.order.line',
                'view_mode': 'list,form',
                'views': [
                    (self.env.ref('tl_rf_reports.view_sale_order_line_dock_weight_tree').id, 'list'),
                    (False, 'form'),
                ],
                'search_view_id': [self.env.ref('tl_rf_reports.view_sale_order_line_dock_weight_search').id, 'search'],
                'domain': domain,
                'context': context,
            }

        # Regal Van Delivery (Batch & Depot based)
        domain = [
            ('order_id.state', 'in', ['sale', 'done']),
            ('order_id.delivery_channel', 'in', ['regal_van', False]),
            ('order_id.delivery_date', '>=', self.delivery_date_from),
            ('order_id.delivery_date', '<=', self.delivery_date_to),
            ('display_type', '=', False),
            ('product_id', '!=', False),
        ]
        if self.depot_ids:
            domain.append(('depot_id', 'in', self.depot_ids.ids))
        if not self.include_late_orders:
            domain.append(('is_late_order', '=', False))
        else:
            domain.append(('is_late_order', '=', True))

        matching_lines = self.env['sale.order.line'].search_count(domain)
        if not matching_lines:
            raise UserError(_(
                "No confirmed Regal Van Delivery order lines found with delivery dates between %s and %s."
            ) % (
                self.delivery_date_from.strftime('%d/%m/%Y'),
                self.delivery_date_to.strftime('%d/%m/%Y'),
            ))

        context = {
            'search_default_group_by_depot': 1,
            'search_default_group_by_category': 1,
        }
        return {
            'name': _('Dock Weight Breakdown - Order Lines'),
            'type': 'ir.actions.act_window',
            'res_model': 'sale.order.line',
            'view_mode': 'list,form',
            'views': [
                (self.env.ref('tl_rf_reports.view_sale_order_line_dock_weight_tree').id, 'list'),
                (False, 'form'),
            ],
            'search_view_id': [self.env.ref('tl_rf_reports.view_sale_order_line_dock_weight_search').id, 'search'],
            'domain': domain,
            'context': context,
        }

# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class RequirementReportWizard(models.TransientModel):
    _name = 'requirement.report.wizard'
    _description = 'Requirement Report Wizard'

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
        help="Starting delivery date for requirement report."
    )
    delivery_date_to = fields.Date(
        string='Delivery Date To',
        required=True,
        default=fields.Date.context_today,
        help="Ending delivery date for requirement report."
    )

    @api.model
    def _default_depot_ids(self):
        return self.env['stock.warehouse'].search([])

    depot_ids = fields.Many2many(
        'stock.warehouse',
        'requirement_report_wizard_warehouse_rel',
        'wizard_id',
        'warehouse_id',
        string='Depot',
        default=_default_depot_ids,
        help="Select one or more depots. Leave unselected to include all depots."
    )

    categ_ids = fields.Many2many(
        'product.category',
        'requirement_report_wizard_category_rel',
        'wizard_id',
        'category_id',
        string='Product Category',
        help="Select one or more product categories to filter. Leave empty to include all categories."
    )

    @api.constrains('delivery_date_from', 'delivery_date_to')
    def _check_dates(self):
        for record in self:
            if record.delivery_date_from and record.delivery_date_to and record.delivery_date_to < record.delivery_date_from:
                raise ValidationError(_("Delivery Date To cannot be earlier than Delivery Date From."))

    def _get_line_domain(self):
        """Helper method to construct search domain for sale order lines."""
        self.ensure_one()
        domain = [
            ('order_id.state', 'in', ['sale', 'done']),
            ('order_id.delivery_date', '>=', self.delivery_date_from),
            ('order_id.delivery_date', '<=', self.delivery_date_to),
            ('display_type', '=', False),
            ('product_id', '!=', False),
        ]
        if self.delivery_channel == 'courier':
            domain.append(('order_id.delivery_channel', '=', 'courier'))
        else:
            domain.append(('order_id.delivery_channel', 'in', ['regal_van', False]))
            if self.depot_ids:
                domain.append(('depot_id', 'in', self.depot_ids.ids))

        if self.categ_ids:
            domain.append(('categ_id', 'in', self.categ_ids.ids))

        return domain

    def action_print_report(self):
        """Validates matching orders/lines and triggers the Requirement PDF Report."""
        self.ensure_one()
        domain = self._get_line_domain()
        matching_lines = self.env['sale.order.line'].search_count(domain)
        if not matching_lines:
            channel_name = dict(self._fields['delivery_channel'].selection).get(self.delivery_channel, '')
            raise UserError(_(
                "No confirmed %s order lines found with delivery dates between %s and %s."
            ) % (
                channel_name,
                self.delivery_date_from.strftime('%d/%m/%Y'),
                self.delivery_date_to.strftime('%d/%m/%Y'),
            ))

        if self.delivery_channel == 'courier':
            courier_action = self.env.ref('tl_rf_reports.action_report_requirement_courier', raise_if_not_found=False)
            if courier_action:
                return courier_action.report_action(self)
        return self.env.ref('tl_rf_reports.action_report_requirement').report_action(self)

    def action_view_lines(self):
        """Opens the Sale Order Line list view grouped by category and delivery date."""
        self.ensure_one()
        domain = self._get_line_domain()
        matching_lines = self.env['sale.order.line'].search_count(domain)
        if not matching_lines:
            channel_name = dict(self._fields['delivery_channel'].selection).get(self.delivery_channel, '')
            raise UserError(_(
                "No confirmed %s order lines found with delivery dates between %s and %s."
            ) % (
                channel_name,
                self.delivery_date_from.strftime('%d/%m/%Y'),
                self.delivery_date_to.strftime('%d/%m/%Y'),
            ))

        context = {
            'search_default_group_by_category': 1,
            # 'search_default_group_by_delivery_date': 1,
        }
        return {
            'name': _('Requirement Report - Order Lines'),
            'type': 'ir.actions.act_window',
            'res_model': 'sale.order.line',
            'view_mode': 'list,form',
            'views': [
                (self.env.ref('tl_rf_reports.view_sale_order_line_requirement_tree').id, 'list'),
                (False, 'form'),
            ],
            'search_view_id': [self.env.ref('tl_rf_reports.view_sale_order_line_requirement_search').id, 'search'],
            'domain': domain,
            'context': context,
        }

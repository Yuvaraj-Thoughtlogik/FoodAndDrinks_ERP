# -*- coding: utf-8 -*-
import base64

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

    @api.onchange('delivery_date_from')
    def _onchange_delivery_date_from(self):
        """Keep 'Delivery Date To' in sync with 'Delivery Date From' whenever
        the start date changes, so a single-day selection (e.g. both = Sep 14)
        is the default without extra clicks. If the user later picks a later
        'To' date manually, that stays untouched until 'From' changes again."""
        if self.delivery_date_from:
            self.delivery_date_to = self.delivery_date_from

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

    def _download_action(self, pdf_content, filename):
        attachment = self.env['ir.attachment'].create({
            'name': filename,
            'type': 'binary',
            'datas': base64.b64encode(pdf_content),
            'mimetype': 'application/pdf',
            'res_model': self._name,
            'res_id': self.id,
        })
        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{attachment.id}?download=true',
            'target': 'self',
        }

    def action_print_report(self):
        """Validates eligible batches or courier orders and triggers the Dock
        Weight Breakdown Report.

        The PDF is now built directly with ReportLab (generate_pdf() on the
        report model) instead of QWeb+wkhtmltopdf, so the report action is a
        synchronous download rather than the old report_action() call - see
        report/dock_weight_breakdown_report.py. The "print report + open the
        underlying lines" client action wrapping (print_and_open_lines) is
        unchanged; only the report_action piece inside it is now an
        ir.actions.act_url download."""
        self.ensure_one()

        if self.delivery_channel == 'courier':
            order_domain = [
                ('delivery_channel', '=', 'courier'),
                ('state', 'in', ['sale', 'done']),
                ('delivery_date', '>=', self.delivery_date_from),
                ('delivery_date', '<=', self.delivery_date_to),
                # Late is line-based (order flagged late, line added after
                # confirm, or line qty changed after confirm) - matching on
                # order_line.late_order picks up orders with at least one
                # qualifying line, not just orders flagged late as a whole.
                ('order_line.late_order', '=', bool(self.include_late_orders)),
            ]

            matching_orders = self.env['sale.order'].search(order_domain)
            if not matching_orders:
                raise UserError(_(
                    "No confirmed Courier Delivery orders found with delivery dates between %s and %s."
                ) % (
                    self.delivery_date_from.strftime('%d/%m/%Y'),
                    self.delivery_date_to.strftime('%d/%m/%Y'),
                ))

            report_model = self.env['report.tl_rf_reports.report_dock_weight_breakdown']
            pdf_content = report_model.generate_pdf(self)
            if not pdf_content:
                raise UserError(_(
                    "No confirmed Courier Delivery orders with matching product weights were found with "
                    "delivery dates between %s and %s."
                ) % (
                    self.delivery_date_from.strftime('%d/%m/%Y'),
                    self.delivery_date_to.strftime('%d/%m/%Y'),
                ))
            report_act = self._download_action(
                pdf_content, f"Courier_Dock_Weight_{self.delivery_date_from.strftime('%Y%m%d')}.pdf"
            )
            lines_act = self.action_view_lines()
            return {
                'type': 'ir.actions.client',
                'tag': 'print_and_open_lines',
                'params': {
                    'report_action': report_act,
                    'lines_action': lines_act,
                }
            }

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
        is_late = bool(self.include_late_orders)
        # Late is line-based (order flagged late, line added after confirm,
        # or line qty changed after confirm) - keep orders with at least one
        # qualifying line, not just orders flagged late as a whole.
        eligible_orders = eligible_orders.filtered(
            lambda so: any(
                bool(l.late_order) == is_late
                for l in so.order_line
                if not l.display_type and l.product_id and l.product_uom_qty > 0
            )
        )

        if not eligible_orders:
            raise UserError(_("Eligible batches were found, but they do not contain any matching Regal Van Delivery sale orders."))

        report_model = self.env['report.tl_rf_reports.report_dock_weight_breakdown']
        pdf_content = report_model.generate_pdf(self)
        if not pdf_content:
            raise UserError(_(
                "Eligible batches were found, but they do not contain any matching Regal Van Delivery "
                "sale order lines with weight data."
            ))
        report_act = self._download_action(
            pdf_content, f"Dock_Weight_Breakdown_{self.delivery_date_from.strftime('%Y%m%d')}.pdf"
        )
        lines_act = self.action_view_lines()
        # return {
        #     'type': 'ir.actions.client',
        #     'tag': 'print_and_open_lines',
        #     'params': {
        #         'report_action': report_act,
        #         'lines_action': lines_act,
        #     }
        # }
        return report_act

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
                ('late_order', '=', bool(self.include_late_orders)),
            ]

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
        domain.append(('late_order', '=', bool(self.include_late_orders)))

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

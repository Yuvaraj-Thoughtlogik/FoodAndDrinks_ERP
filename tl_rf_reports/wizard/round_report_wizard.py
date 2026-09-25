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
            ('both', 'Both'),
        ],
        string='Delivery Channel',
        required=True,
        default='regal_van',
        help="Select delivery channel for the report. 'Both' merges Regal Van and Courier "
             "lines into one Depot -> Category report, courier lines listed under their depot."
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
    report_type = fields.Selection(
        selection=[
            ('normal', 'Weight Breakdown Report'),
            ('all', 'All Weight Breakdown Report'),
            ('late', 'Late Order'),
        ],
        string='Report Type',
        default='normal',
        required=True,
        help="Weight Breakdown: normal order lines only. All Weight Breakdown: normal and "
             "late order lines combined. Late Order: late order lines only, with the weight "
             "added/removed by late changes (ALT's report)."
    )

    @api.onchange('report_type')
    def _onchange_report_type(self):
        self.include_late_orders = self.report_type == 'late'

    def _is_late_report(self):
        """Late Order report: late lines only, ALT's layout."""
        self.ensure_one()
        return self.report_type == 'late'

    def _line_matches_late(self, line):
        """Late filter for one sale order line: All Weight Breakdown takes
        every line, the other two keep only non-late / late lines."""
        if self.report_type == 'all':
            return True
        return bool(line.is_late_order) == self._is_late_report()

    def _late_domain(self, field='is_late_order'):
        """Same late filter as _line_matches_late(), as a domain."""
        self.ensure_one()
        if self.report_type == 'all':
            return []
        return [(field, '=', self._is_late_report())]

    @api.model
    def _default_category_ids(self):
        return self.env['product.category'].search([('name', '=ilike', 'Fresh')])

    category_ids = fields.Many2many(
        'product.category',
        'batch_report_wizard_category_rel',
        'wizard_id',
        'category_id',
        string='Product Categories',
        default=_default_category_ids,
        help="Only products in these categories (or their sub-categories) are included. "
             "Leave empty to include all categories."
    )

    def _get_filter_category_ids(self):
        """Selected categories plus their sub-categories, or an empty list
        when no category is selected (= no filtering)."""
        self.ensure_one()
        if not self.category_ids:
            return []
        return self.env['product.category'].search([('id', 'child_of', self.category_ids.ids)]).ids

    def _line_matches_category(self, line, categ_ids=None):
        """True when the sale order line's product falls within the wizard's
        category filter (always True when no category is selected)."""
        if categ_ids is None:
            categ_ids = self._get_filter_category_ids()
        return not categ_ids or line.product_id.categ_id.id in categ_ids

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

    def _channel_label(self):
        return {
            'regal_van': _("Regal Van Delivery"),
            'courier': _("Courier Delivery"),
            'both': _("Regal Van or Courier Delivery"),
        }.get(self.delivery_channel, '')

    def action_print_report(self):
        """Builds the Dock Weight Breakdown PDF directly with ReportLab
        (generate_pdf() on the report model) and returns it as a download.

        Report Type picks which lines are included (normal / all / late -
        see _line_matches_late()), Delivery Channel which orders: Regal Van
        (batch-based), Courier, or Both merged into the Regal Van layout."""
        self.ensure_one()
        self.include_late_orders = self._is_late_report()
        date_from_str = self.delivery_date_from.strftime('%d/%m/%Y')
        date_to_str = self.delivery_date_to.strftime('%d/%m/%Y')

        if self.delivery_channel == 'regal_van':
            domain = [
                ('delivery_date', '>=', self.delivery_date_from),
                ('delivery_date', '<=', self.delivery_date_to),
            ]
            if self.depot_ids:
                domain.append(('depot_id', 'in', self.depot_ids.ids))
            if not self.env['round.management.batch'].search_count(domain):
                depot_names = ", ".join(self.depot_ids.mapped('name')) if self.depot_ids else ""
                depot_label = f" for depot(s) '{depot_names}'" if depot_names else ""
                raise UserError(_(
                    "No batches found with delivery dates between %s and %s%s."
                ) % (date_from_str, date_to_str, depot_label))

        report_model = self.env['report.tl_rf_reports.report_dock_weight_breakdown']
        pdf_content = report_model.generate_pdf(self)
        if not pdf_content:
            raise UserError(_(
                "No confirmed %s order lines matching the selected report type, depots and "
                "categories were found with delivery dates between %s and %s."
            ) % (self._channel_label(), date_from_str, date_to_str))

        prefix = {
            'courier': 'Courier_Dock_Weight_',
            'both': 'Dock_Weight_Breakdown_Combined_',
        }.get(self.delivery_channel, 'Dock_Weight_Breakdown_')
        if self.report_type == 'all':
            prefix = 'All_' + prefix
        elif self.report_type == 'late':
            prefix = 'Late_' + prefix
        return self._download_action(
            pdf_content, f"{prefix}{self.delivery_date_from.strftime('%Y%m%d')}.pdf"
        )

    def action_view_lines(self):
        """Opens the Sale Order Line list view matching the report's filters,
        grouped by category (Courier) or depot and category (Regal Van/Both)."""
        self.ensure_one()
        categ_ids = self._get_filter_category_ids()

        domain = [
            ('order_id.state', 'in', ['sale', 'done']),
            ('order_id.delivery_date', '>=', self.delivery_date_from),
            ('order_id.delivery_date', '<=', self.delivery_date_to),
            ('display_type', '=', False),
            ('product_id', '!=', False),
        ]
        if self.delivery_channel == 'courier':
            domain.append(('order_id.delivery_channel', '=', 'courier'))
        elif self.delivery_channel == 'both':
            domain.append(('order_id.delivery_channel', 'in', ['regal_van', 'courier', False]))
            if self.depot_ids:
                # Courier lines are listed under their line depot, else the order's warehouse.
                domain += [
                    '|', ('depot_id', 'in', self.depot_ids.ids),
                    '&', ('depot_id', '=', False), ('order_id.warehouse_id', 'in', self.depot_ids.ids),
                ]
        else:
            domain.append(('order_id.delivery_channel', 'in', ['regal_van', False]))
            if self.depot_ids:
                domain.append(('depot_id', 'in', self.depot_ids.ids))
        domain += self._late_domain()
        if categ_ids:
            domain.append(('product_id.categ_id', 'in', categ_ids))

        if not self.env['sale.order.line'].search_count(domain):
            raise UserError(_(
                "No confirmed %s order lines found with delivery dates between %s and %s."
            ) % (
                self._channel_label(),
                self.delivery_date_from.strftime('%d/%m/%Y'),
                self.delivery_date_to.strftime('%d/%m/%Y'),
            ))

        if self.delivery_channel == 'courier':
            name = _('Courier Dock Weight - Order Lines')
            context = {'search_default_group_by_category': 1}
        else:
            name = _('Dock Weight Breakdown - Order Lines')
            context = {
                'search_default_group_by_depot': 1,
                'search_default_group_by_category': 1,
            }
        return {
            'name': name,
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

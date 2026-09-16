# -*- coding: utf-8 -*-
import base64
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
        # domain=[('name', 'in', ['Fresh', 'Chilled'])],
        # default=_default_category_ids,
        help="Select Fresh, Chilled, or both product categories to include in the report."
    )

    @api.onchange('delivery_date_from')
    def _onchange_delivery_date_from(self):
        if self.delivery_date_from:
            self.delivery_date_to = self.delivery_date_from
            self.packing_date_from = self.delivery_date_from - timedelta(days=1)
            self.packing_date_to = self.delivery_date_from - timedelta(days=1)

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

    def _get_production_domain(self):
        """Domain for the draft Regal Van Manufacturing Orders backing the
        Production Report. A draft MO's own top-level product is a generic
        pack (e.g. "Salmon Fish Pack"), not the box-type product to report
        on - that lives on its raw-material component lines (move_raw_ids,
        see report/production_report.py) - so this domain does NOT filter by
        category; category_ids is applied to the component lines instead
        (see _get_component_move_domain() below and generate_pdf()).

        Filters through round_batch_id (not the ambiguous delivery_date/
        batch_id fields also defined on mrp.production by round_management's
        stock_picking.py - see the note in models/mrp_production.py) so this
        stays correct regardless of which of those overlapping field
        definitions the registry resolves."""
        self.ensure_one()
        domain = [
            ('state', '=', 'draft'),
            ('delivery_channel', '=', 'regal_van'),
            ('round_batch_id.delivery_date', '>=', self.delivery_date_from),
            ('round_batch_id.delivery_date', '<=', self.delivery_date_to),
            ('is_late_order', '=', self.include_late_orders),
        ]
        if self.depot_ids:
            domain.append(('depot_id', 'in', self.depot_ids.ids))
        return domain

    def _get_component_move_domain(self):
        """Domain for the draft Regal Van Manufacturing Orders' raw material
        component lines (move_raw_ids) backing the Production Report's "View
        Lines" screen - the same records report/production_report.py's
        generate_pdf() groups Depot -> Category -> Product from, filtered/
        grouped by the *component's* category and product, not the MO's own."""
        self.ensure_one()
        domain = [
            ('raw_material_production_id', '!=', False),
            ('raw_material_production_id.state', '=', 'draft'),
            ('raw_material_production_id.delivery_channel', '=', 'regal_van'),
            ('raw_material_production_id.round_batch_id.delivery_date', '>=', self.delivery_date_from),
            ('raw_material_production_id.round_batch_id.delivery_date', '<=', self.delivery_date_to),
            ('raw_material_production_id.is_late_order', '=', self.include_late_orders),
        ]
        if self.depot_ids:
            domain.append(('raw_material_production_id.depot_id', 'in', self.depot_ids.ids))
        if self.category_ids:
            domain.append(('product_id.categ_id', 'in', self.category_ids.ids))
        return domain

    def action_print_report(self):
        """Builds the Production Report PDF directly with ReportLab (see
        report/production_report.py) from the draft Regal Van Manufacturing
        Orders matching the wizard's filters, and returns it as a
        synchronous download - the same "fast path" as action_print_label()
        below, no QWeb/wkhtmltopdf, no background job."""
        self.ensure_one()
        if self.delivery_channel == 'courier':
            raise UserError(_("Production Report is not yet available for Courier Delivery."))

        domain = self._get_production_domain()
        productions = self.env['mrp.production'].search(domain)
        if not productions:
            raise UserError(_(
                "No draft Manufacturing Orders found for Regal Van Delivery with delivery dates between %s and %s."
            ) % (
                self.delivery_date_from.strftime('%d/%m/%Y'),
                self.delivery_date_to.strftime('%d/%m/%Y'),
            ))

        report_model = self.env['report.tl_rf_reports.report_production_report']
        pdf_content = report_model.generate_pdf(self, productions)
        if not pdf_content:
            raise UserError(_("No matching records found to generate the Production Report for the selected criteria."))

        attachment = self.env['ir.attachment'].create({
            'name': f'Production_Report_{self.delivery_date_from.strftime("%Y%m%d")}.pdf',
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

    def action_view_lines(self):
        """Opens the underlying draft MOs' raw material component lines (one
        row per box - e.g. "0.5 kg Cod Fillets Boned" - see
        report/production_report.py) grouped by Depot -> Category, matching
        the Production Report's filters - same pattern as
        RequirementReportWizard.action_view_lines()."""
        self.ensure_one()
        if self.delivery_channel == 'courier':
            raise UserError(_("Production Report is only available for Regal Van Delivery."))

        domain = self._get_component_move_domain()
        if not self.env['stock.move'].search_count(domain):
            raise UserError(_(
                "No draft Manufacturing Orders found for Regal Van Delivery with delivery dates between %s and %s."
            ) % (
                self.delivery_date_from.strftime('%d/%m/%Y'),
                self.delivery_date_to.strftime('%d/%m/%Y'),
            ))

        return {
            'name': _('Production Report - Manufacturing Order Lines'),
            'type': 'ir.actions.act_window',
            'res_model': 'stock.move',
            'view_mode': 'list,form',
            'views': [
                (self.env.ref('tl_rf_reports.view_stock_move_production_report_list').id, 'list'),
                (False, 'form'),
            ],
            'search_view_id': [self.env.ref('tl_rf_reports.view_stock_move_production_report_search').id, 'search'],
            'domain': domain,
            'context': {
                'search_default_group_by_depot': 1,
                'search_default_group_by_category': 1,
            },
        }

    def action_print_label(self):
        """Triggers the channel-specific Production Label report.

        Built directly with ReportLab (generate_pdf() on the report model,
        see production_label_report.py) instead of QWeb+wkhtmltopdf, and
        returned as a synchronous download - one physical label per PDF
        page at a fixed 100mm x 130mm size. The QWeb templates/actions in
        production_label_report_views.xml are left registered for parity
        but are no longer invoked here."""
        self.ensure_one()
        label_lines = self._get_label_data()
        if not label_lines:
            raise UserError(_("No matching records found to generate labels for the selected criteria."))

        if self.delivery_channel == 'courier':
            report_model = self.env['report.tl_rf_reports.report_production_label_document_courier']
            filename_suffix = 'Courier'
        else:
            report_model = self.env['report.tl_rf_reports.report_production_label_document_regal_van']
            filename_suffix = 'Regal_Van'

        pdf_content = report_model.generate_pdf(self)
        if not pdf_content:
            raise UserError(_("No matching records found to generate labels for the selected criteria."))

        attachment = self.env['ir.attachment'].create({
            'name': f'Production_Label_{filename_suffix}_{self.delivery_date_from.strftime("%Y%m%d")}.pdf',
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
                    'round_name': order.round_id.name if order.round_id else '',

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
                    'product_barcode': product.barcode or '',
                    'product_default_code': product.default_code or '',

                    # Fresh Use By:
                    # Delivery Date + Product Expiration Time
                    'use_by_display': (
                        use_by_date.strftime('%d %B %Y')
                        if use_by_date else ''
                    ),
                })

        return label_lines
 

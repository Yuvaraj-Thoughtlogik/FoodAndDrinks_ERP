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
        lang = self.env.lang or 'en_US'
        company_ids = tuple(self.env.companies.ids) if self.env.companies else (self.env.company.id,)

        params = {
            'date_from': self.delivery_date_from,
            'date_to': self.delivery_date_to,
            'is_late': bool(self.include_late_orders),
            'company_ids': company_ids,
            'lang': lang,
        }

        channel_filter = ""
        depot_filter = ""
        if self.delivery_channel == 'courier':
            channel_filter = "AND so.delivery_channel = 'courier'"
        else:
            channel_filter = "AND (so.delivery_channel = 'regal_van' OR so.delivery_channel IS NULL)"
            if self.depot_ids:
                depot_filter = "AND b.depot_id IN %(depot_ids)s"
                params['depot_ids'] = tuple(self.depot_ids.ids)

        category_filter = ""
        if self.category_ids:
            category_filter = "AND pc.id IN %(category_ids)s"
            params['category_ids'] = tuple(self.category_ids.ids)

        query = f"""
            SELECT 
                rp.name AS customer_name,
                rp.customer_code AS customer_code,
                rmr.name AS round_name,
                so.delivery_date AS delivery_date,
                b.code AS batch_code,
                COALESCE(pc.name->>%(lang)s, pc.name->>'en_GB', pc.name->>'en_US', pc.name::text) AS category_name,
                sw.name AS warehouse_name,
                COALESCE(pt.name->>%(lang)s, pt.name->>'en_GB', pt.name->>'en_US', pt.name::text) AS product_name,
                pt.origin_country AS origin_country,
                COALESCE(p.barcode, pt.barcode, '') AS product_barcode,
                COALESCE(p.default_code, pt.default_code, '') AS product_default_code,
                pt.expiration_time AS expiration_time
            FROM sale_order so
            JOIN res_partner rp ON rp.id = so.partner_id
            LEFT JOIN round_management_batch b ON b.id = so.batch_id
            LEFT JOIN stock_warehouse sw ON sw.id = b.depot_id
            LEFT JOIN round_management_round rmr ON rmr.id = so.round_id
            JOIN sale_order_line sol ON sol.order_id = so.id 
                AND sol.display_type IS NULL 
                AND sol.product_id IS NOT NULL 
                AND sol.product_uom_qty > 0
            JOIN product_product p ON p.id = sol.product_id
            JOIN product_template pt ON pt.id = p.product_tmpl_id
            JOIN product_category pc ON pc.id = pt.categ_id
            WHERE so.state IN ('sale', 'done')
              AND so.delivery_date >= %(date_from)s
              AND so.delivery_date <= %(date_to)s
              AND COALESCE(so.is_late_order, false) = %(is_late)s
              {channel_filter}
              {depot_filter}
              {category_filter}
              AND (so.company_id IS NULL OR so.company_id IN %(company_ids)s)
            ORDER BY so.delivery_date ASC, so.name ASC, sol.id ASC
        """
        self.env.cr.execute(query, params)
        rows = self.env.cr.dictfetchall()

        label_lines = []
        for r in rows:
            delivery_date = r['delivery_date']
            exp_time = r['expiration_time']
            use_by_date = False
            if delivery_date and exp_time:
                use_by_date = delivery_date + timedelta(days=exp_time)

            label_lines.append({
                'customer_name': r['customer_name'] or '',
                'customer_code': r['customer_code'] or '',
                'round_name': r['round_name'] or '',
                'delivery_date_display': delivery_date.strftime('%a, %d %B %Y') if delivery_date else '',
                'delivery_day_display': delivery_date.strftime('%A') if delivery_date else '',
                'batch_code': r['batch_code'] or '',
                'category_name': r['category_name'] or '',
                'warehouse_name': r['warehouse_name'] or '',
                'product_name': r['product_name'] or '',
                'origin_country': r['origin_country'] or '',
                'product_barcode': r['product_barcode'] or '',
                'product_default_code': r['product_default_code'] or '',
                'use_by_display': use_by_date.strftime('%d %B %Y') if use_by_date else '',
            })

        return label_lines
 

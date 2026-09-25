# -*- coding: utf-8 -*-
import base64

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class ProductLabelWizard(models.TransientModel):
    """Production Label wizard opened from the Product (product.template)
    list view: Actions > Production Label.

    It copies every field and method of production.label.wizard (prototype
    inheritance), so the SAME label reports and the SAME
    _build_*_label_dict() helpers are reused, which keeps the label design
    identical. Only the data source changes: every label is built from the
    selected products. No Sales Order, MO, round, batch or depot is read.
    """
    _name = 'product.label.wizard'
    _inherit = 'production.label.wizard'
    _description = 'Product Label Wizard (from Product list)'

    # Own relation table - the parent's table is tied to production.label.wizard.
    depot_ids = fields.Many2many(
        'stock.warehouse',
        'product_label_wizard_warehouse_rel',
        'wizard_id',
        'warehouse_id',
        string='Depot',
    )

    product_tmpl_ids = fields.Many2many(
        'product.template',
        'product_label_wizard_product_tmpl_rel',
        'wizard_id',
        'product_tmpl_id',
        string='Products',
    )
    copies = fields.Integer(
        string='Copies',
        default=1,
        required=True,
        help="Number of labels to print for each selected product.",
    )
    allowed_category_ids = fields.Many2many(
        'product.category',
        compute='_compute_allowed_category_ids',
    )

    # ------------------------------------------------------------------
    # Defaults / computes / constraints
    # ------------------------------------------------------------------
    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        ctx = self.env.context
        if ctx.get('active_model') == 'product.template' and ctx.get('active_ids'):
            templates = self.env['product.template'].browse(ctx['active_ids']).exists()
            res['product_tmpl_ids'] = [(6, 0, templates.ids)]
            categories = templates.categ_id
            if len(categories) == 1:
                res['category_id'] = categories.id
        return res

    @api.depends('product_tmpl_ids')
    def _compute_allowed_category_ids(self):
        for wizard in self:
            wizard.allowed_category_ids = wizard.product_tmpl_ids.categ_id

    @api.constrains('copies')
    def _check_copies(self):
        for wizard in self:
            if wizard.copies < 1:
                raise ValidationError(_("Copies must be at least 1."))

    # The parent's date constraints are about order filters and do not apply here.
    @api.constrains('delivery_date_from', 'delivery_date_to')
    def _check_delivery_dates(self):
        return True

    @api.constrains('packing_date_from', 'packing_date_to')
    def _check_packing_dates(self):
        return True

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _get_label_products(self):
        """Selected products (variants) that belong to the chosen category."""
        self.ensure_one()
        if not self.product_tmpl_ids:
            raise UserError(_("Please select at least one product."))
        products = self.product_tmpl_ids.product_variant_ids.filtered(
            lambda p: p.categ_id == self.category_id
        )
        if not products:
            raise UserError(_(
                "None of the selected products belong to the '%s' category.",
                self.category_id.display_name,
            ))
        return products

    def _apply_copies(self, label_lines):
        """Repeat each label 'copies' times, keeping the copies of one product together."""
        self.ensure_one()
        return [dict(line) for line in label_lines for _i in range(self.copies)]

    def _get_expiry_display(self, product):
        """Expiry from the product template's Expiration Date field
        (expiration_time, Inventory tab), printed as days, e.g. '2 Days'.
        Empty when the product has no expiry set - the row is then hidden."""
        # Read from product.template safely: the field may not exist on
        # product.product (or at all if the expiry module is not installed).
        template = product.product_tmpl_id
        days = 0
        if 'expiration_time' in template._fields:
            days = template.expiration_time or 0
        # Only print when the product uses expiry dates and has days set.
        if 'use_expiration_date' in template._fields and not template.use_expiration_date:
            days = 0
        if not days:
            return ''
        return _("%s Day", days) if days == 1 else _("%s Days", days)

    # ------------------------------------------------------------------
    # Product-based data (overrides of the parent's SO / MO methods)
    # ------------------------------------------------------------------
    def _get_matching_orders(self):
        return self.env['sale.order']

    def _get_label_data(self):
        """Frozen Label + default layout - one entry per product."""
        self.ensure_one()
        label_lines = []
        for product in self._get_label_products():
            expiry = self._get_expiry_display(product)
            line_data = {
                'customer_name': '',
                'customer_code': '',
                'round_name': '',
                'delivery_date_display': '',
                'delivery_day_display': '',
                'batch_code': '',
                'category_name': product.categ_id.name or '',
                'warehouse_name': '',
                'product_name': product.name or '',
                'origin_country': product.origin_country or '',
                'product_barcode': product.barcode or '',
                'product_default_code': product.default_code or '',
                'use_by_display': expiry,
            }
            line_data.update(self._get_frozen_label_fields(False, product, False))
            # No production date; Use By = product expiry days.
            line_data['production_date_display'] = ''
            line_data['frozen_use_by_display'] = expiry
            label_lines.append(line_data)
        return self._apply_copies(label_lines)

    def _get_fresh_label_data(self):
        """Fresh Label - one entry per product (no MO / SO)."""
        self.ensure_one()
        label_lines = []
        for product in self._get_label_products():
            expiry = self._get_expiry_display(product)
            label_lines.append({
                'customer_name': '',
                'customer_code': '',
                'round_name': '',
                'delivery_date_display': '',
                'delivery_day_display': '',
                'batch_code': '',
                'category_name': product.categ_id.name or '',
                'warehouse_name': '',
                'product_name': product.name or '',
                'origin_country': product.origin_country or '',
                'product_barcode': product.barcode or '',
                'product_default_code': product.default_code or '',
                'use_by_display': expiry,
                'mo_name': '',
                'mo_qty': 0.0,
                'mo_uom': '',
            })
        return self._apply_copies(label_lines)

    def _get_plain_frozen_label_data(self):
        self.ensure_one()
        lines = []
        for product in self._get_label_products():
            data = self._build_plain_frozen_label_dict(product, False)
            data['freeze_date_display'] = ''
            data['best_before_display'] = self._get_expiry_display(product)
            lines.append(data)
        return self._apply_copies(lines)

    def _get_plain_label_data(self):
        self.ensure_one()
        lines = []
        for product in self._get_label_products():
            data = self._build_plain_label_dict(product, False)
            data['production_date_display'] = ''
            data['use_by_display'] = self._get_expiry_display(product)
            # No MO quantity here - use the product's own weight instead.
            if not data.get('min_weight_display') and product.weight:
                data['min_weight_display'] = "Min Weight: %.2f %s" % (
                    product.weight, product.weight_uom_name or 'kg')
            lines.append(data)
        return self._apply_copies(lines)

    def _get_chilled_front_sleeve_label_data(self):
        self.ensure_one()
        lines = []
        for product in self._get_label_products():
            data = self._build_chilled_front_sleeve_label_dict(product, False)
            data['production_date_display'] = ''
            data['use_by_display'] = self._get_expiry_display(product)
            lines.append(data)
        return self._apply_copies(lines)

    def _get_chilled_back_sleeve_label_data(self):
        self.ensure_one()
        lines = [
            self._build_chilled_back_sleeve_label_dict(product, False)
            for product in self._get_label_products()
        ]
        return self._apply_copies(lines)

    # ------------------------------------------------------------------
    # Print
    # ------------------------------------------------------------------
    def _get_report_config(self):
        """(report model name, filename suffix, data method, pass label_lines) for the chosen
        category + label format. Same reports as production.label.wizard."""
        self.ensure_one()
        prefix = 'report.tl_rf_reports.'
        category = self.category_name
        if category == 'Frozen':
            mapping = {
                'frozen_label': ('report_production_label_document_frozen', 'Frozen', self._get_label_data),
                'plain_frozen_label': ('report_production_label_plain_frozen', 'Plain_Frozen', self._get_plain_frozen_label_data),
                'plain_label': ('report_production_label_plain', 'Plain_Label', self._get_plain_label_data),
            }
            key, field = self.frozen_label_type, 'frozen_label_type'
        elif category == 'Chilled':
            mapping = {
                'front_sleeve_label': ('report_production_label_chilled_front', 'Chilled_Front_Sleeve', self._get_chilled_front_sleeve_label_data),
                'back_sleeve_label': ('report_production_label_chilled_back', 'Chilled_Back_Sleeve', self._get_chilled_back_sleeve_label_data),
            }
            key, field = self.chilled_label_type, 'chilled_label_type'
        elif category == 'Fresh':
            mapping = {
                'fresh_label': ('report_production_label_document_regal_van', 'Fresh', self._get_fresh_label_data),
            }
            key, field = self.fresh_label_type, 'fresh_label_type'
        else:
            return prefix + 'report_production_label_document_regal_van', 'Label', self._get_label_data, True

        if key not in mapping:
            raise UserError(_(
                "The '%s' label format is not implemented yet.",
                dict(self._fields[field].selection).get(key, key),
            ))
        report_name, suffix, data_method = mapping[key]
        # Only the Courier / Regal Van report's generate_pdf() accepts
        # label_lines. The Frozen, Plain Frozen, Plain and Chilled reports take
        # generate_pdf(wizard) only and call the wizard's _get_*_label_data()
        # themselves - those methods are overridden above to use product data.
        pass_lines = report_name == 'report_production_label_document_regal_van'
        return prefix + report_name, suffix, data_method, pass_lines

    def action_print_label(self):
        self.ensure_one()
        if not self.category_id:
            raise UserError(_("Please select a Category before printing labels."))

        report_name, filename_suffix, data_method, pass_lines = self._get_report_config()
        report = self.env[report_name]

        if pass_lines:
            pdf_content = report.generate_pdf(self, label_lines=data_method())
        else:
            pdf_content = report.generate_pdf(self)
        if not pdf_content:
            raise UserError(_("No labels to print for the selected products."))

        attachment = self.env['ir.attachment'].create({
            'name': f'Product_Label_{filename_suffix}_{fields.Date.context_today(self).strftime("%Y%m%d")}.pdf',
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
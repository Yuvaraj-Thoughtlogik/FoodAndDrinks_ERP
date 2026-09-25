# -*- coding: utf-8 -*-
import base64

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class ProductLabelWizard(models.TransientModel):
    """Production Label wizard opened from the Product (product.template)
    list view: Actions > Production Label.

    Inherits production.label.wizard (prototype inheritance) only to reuse its
    label-format fields. Every label is built from the selected products'
    own fields - no Sales Order, MO, production date or date calculation.
    The same ReportLab reports print them, so the design is identical.
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
        """Repeat each label 'copies' times (copies of one product together) and
        mark every label 'from_product' so the reports hide empty rows and do
        not add default text. MO / SO labels never carry this flag."""
        self.ensure_one()
        return [
            dict(line, from_product=True)
            for line in label_lines for _i in range(self.copies)
        ]

    def _product_field(self, product, *names):
        """First non-empty value of the given fields on the variant or its
        template - the product's own data only, no default text."""
        template = product.product_tmpl_id
        for name in names:
            for record in (product, template):
                if name in record._fields and record[name]:
                    return record[name]
        return ''

    def _product_catch_area(self, product):
        """Catch area built only from the product's own fields."""
        catch_method = self._product_field(product, 'catch_method')
        origin_country = self._product_field(product, 'origin_country')
        fao_area = self._product_field(product, 'fao_catch_area')
        text = catch_method or ''
        if origin_country:
            text = f"{text} in {origin_country}" if text else origin_country
        if fao_area:
            text = f"{text}, FAO {fao_area}" if text else f"FAO {fao_area}"
        if text and not text.endswith('.'):
            text += '.'
        if not text:
            fish_info = self._product_field(product, 'fish_info')
            text = fish_info.split('\n')[0].strip() if fish_info else ''
        return text

    def _company_address(self):
        company = self.env.company
        parts = [
            company.name, company.street, company.street2, company.city,
            company.state_id.name if company.state_id else False, company.zip,
        ]
        return ', '.join(part for part in parts if part)

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
    # Product-based data (overrides of the parent's SO / MO methods).
    # Every label is built ONLY from product fields. The MO / SO builder
    # methods of production.label.wizard are NOT called, so no production
    # date, MO date or date calculation is used anywhere. The only "date"
    # printed is the product's expiry days (e.g. "Use By: 2 Days"), and
    # only when the product has an expiry set.
    # ------------------------------------------------------------------
    def _get_matching_orders(self):
        return self.env['sale.order']

    def _latin_name(self, product):
        species = self._product_field(product, 'species_id')
        if species and getattr(species, 'name', False):
            return species.name
        return self._product_field(product, 'latin_name') or ''

    def _allergens(self, product):
        allergens = self._product_field(product, 'allergens_notice')
        if not allergens and 'allergen_ids' in product._fields and product.allergen_ids:
            allergens = ', '.join(product.allergen_ids.mapped('name'))
        return allergens or self._product_field(product, 'allergens') or ''

    def _weight_text(self, product):
        """Product weight as '250g' / '1kg' from the product's weight field."""
        w = product.weight
        if not w:
            return ''
        if w < 1:
            grams = w * 1000
            return f"{int(grams) if float(grams).is_integer() else grams}g"
        return f"{int(w) if float(w).is_integer() else w}kg"

    def _get_label_data(self):
        """Frozen Label (and default layout) - one entry per product."""
        self.ensure_one()
        label_lines = []
        for product in self._get_label_products():
            expiry = self._get_expiry_display(product)

            # Origin: country (+ FAO area), else catch method (+ FAO), else fish info
            origin = self._product_field(product, 'origin_country')
            fao_area = self._product_field(product, 'fao_catch_area')
            catch_method = self._product_field(product, 'catch_method')
            if origin:
                origin_display = origin
                if fao_area and f"FAO {fao_area}" not in origin_display:
                    origin_display = f"{origin_display} (FAO {fao_area})"
            elif catch_method:
                origin_display = f"{catch_method} (FAO {fao_area})" if fao_area else catch_method
            else:
                fish_info = self._product_field(product, 'fish_info')
                origin_display = fish_info.split('\n')[0].strip() if fish_info else ''

            description = self._product_field(product, 'packing_info', 'label_description')
            if not description and product.product_template_attribute_value_ids:
                description = ', '.join(product.product_template_attribute_value_ids.mapped('name'))
            if description and not description.endswith('.'):
                description += '.'

            weight_range = (
                self._product_field(product, 'gross_net_weight', 'weight_range')
                or (f"{product.weight} kg" if product.weight else '')
            )

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
                'origin_country': origin or '',
                'product_barcode': product.barcode or '',
                'product_default_code': product.default_code or '',
                'use_by_display': expiry,
                'latin_name': self._latin_name(product),
                'origin_display': origin_display,
                'label_description': description,
                'weight_range': weight_range,
                'allergens_display': self._allergens(product),
                'production_date_display': '',
                'frozen_use_by_display': expiry,
            })
        return self._apply_copies(label_lines)

    def _get_fresh_label_data(self):
        """Fresh Label - one entry per product."""
        self.ensure_one()
        label_lines = []
        for product in self._get_label_products():
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
                'origin_country': self._product_field(product, 'origin_country') or '',
                'product_barcode': product.barcode or '',
                'product_default_code': product.default_code or '',
                'use_by_display': self._get_expiry_display(product),
            })
        return self._apply_copies(label_lines)

    def _get_plain_frozen_label_data(self):
        """Plain Frozen Label - one entry per product."""
        self.ensure_one()
        lines = []
        for product in self._get_label_products():
            ingredients = self._product_field(product, 'ingredients_html')
            latin_name = self._latin_name(product) or self._product_field(product, 'origin_country') or ''
            lines.append({
                'product_name': (product.name or '').upper(),
                'latin_name': latin_name,
                'origin': latin_name,
                'ingredients': ingredients,
                'ingredients_html': ingredients,
                # Fixed legal text (not a product field)
                'storage_instructions': "Store at below -18°C.  Once defrosted do not refreeze",
                'catch_area': self._product_catch_area(product),
                'freeze_date_display': '',
                'best_before_display': self._get_expiry_display(product),
                'company_address': self._company_address(),
            })
        return self._apply_copies(lines)

    def _get_plain_label_data(self):
        """Plain Label - one entry per product."""
        self.ensure_one()
        lines = []
        for product in self._get_label_products():
            raw_name = (product.name or '').strip()
            name_main, name_sub = raw_name, ''
            if '\n' in raw_name:
                name_main, name_sub = [p.strip() for p in raw_name.split('\n', 1)]
            elif ' with ' in raw_name.lower():
                idx = raw_name.lower().index(' with ')
                name_main, name_sub = raw_name[:idx].strip(), raw_name[idx + 1:].strip()
            elif ' - ' in raw_name:
                name_main, name_sub = [p.strip() for p in raw_name.split(' - ', 1)]

            cooking = self._product_field(product, 'cooking_instructions_html')
            ingredients = self._product_field(product, 'ingredients_html')
            fish_info = self._product_field(product, 'fish_info')
            weight = self._weight_text(product)
            lines.append({
                'product_name': raw_name,
                'product_name_main': name_main,
                'product_name_sub': name_sub,
                'cooking_instructions': cooking,
                'cooking_instructions_html': cooking,
                'ingredients': ingredients,
                'ingredients_html': ingredients,
                # Fixed legal text (not product fields)
                'allergen_notice': "Allergens including Gluten are in <b>Bold</b>",
                'advisory_notice': "Although every effort has been made to remove bones, some may remain.",
                'storage_notice': "Store at or below 5°C.",
                'freezing_notice': "Use by date shown on label or if freezing we recommend freezing on day of purchase.",
                'catch_info': fish_info.split('\n')[0].strip() if fish_info else '',
                'production_date_display': '',
                'use_by_display': self._get_expiry_display(product),
                'min_weight_display': f"Min Weight: {weight}" if weight else '',
                'nutrition_html': self._product_field(product, 'nutritional_info_html'),
                'company_address': self._company_address(),
            })
        return self._apply_copies(lines)

    def _get_chilled_front_sleeve_label_data(self):
        """Chilled Front Sleeve Label - one entry per product."""
        self.ensure_one()
        lines = []
        for product in self._get_label_products():
            cooking_html = self._product_field(product, 'cooking_instructions_html')
            lines.append({
                'product_name': (product.name or '').strip(),
                'cooking_instructions': self._product_field(product, 'cooking_instructions') or cooking_html,
                'cooking_instructions_html': cooking_html,
                'production_date_display': '',
                'use_by_display': self._get_expiry_display(product),
            })
        return self._apply_copies(lines)

    def _get_chilled_back_sleeve_label_data(self):
        """Chilled Back Sleeve Label - one entry per product."""
        self.ensure_one()
        lines = []
        for product in self._get_label_products():
            ingredients = self._product_field(product, 'ingredients_html')
            cooking = self._product_field(product, 'cooking_instructions_html')
            weight = self._product_field(product, 'gross_net_weight') or self._weight_text(product)
            lines.append({
                'product_name': (product.name or '').strip(),
                'ingredients': ingredients,
                'ingredients_html': ingredients,
                'allergy_advice': self._product_field(product, 'allergens_notice'),
                'cooking_instructions': cooking,
                'cooking_instructions_html': cooking,
                'product_weight_display': weight,
                'weight_display': weight,
                'nutrition_html': self._product_field(product, 'nutritional_info_html'),
            })
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
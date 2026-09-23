# -*- coding: utf-8 -*-
import base64
import re
from datetime import timedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class ProductionLabelWizard(models.TransientModel):
    _name = 'production.label.wizard'
    _description = 'Production Label Wizard'

    delivery_channel = fields.Selection(
        selection=[
            ('regal_van', 'Regal Van Delivery'),
            ('courier', 'Courier Delivery'),
        ],
        string='Delivery Channel',
        required=True,
        default='regal_van',
        help="Select delivery channel for the production labels."
    )

    def _default_packing_date(self):
        return fields.Date.context_today(self) - timedelta(days=1)

    delivery_date_from = fields.Date(
        string='Delivery Date From',
        required=True,
        default=fields.Date.context_today,
        help="Starting delivery date for production label selection."
    )
    delivery_date_to = fields.Date(
        string='Delivery Date To',
        required=True,
        default=fields.Date.context_today,
        help="Ending delivery date for production label selection."
    )
    packing_date_from = fields.Date(
        string='Packing Date From',
        default=_default_packing_date,
        help="Starting packing date for production label selection."
    )
    packing_date_to = fields.Date(
        string='Packing Date To',
        default=_default_packing_date,
        help="Ending packing date for production label selection."
    )

    @api.model
    def _default_depot_ids(self):
        return self.env['stock.warehouse'].search([])

    depot_ids = fields.Many2many(
        'stock.warehouse',
        'production_label_wizard_warehouse_rel',
        'wizard_id',
        'warehouse_id',
        string='Depot',
        default=_default_depot_ids,
        help="Select one or more depots. Leave unselected to include all depots."
    )
    include_late_orders = fields.Boolean(
        string='Late Order',
        default=False,
        help="When unchecked, normal labels are generated. When checked, late order labels are generated."
    )

    category_id = fields.Many2one(
        'product.category',
        string='Category',
        required=True,
        help="Select a single product category to include in the labels and, for "
             "Frozen/Chilled/Fresh, to choose the matching label layout below. "
             "A category must be selected before labels can be printed."
    )

    category_name = fields.Char(
        related='category_id.name',
        store=False,
    )

    frozen_label_type = fields.Selection(
        selection=[
            ('frozen_label', 'Frozen Label'),
            ('plain_frozen_label', 'Plain Frozen Label'),
            ('plain_label', 'Plain Label'),
        ],
        string='Label Format',
        default='frozen_label',
        help="Label layout to print when Category is 'Frozen'."
    )

    chilled_label_type = fields.Selection(
        selection=[
            ('front_sleeve_label', 'Front Sleeve Label'),
            ('back_sleeve_label', 'Back Sleeve Label'),
        ],
        string='Label Template',
        default='front_sleeve_label',
        help="Label layout to print when Category is 'Chilled'."
    )

    fresh_label_type = fields.Selection(
        selection=[
            ('fresh_label', 'Fresh Label'),
        ],
        string='Label Format',
        default='fresh_label',
        help="Label layout to print when Category is 'Fresh'."
    )

    def _get_selected_label_type(self):
        self.ensure_one()
        category_name = self.category_id.name if self.category_id else False
        if category_name == 'Frozen':
            return self.frozen_label_type
        if category_name == 'Chilled':
            return self.chilled_label_type
        if category_name == 'Fresh':
            return self.fresh_label_type
        return False

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
        """Returns the eligible sale.order recordset based on current wizard filters."""
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
        """Domain for draft/confirmed Manufacturing Orders matching wizard filters."""
        self.ensure_one()
        if self.delivery_channel == 'courier':
            return [
                ('state', 'in', ('draft', 'confirmed')),
                ('delivery_channel', '=', 'courier'),
                ('delivery_date', '>=', self.delivery_date_from),
                ('delivery_date', '<=', self.delivery_date_to),
                ('is_late_order', '=', self.include_late_orders),
            ]

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

    def action_print_label(self):
        """Generates and downloads the label PDF matching the selected category and format."""
        self.ensure_one()

        if not self.category_id:
            raise UserError(_("Please select a Category before printing labels."))

        if self.category_name == 'Frozen':
            if self.frozen_label_type == 'frozen_label':
                report_model = self.env['report.tl_rf_reports.report_production_label_document_frozen']
                filename_suffix = 'Frozen'
            elif self.frozen_label_type == 'plain_frozen_label':
                report_model = self.env['report.tl_rf_reports.report_production_label_plain_frozen']
                filename_suffix = 'Plain_Frozen'
            elif self.frozen_label_type == 'plain_label':
                report_model = self.env['report.tl_rf_reports.report_production_label_plain']
                filename_suffix = 'Plain_Label'
            else:
                raise UserError(_(
                    "The '%s' label format is not implemented yet.",
                    dict(self._fields['frozen_label_type'].selection).get(self.frozen_label_type, self.frozen_label_type),
                ))
        elif self.category_name == 'Chilled':
            if self.chilled_label_type == 'front_sleeve_label':
                report_model = self.env['report.tl_rf_reports.report_production_label_chilled_front']
                filename_suffix = 'Chilled_Front_Sleeve'
            elif self.chilled_label_type == 'back_sleeve_label':
                report_model = self.env['report.tl_rf_reports.report_production_label_chilled_back']
                filename_suffix = 'Chilled_Back_Sleeve'
            else:
                raise UserError(_(
                    "The '%s' label format is not implemented yet.",
                    dict(self._fields['chilled_label_type'].selection).get(self.chilled_label_type, self.chilled_label_type),
                ))
        elif self.category_name == 'Fresh':
            if self.fresh_label_type != 'fresh_label':
                raise UserError(_(
                    "The '%s' label format is not implemented yet.",
                    dict(self._fields['fresh_label_type'].selection).get(self.fresh_label_type, self.fresh_label_type),
                ))
            if self.delivery_channel == 'courier':
                report_model = self.env['report.tl_rf_reports.report_production_label_document_courier']
                filename_suffix = 'Courier'
            else:
                report_model = self.env['report.tl_rf_reports.report_production_label_document_regal_van']
                filename_suffix = 'Regal_Van'
        elif self.delivery_channel == 'courier':
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

        for order in orders:
            batch = order.batch_id
            warehouse = batch.depot_id if batch else False

            for line in order.order_line:
                product = line.product_id

                if not product or not product.categ_id:
                    continue

                if self.category_id and product.categ_id.id != self.category_id.id:
                    continue

                use_by_date = False
                if order.delivery_date and product.expiration_time:
                    use_by_date = order.delivery_date + timedelta(days=product.expiration_time)

                line_data = {
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
                    'use_by_display': (
                        use_by_date.strftime('%d %B %Y')
                        if use_by_date else ''
                    ),
                }
                line_data.update(self._get_frozen_label_fields(order, product, use_by_date))
                label_lines.append(line_data)

        return label_lines

    def _get_frozen_label_fields(self, order, product, use_by_date):
        """Returns the extra dict keys needed by the Frozen Label report."""
        template = getattr(product, 'product_tmpl_id', product)

        # Latin / Species Name
        latin_name = ''
        species = getattr(product, 'species_id', False) or getattr(template, 'species_id', False)
        if species and hasattr(species, 'name') and species.name:
            latin_name = species.name
        if not latin_name:
            latin_name = getattr(product, 'latin_name', '') or getattr(template, 'latin_name', '') or ''

        # Product Origin
        origin_val = getattr(product, 'origin_country', '') or getattr(template, 'origin_country', '') or ''
        fao_area = getattr(product, 'fao_catch_area', '') or getattr(template, 'fao_catch_area', '') or ''
        catch_method = getattr(product, 'catch_method', '') or getattr(template, 'catch_method', '') or ''

        if origin_val:
            origin_display = origin_val
            if fao_area and f"FAO {fao_area}" not in origin_display:
                origin_display = f"{origin_display} (FAO {fao_area})"
        elif catch_method:
            origin_display = catch_method
            if product.origin_country:
                origin_display = f"{origin_display} in {product.origin_country}"
            if fao_area:
                origin_display = f"{origin_display} (FAO {fao_area})"
        else:
            fish_info = getattr(product, 'fish_info', '') or getattr(template, 'fish_info', '') or ''
            origin_display = fish_info.split('\n')[0].strip() if fish_info else ''

        # Description
        label_description = (
            getattr(product, 'packing_info', '')
            or getattr(template, 'packing_info', '')
            or getattr(product, 'label_description', '')
            or getattr(template, 'label_description', '')
            or ''
        )
        if not label_description and hasattr(product, 'product_template_attribute_value_ids'):
            attribute_names = product.product_template_attribute_value_ids.mapped('name')
            if attribute_names:
                label_description = ', '.join(attribute_names)
        if label_description and not label_description.endswith('.'):
            label_description += '.'

        # Product Weight
        weight_range = (
            getattr(product, 'gross_net_weight', '')
            or getattr(template, 'gross_net_weight', '')
            or getattr(product, 'weight_range', '')
            or getattr(template, 'weight_range', '')
            or ''
        )
        if not weight_range and product.weight:
            weight_range = f"{product.weight} kg"

        # Allergens
        allergens_display = (
            getattr(product, 'allergens_notice', '')
            or getattr(template, 'allergens_notice', '')
            or ''
        )
        if not allergens_display and hasattr(product, 'allergen_ids') and product.allergen_ids:
            allergens_display = ', '.join(product.allergen_ids.mapped('name'))
        if not allergens_display:
            allergens_display = getattr(product, 'allergens', '') or getattr(template, 'allergens', '') or 'Fish'

        # Production Date
        manufactured_date = (
            getattr(order, 'packing_date', False)
            or (self.packing_date_from if hasattr(self, 'packing_date_from') and self.packing_date_from else False)
            or (order.delivery_date - timedelta(days=1) if order and order.delivery_date else False)
            or fields.Date.context_today(self)
        )

        # Use By Date
        exp_duration = (
            getattr(product, 'use_frozen_days', 0)
            or getattr(template, 'use_frozen_days', 0)
            or getattr(product, 'expiration_time', 0)
            or getattr(template, 'expiration_time', 0)
            or getattr(product, 'expiration_duration', 0)
            or getattr(template, 'expiration_duration', 0)
            or 0
        )

        if manufactured_date and exp_duration:
            calculated_use_by = manufactured_date + timedelta(days=exp_duration)
        elif use_by_date:
            calculated_use_by = use_by_date
        elif order and order.delivery_date and getattr(template, 'use_fresh_days', 0):
            calculated_use_by = order.delivery_date + timedelta(days=template.use_fresh_days)
        elif manufactured_date:
            calculated_use_by = manufactured_date + timedelta(days=4)
        else:
            calculated_use_by = False

        return {
            'latin_name': latin_name,
            'origin_display': origin_display,
            'label_description': label_description,
            'weight_range': weight_range,
            'allergens_display': allergens_display,
            'production_date_display': (
                manufactured_date.strftime('%d %B, %Y') if manufactured_date else ''
            ),
            'frozen_use_by_display': (
                calculated_use_by.strftime('%d %B, %Y') if calculated_use_by else ''
            ),
        }

    def _get_plain_frozen_label_data(self):
        """Fetches label data for Plain Frozen Product Labels from matching Manufacturing Orders (MOs).
        Applies filters: Delivery Date From/To, Product Category, Depot, Late Orders.
        """
        self.ensure_one()
        label_lines = []
        domain = self._get_production_domain()
        productions = self.env['mrp.production'].search(domain)

        # Process matching Manufacturing Orders
        for mo in productions:
            mo_created_date = (
                mo.create_date.date() if mo.create_date
                else (self.packing_date_from or fields.Date.context_today(self))
            )

            # Check raw material component lines (move_raw_ids) if MO is a composite/generic pack
            matching_moves = mo.move_raw_ids.filtered(
                lambda m: not self.category_id or m.product_id.categ_id.id == self.category_id.id
            ) if mo.move_raw_ids else self.env['stock.move']

            if matching_moves:
                for move in matching_moves:
                    label_data = self._build_plain_frozen_label_dict(move.product_id, mo_created_date, mo)
                    label_lines.append(label_data)
            elif mo.product_id and (not self.category_id or mo.product_id.categ_id.id == self.category_id.id or mo.product_category_id.id == self.category_id.id):
                label_data = self._build_plain_frozen_label_dict(mo.product_id, mo_created_date, mo)
                label_lines.append(label_data)

        # Fallback to matching Sales Orders if no MOs found, ensuring preview/print consistency
        if not label_lines:
            orders = self._get_matching_orders()
            for order in orders:
                mo_date = (
                    getattr(order, 'packing_date', False)
                    or (order.delivery_date - timedelta(days=1) if order.delivery_date else False)
                    or fields.Date.context_today(self)
                )
                for line in order.order_line:
                    product = line.product_id
                    if not product or not product.categ_id:
                        continue
                    if self.category_id and product.categ_id.id != self.category_id.id:
                        continue
                    label_data = self._build_plain_frozen_label_dict(product, mo_date)
                    label_lines.append(label_data)

        return label_lines

    def _build_plain_frozen_label_dict(self, product, mo_created_date, mo=None):
        """Constructs a dictionary of all fields required by the Plain Frozen Product Label template."""
        template = getattr(product, 'product_tmpl_id', product)

        # 1. Product Name
        product_name = (product.name or '').upper()

        # 2. Latin / Scientific Name / Origin
        species = getattr(product, 'species_id', False) or getattr(template, 'species_id', False)
        latin_name = ''
        if species and hasattr(species, 'name') and species.name:
            latin_name = species.name
        if not latin_name:
            latin_name = getattr(product, 'latin_name', '') or getattr(template, 'latin_name', '') or ''
        if not latin_name:
            latin_name = getattr(product, 'origin_country', '') or getattr(template, 'origin_country', '') or ''

        # 3. Ingredients (with BOLD allergens)
        ingredients_html = (
            getattr(product, 'ingredients_html', '')
            or getattr(template, 'ingredients_html', '')
            or ''
        )
        if not ingredients_html:
            allergens_notice = getattr(product, 'allergens_notice', '') or getattr(template, 'allergens_notice', '') or ''
            if allergens_notice:
                ingredients_html = f"Cod <b>({allergens_notice.upper()})</b>, water as protective glaze."
            else:
                ingredients_html = "Cod <b>(FISH)</b>, water as protective glaze."

        # 4. Storage Instructions
        storage_instructions = "Store at below -18°C.  Once defrosted do not refreeze"

        # 5. Catch Area
        fao_area = getattr(product, 'fao_catch_area', '') or getattr(template, 'fao_catch_area', '') or ''
        catch_method = getattr(product, 'catch_method', '') or getattr(template, 'catch_method', '') or ''
        origin_country = getattr(product, 'origin_country', '') or getattr(template, 'origin_country', '') or ''

        if catch_method or fao_area:
            catch_text = catch_method or 'Longline caught'
            if origin_country:
                catch_text += f" in the {origin_country}" if "in" not in catch_text.lower() else f" {origin_country}"
            else:
                catch_text += " in the Pacific Ocean" if "ocean" not in catch_text.lower() else ""
            if fao_area:
                catch_text += f", FAO {fao_area}."
            else:
                catch_text += ", FAO 61."
        else:
            fish_info = getattr(product, 'fish_info', '') or getattr(template, 'fish_info', '') or ''
            if fish_info and ('fao' in fish_info.lower() or 'caught' in fish_info.lower()):
                catch_text = fish_info.split('\n')[0].strip()
            else:
                catch_text = "Catch Area: Longline caught in the Pacific Ocean, FAO 61."

        # 6. Freeze Date: Manufacturing Order Created Date (DD.MM.YYYY)
        freeze_date_display = mo_created_date.strftime('%d.%m.%Y') if mo_created_date else ''

        # 7. Best Before Date: MO Created Date + Product Expiration Duration
        exp_days = (
            getattr(product, 'use_frozen_days', 0)
            or getattr(template, 'use_frozen_days', 0)
            or getattr(product, 'expiration_time', 0)
            or getattr(template, 'expiration_time', 0)
            or getattr(product, 'expiration_duration', 0)
            or getattr(template, 'expiration_duration', 0)
            or 0
        )
        use_frozen_text = str(getattr(product, 'use_frozen', '') or getattr(template, 'use_frozen', '') or '')

        if exp_days:
            best_before_dt = mo_created_date + timedelta(days=exp_days)
        elif 'year' in use_frozen_text.lower():
            m = re.search(r'(\d+)\s*year', use_frozen_text.lower())
            years = int(m.group(1)) if m else 2
            best_before_dt = mo_created_date + timedelta(days=years * 365)
        elif 'month' in use_frozen_text.lower():
            m = re.search(r'(\d+)\s*month', use_frozen_text.lower())
            months = int(m.group(1)) if m else 24
            best_before_dt = mo_created_date + timedelta(days=months * 30)
        else:
            # Default frozen expiration period: 2 Years
            best_before_dt = mo_created_date + timedelta(days=730)

        best_before_display = best_before_dt.strftime('%B %Y') if best_before_dt else ''

        # 8. Company Information
        company = self.env.company
        address_parts = [
            company.name,
            company.street,
            company.street2,
            company.city,
            company.state_id.name if company.state_id else False,
            company.zip,
        ]
        company_address = ', '.join(part for part in address_parts if part)
        if not company_address:
            company_address = "Regal Fish Supplies Ltd, Thorold Street, Grimsby, DN31 3AL"

        return {
            'product_name': product_name,
            'latin_name': latin_name,
            'origin': latin_name,
            'ingredients': ingredients_html,
            'ingredients_html': ingredients_html,
            'storage_instructions': storage_instructions,
            'catch_area': catch_text,
            'freeze_date_display': freeze_date_display,
            'best_before_display': best_before_display,
            'company_address': company_address,
        }

    def _get_plain_label_data(self):
        """Fetches label data for Plain Product Labels (Frozen) from matching Manufacturing Orders (MOs).
        Applies filters: Delivery Date From/To, Product Category, Depot, Late Orders.
        """
        self.ensure_one()
        label_lines = []
        domain = self._get_production_domain()
        productions = self.env['mrp.production'].search(domain)

        # Process matching Manufacturing Orders
        for mo in productions:
            mo_created_date = (
                mo.create_date.date() if mo.create_date
                else (self.packing_date_from or fields.Date.context_today(self))
            )

            # Check raw material component lines (move_raw_ids) if MO is a composite/generic pack
            matching_moves = mo.move_raw_ids.filtered(
                lambda m: not self.category_id or m.product_id.categ_id.id == self.category_id.id
            ) if mo.move_raw_ids else self.env['stock.move']

            if matching_moves:
                for move in matching_moves:
                    label_data = self._build_plain_label_dict(move.product_id, mo_created_date, mo)
                    label_lines.append(label_data)
            elif mo.product_id and (not self.category_id or mo.product_id.categ_id.id == self.category_id.id or mo.product_category_id.id == self.category_id.id):
                label_data = self._build_plain_label_dict(mo.product_id, mo_created_date, mo)
                label_lines.append(label_data)

        # Fallback to matching Sales Orders if no MOs found, ensuring preview/print consistency
        if not label_lines:
            orders = self._get_matching_orders()
            for order in orders:
                mo_date = (
                    getattr(order, 'packing_date', False)
                    or (order.delivery_date - timedelta(days=1) if order.delivery_date else False)
                    or fields.Date.context_today(self)
                )
                for line in order.order_line:
                    product = line.product_id
                    if not product or not product.categ_id:
                        continue
                    if self.category_id and product.categ_id.id != self.category_id.id:
                        continue
                    label_data = self._build_plain_label_dict(product, mo_date)
                    label_lines.append(label_data)

        return label_lines

    def _build_plain_label_dict(self, product, mo_created_date, mo=None):
        """Constructs a dictionary of all fields required by the Plain Label (Frozen) template."""
        template = getattr(product, 'product_tmpl_id', product)

        # 1. Product Name (split into main name and subtitle if applicable)
        raw_name = (product.name or '').strip()
        product_name_main = raw_name
        product_name_sub = ''

        if '\n' in raw_name:
            parts = raw_name.split('\n', 1)
            product_name_main = parts[0].strip()
            product_name_sub = parts[1].strip()
        elif ' with ' in raw_name.lower():
            idx = raw_name.lower().index(' with ')
            product_name_main = raw_name[:idx].strip()
            product_name_sub = raw_name[idx+1:].strip()  # 'with ...'
        elif ' - ' in raw_name:
            parts = raw_name.split(' - ', 1)
            product_name_main = parts[0].strip()
            product_name_sub = parts[1].strip()

        # 2. Cooking Instructions - fetched straight from the product's (or
        # template's) cooking_instructions_html field. No hardcoded recipe
        # text: if the field is empty, the section is left blank.
        cooking_html = (
            getattr(product, 'cooking_instructions_html', '')
            or getattr(template, 'cooking_instructions_html', '')
            or ''
        )
        # cooking_heading = "Oven Bake from chilled:"
        cooking_instructions = cooking_html

        # 3. Ingredients (with BOLD allergens) - fetched straight from the
        # product's (or template's) ingredients_html field. No hardcoded
        # ingredient list: if the field is empty, the section is left blank.
        ingredients_html = (
            getattr(product, 'ingredients_html', '')
            or getattr(template, 'ingredients_html', '')
            or ''
        )

        # 4. Hardcoded Notices
        allergen_notice = "Allergens including Gluten are in <b>Bold</b>"
        advisory_notice = "Although every effort has been made to remove bones, some may remain."

        # 5. Catch Info - fetched straight from the product's (or template's)
        # fish_info field. No hardcoded catch-area text: if the field is
        # empty, the section is left blank.
        fish_info = getattr(product, 'fish_info', '') or getattr(template, 'fish_info', '') or ''
        catch_info = fish_info.split('\n')[0].strip() if fish_info else ''

        # 6. Hardcoded Storage & Freezing Notices (Bold)
        storage_notice = "Store at or below 5°C."
        freezing_notice = "Use by date shown on label or if freezing we recommend freezing on day of purchase."

        # 7. Production Date: MO Created Date (DD MMMM, YYYY e.g. "15 September, 2026")
        production_date_display = mo_created_date.strftime('%d %B, %Y') if mo_created_date else ''

        # 8. Use By Date: MO Created Date + Product Expiration Duration (DD MMMM, YYYY e.g. "18 September, 2026")
        # No fabricated fallback duration - if the product has no
        # expiration field set, no Use By date is calculated/printed.
        exp_days = (
            getattr(product, 'use_frozen_days', 0)
            or getattr(template, 'use_frozen_days', 0)
            or getattr(product, 'expiration_time', 0)
            or getattr(template, 'expiration_time', 0)
            or getattr(product, 'expiration_duration', 0)
            or getattr(template, 'expiration_duration', 0)
            or getattr(product, 'use_fresh_days', 0)
            or getattr(template, 'use_fresh_days', 0)
            or 0
        )
        use_by_dt = mo_created_date + timedelta(days=exp_days) if (mo_created_date and exp_days) else False
        use_by_display = use_by_dt.strftime('%d %B, %Y') if use_by_dt else ''

        # 9. Product Weight (e.g. "Min Weight: 1.00 kg") - taken from the
        # Manufacturing Order's Quantity (product_qty) and its Unit of
        # Measure (product_uom_id), NOT from the product's own Inventory >
        # Weight field. If there's no MO (e.g. the Sales Order fallback
        # path below, which has no MO to read a quantity from), no Min
        # Weight line is printed rather than falling back to product.weight.
        if mo and mo.product_qty and mo.product_uom_id:
            min_weight_display = f"Min Weight: {mo.product_qty:.2f} {mo.product_uom_id.name}"
        else:
            min_weight_display = ''

        # 10. Product Nutrition - sourced from the product's (or its template's)
        # Nutrition field. No hardcoded/fabricated nutrition values: if the
        # field is empty, the label simply prints nothing for this section
        # rather than a fake per-100g breakdown.
        nutrition_html = (
            getattr(product, 'nutritional_info_html', '')
            or getattr(template, 'nutritional_info_html', '')
            or ''
        )

        # 11. Company Address (Footer) - fetched from the company record,
        # no hardcoded address text.
        company = self.env.company
        address_parts = [
            company.name,
            company.street,
            company.street2,
            company.city,
            company.state_id.name if company.state_id else False,
            company.zip,
        ]
        company_address = ', '.join(part for part in address_parts if part)

        return {
            'product_name': raw_name,
            'product_name_main': product_name_main,
            'product_name_sub': product_name_sub,
            # 'cooking_heading': cooking_heading,
            'cooking_instructions': cooking_instructions,
            'cooking_instructions_html': cooking_html,
            'ingredients': ingredients_html,
            'ingredients_html': ingredients_html,
            'allergen_notice': allergen_notice,
            'advisory_notice': advisory_notice,
            'catch_info': catch_info,
            'storage_notice': storage_notice,
            'freezing_notice': freezing_notice,
            'production_date_display': production_date_display,
            'use_by_display': use_by_display,
            'min_weight_display': min_weight_display,
            'nutrition_html': nutrition_html,
            'company_address': company_address,
        }

    def _get_chilled_front_sleeve_label_data(self):
        """Fetches label data for Chilled Front Sleeve Labels from matching Manufacturing Orders (MOs).
        Applies filters: Delivery Date From/To, Product Category, Depot, Late Orders.
        """
        self.ensure_one()
        label_lines = []
        domain = self._get_production_domain()
        productions = self.env['mrp.production'].search(domain)

        # Process matching Manufacturing Orders
        for mo in productions:
            mo_created_date = (
                mo.create_date.date() if mo.create_date
                else (self.packing_date_from or fields.Date.context_today(self))
            )

            # Check raw material component lines (move_raw_ids) if MO is a composite/generic pack
            matching_moves = mo.move_raw_ids.filtered(
                lambda m: not self.category_id or m.product_id.categ_id.id == self.category_id.id
            ) if mo.move_raw_ids else self.env['stock.move']

            if matching_moves:
                for move in matching_moves:
                    label_data = self._build_chilled_front_sleeve_label_dict(move.product_id, mo_created_date, mo)
                    label_lines.append(label_data)
            elif mo.product_id and (not self.category_id or mo.product_id.categ_id.id == self.category_id.id or mo.product_category_id.id == self.category_id.id):
                label_data = self._build_chilled_front_sleeve_label_dict(mo.product_id, mo_created_date, mo)
                label_lines.append(label_data)

        # Fallback to matching Sales Orders if no MOs found, ensuring preview/print consistency
        if not label_lines:
            orders = self._get_matching_orders()
            for order in orders:
                mo_date = (
                    getattr(order, 'packing_date', False)
                    or (order.delivery_date - timedelta(days=1) if order.delivery_date else False)
                    or fields.Date.context_today(self)
                )
                for line in order.order_line:
                    product = line.product_id
                    if not product or not product.categ_id:
                        continue
                    if self.category_id and product.categ_id.id != self.category_id.id:
                        continue
                    label_data = self._build_chilled_front_sleeve_label_dict(product, mo_date)
                    label_lines.append(label_data)

        return label_lines

    def _build_chilled_front_sleeve_label_dict(self, product, mo_created_date, mo=None):
        """Constructs a dictionary of all fields required by the Chilled Front Sleeve Label template."""
        template = getattr(product, 'product_tmpl_id', product)

        # 1. Product Name
        product_name = (product.name or '').strip()

        # 2. Cooking Instructions - fetched dynamically from the product's cooking_instructions_html
        cooking_html = (
            getattr(product, 'cooking_instructions_html', '')
            or getattr(template, 'cooking_instructions_html', '')
            or ''
        )
        cooking_instructions = (
            getattr(product, 'cooking_instructions', '')
            or getattr(template, 'cooking_instructions', '')
            or cooking_html
        )

        # 3. Production Date: MO Created Date (DD MMMM, YYYY e.g. "15 September, 2026")
        production_date_display = mo_created_date.strftime('%d %B, %Y') if mo_created_date else ''

        # 4. Expiry Date: MO Created Date + Product Expiration Duration (use_fresh_days, expiration_time, expiration_duration)
        exp_days = (
            getattr(product, 'use_fresh_days', 0)
            or getattr(template, 'use_fresh_days', 0)
            or getattr(product, 'expiration_time', 0)
            or getattr(template, 'expiration_time', 0)
            or getattr(product, 'expiration_duration', 0)
            or getattr(template, 'expiration_duration', 0)
            or getattr(product, 'use_frozen_days', 0)
            or getattr(template, 'use_frozen_days', 0)
            or 3  # Standard 3-day chilled duration if unspecified
        )
        use_by_dt = mo_created_date + timedelta(days=exp_days) if (mo_created_date and exp_days) else False
        use_by_display = use_by_dt.strftime('%d %B, %Y') if use_by_dt else ''

        return {
            'product_name': product_name,
            'cooking_instructions': cooking_instructions,
            'cooking_instructions_html': cooking_html,
            'production_date_display': production_date_display,
            'use_by_display': use_by_display,
        }

    def _get_chilled_back_sleeve_label_data(self):
        """Fetches label data for Chilled Back Sleeve Labels from matching Manufacturing Orders (MOs).
        Applies filters: Delivery Date From/To, Product Category, Depot, Late Orders.
        """
        self.ensure_one()
        label_lines = []
        domain = self._get_production_domain()
        productions = self.env['mrp.production'].search(domain)

        # Process matching Manufacturing Orders
        for mo in productions:
            mo_created_date = (
                mo.create_date.date() if mo.create_date
                else (self.packing_date_from or fields.Date.context_today(self))
            )

            # Check raw material component lines (move_raw_ids) if MO is a composite/generic pack
            matching_moves = mo.move_raw_ids.filtered(
                lambda m: not self.category_id or m.product_id.categ_id.id == self.category_id.id
            ) if mo.move_raw_ids else self.env['stock.move']

            if matching_moves:
                for move in matching_moves:
                    label_data = self._build_chilled_back_sleeve_label_dict(move.product_id, mo_created_date, mo)
                    label_lines.append(label_data)
            elif mo.product_id and (not self.category_id or mo.product_id.categ_id.id == self.category_id.id or mo.product_category_id.id == self.category_id.id):
                label_data = self._build_chilled_back_sleeve_label_dict(mo.product_id, mo_created_date, mo)
                label_lines.append(label_data)

        # Fallback to matching Sales Orders if no MOs found, ensuring preview/print consistency
        if not label_lines:
            orders = self._get_matching_orders()
            for order in orders:
                mo_date = (
                    getattr(order, 'packing_date', False)
                    or (order.delivery_date - timedelta(days=1) if order.delivery_date else False)
                    or fields.Date.context_today(self)
                )
                for line in order.order_line:
                    product = line.product_id
                    if not product or not product.categ_id:
                        continue
                    if self.category_id and product.categ_id.id != self.category_id.id:
                        continue
                    label_data = self._build_chilled_back_sleeve_label_dict(product, mo_date)
                    label_lines.append(label_data)

        return label_lines

    def _build_chilled_back_sleeve_label_dict(self, product, mo_created_date, mo=None):
        """Constructs a dictionary of all fields required by the Chilled Back Sleeve Label template."""
        template = getattr(product, 'product_tmpl_id', product)

        # 1. Product Name
        product_name = (product.name or '').strip()

        # 2. Ingredients (HTML/Text)
        ingredients_html = (
            getattr(product, 'ingredients_html', '')
            or getattr(template, 'ingredients_html', '')
            or ''
        )
        if not ingredients_html:
            # Fallback based on species / product name if empty
            species_name = (
                getattr(getattr(product, 'species_id', False), 'name', '')
                or getattr(getattr(template, 'species_id', False), 'name', '')
                or getattr(product, 'latin_name', '')
                or getattr(template, 'latin_name', '')
                or 'Salmo Salar'
            )
            allergens_notice = getattr(product, 'allergens_notice', '') or getattr(template, 'allergens_notice', '') or 'Fish'
            ingredients_html = (
                f"Salmon (<i>{species_name}</i>) (<b>{allergens_notice.upper() if allergens_notice else 'FISH'}</b>) 90%, "
                "Mint Glaze 10%, Sugar, Acids (Sodium Diacetate, Malic Acid), Dried Glucose Syrup, Modified Starch, Salt, "
                "Dried Mint (3.6%), Yeast Extract (Yeast Extract, Salt), Dried Tomato, Colours (Paprika Extract and Natural "
                "Rosemary Flavouring, Curcumin), Natural Flavouring, Thickeners (Xanthan Gum, Guar Gum) Natural Garden Mint Flavouring."
            )

        # 3. Allergy Advice - fetched straight from the product's (or
        # template's) allergens_notice field. No hardcoded text: if the
        # field is empty, the section is left blank.
        allergy_advice = (
            getattr(product, 'allergens_notice', '')
            or getattr(template, 'allergens_notice', '')
            or ''
        )

        # 4. Cooking Instructions
        cooking_html = (
            getattr(product, 'cooking_instructions_html', '')
            or getattr(template, 'cooking_instructions_html', '')
            or ''
        )
        if not cooking_html:
            cooking_html = (
                "<b>Oven:</b> Pierce film and place in a pre-heated oven at 200°C for approx 20-25 minutes (chilled), 25-30 minutes (frozen).<br/>"
                "<b>Microwave: (850w):</b> Pierce film several times and cook on full power for 3-4 minutes (chilled), 5-6 minutes (frozen).<br/>"
                "Remove from packaging and serve."
            )

        # 5. Product Weight (dynamically populated from MO Quantity and Unit)
        if mo and mo.product_qty:
            qty = mo.product_qty
            uom_name = mo.product_uom_id.name if mo.product_uom_id else 'g'
            # If UoM is kg and qty < 1, e.g. 0.25 kg -> 250g
            if uom_name.lower() in ('kg', 'kgs') and qty < 1:
                weight_val = int(qty * 1000) if (qty * 1000).is_integer() else (qty * 1000)
                product_weight_display = f"{weight_val}g"
            else:
                formatted_qty = int(qty) if float(qty).is_integer() else f"{qty:.2f}".rstrip('0').rstrip('.')
                product_weight_display = f"{formatted_qty}{uom_name}"
        else:
            # Fallback if product has weight or gross_net_weight
            gross_net = getattr(product, 'gross_net_weight', '') or getattr(template, 'gross_net_weight', '')
            if gross_net:
                product_weight_display = gross_net
            elif product.weight:
                w = product.weight
                if w < 1:
                    product_weight_display = f"{int(w * 1000) if (w * 1000).is_integer() else w * 1000}g"
                else:
                    product_weight_display = f"{int(w) if w.is_integer() else w}kg"
            else:
                product_weight_display = "250g"

        # 6. Nutritional Information - fetched straight from the product's
        # (or template's) nutritional_info_html field and printed as a
        # paragraph inside the Nutritional Information table. No hardcoded
        # values: if the field is empty, the table body is left blank.
        nutrition_html = (
            getattr(product, 'nutritional_info_html', '')
            or getattr(template, 'nutritional_info_html', '')
            or ''
        )

        return {
            'product_name': product_name,
            'ingredients': ingredients_html,
            'ingredients_html': ingredients_html,
            'allergy_advice': allergy_advice,
            'cooking_instructions': cooking_html,
            'cooking_instructions_html': cooking_html,
            'product_weight_display': product_weight_display,
            'weight_display': product_weight_display,
            'nutrition_html': nutrition_html,
        }
# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class MrpProductionLabelWizard(models.TransientModel):
    """Production Label wizard opened from the Manufacturing Order list view:
    Actions > Production Label.

    Inherits production.label.wizard (prototype inheritance), so every label
    builder, date rule and Sales Order lookup of the Round Management
    Production Label wizard is reused unchanged. Only two things differ:

    * Which MOs: the MOs selected in the list (instead of a delivery date /
      depot / channel search).
    * Which product: always the MO's main product (mo.product_id), never
      its component lines (move_raw_ids).

    The same 6 ReportLab reports print the labels, so the design (and the
    fit-to-one-page logic) is identical.
    """
    _name = 'mrp.production.label.wizard'
    _inherit = 'production.label.wizard'
    _description = 'Production Label Wizard (from Manufacturing Orders)'

    # Own relation table - the parent's table is tied to production.label.wizard.
    depot_ids = fields.Many2many(
        'stock.warehouse',
        'mrp_production_label_wizard_warehouse_rel',
        'wizard_id',
        'warehouse_id',
        string='Depot',
    )

    production_ids = fields.Many2many(
        'mrp.production',
        'mrp_production_label_wizard_production_rel',
        'wizard_id',
        'production_id',
        string='Manufacturing Orders',
    )
    copies = fields.Integer(
        string='Copies',
        default=1,
        required=True,
        help="Number of labels to print for each selected Manufacturing Order.",
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
        if ctx.get('active_model') == 'mrp.production' and ctx.get('active_ids'):
            productions = self.env['mrp.production'].browse(ctx['active_ids']).exists()
            res['production_ids'] = [(6, 0, productions.ids)]
            categories = productions.product_id.categ_id
            if len(categories) == 1:
                res['category_id'] = categories.id
            # Fresh label layout (Courier vs Regal Van) follows the MOs'
            # delivery channel: Courier only when every selected MO is courier.
            if 'delivery_channel' in productions._fields:
                channels = set(productions.mapped('delivery_channel'))
                res['delivery_channel'] = 'courier' if channels == {'courier'} else 'regal_van'
        # No packing date filter here - the production date comes from each
        # MO / its Sales Order (see _mo_packing_date).
        res['packing_date_from'] = False
        res['packing_date_to'] = False
        return res

    @api.depends('production_ids')
    def _compute_allowed_category_ids(self):
        for wizard in self:
            wizard.allowed_category_ids = wizard.production_ids.product_id.categ_id

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
    def _get_label_productions(self):
        """Selected MOs whose MAIN product belongs to the chosen category."""
        self.ensure_one()
        if not self.production_ids:
            raise UserError(_("Please select at least one Manufacturing Order."))
        productions = self.production_ids.filtered(
            lambda mo: mo.product_id and mo.product_id.categ_id == self.category_id
        ).sorted('id')
        if not productions:
            raise UserError(_(
                "None of the selected Manufacturing Orders produce a product in the '%s' category.",
                self.category_id.display_name,
            ))
        return productions

    def _apply_copies(self, label_lines):
        """Repeat each label 'copies' times (copies of one MO together)."""
        self.ensure_one()
        return [dict(line) for line in label_lines for _i in range(self.copies)]

    @staticmethod
    def _mo_created_date(mo):
        return mo.create_date.date() if mo.create_date else fields.Date.today()

    def _mo_links(self, mo):
        """(sale order, batch, warehouse, delivery date) of an MO - same
        lookup order as the Production Label wizard's Fresh label."""
        order = self._get_mo_sale_order(mo)
        batch = (order.batch_id if order else False) or getattr(mo, 'round_batch_id', False)
        warehouse = (batch.depot_id if batch else False) or getattr(mo, 'depot_id', False)
        delivery_date = (
            (order.delivery_date if order else False)
            or getattr(mo, 'delivery_date', False)
            or (batch.delivery_date if batch else False)
        )
        return order, batch, warehouse, delivery_date

    def _mo_packing_date(self, mo, delivery_date):
        """Packing date used as the Production Date on the Frozen label.
        In the Production Label wizard this is the Packing Date filter,
        which defaults to Delivery Date - 1 day. Here: Delivery Date - 1 day,
        else the MO created date."""
        if delivery_date:
            return delivery_date - timedelta(days=1)
        return self._mo_created_date(mo)

    # ------------------------------------------------------------------
    # Data - overrides of production.label.wizard.
    # Same builders, same date logic; MOs = the selected ones and
    # product = the MO's main product.
    # ------------------------------------------------------------------
    def _get_production_domain(self):
        # Used by the parent's _get_fresh_label_data(): only the selected MOs.
        self.ensure_one()
        return [('id', 'in', self._get_label_productions().ids)]

    def _get_matching_orders(self):
        # No Sales Order search - labels come from the selected MOs only.
        return self.env['sale.order']

    def _get_fresh_label_data(self):
        """Fresh Label - the parent's MO based logic, on the selected MOs."""
        return self._apply_copies(super()._get_fresh_label_data())

    def _get_label_data(self):
        """Frozen Label - one label per selected MO (main product). Same
        fields and date rules as the Production Label wizard's Sales
        Order line based Frozen label."""
        self.ensure_one()
        label_lines = []
        for mo in self._get_label_productions():
            product = mo.product_id
            order, batch, warehouse, delivery_date = self._mo_links(mo)

            use_by_date = False
            if delivery_date and product.expiration_time:
                use_by_date = delivery_date + timedelta(days=product.expiration_time)

            line_data = {
                'customer_name': (order.partner_id.name or '') if order else '',
                'customer_code': (order.partner_id.customer_code or '') if order else '',
                'round_name': order.round_id.name if order and order.round_id else '',
                'delivery_date_display': delivery_date.strftime('%a, %d %B %Y') if delivery_date else '',
                'delivery_day_display': delivery_date.strftime('%A') if delivery_date else '',
                'batch_code': batch.code if batch else '',
                'category_name': product.categ_id.name or '',
                'warehouse_name': warehouse.name if warehouse else '',
                'product_name': product.name or '',
                'origin_country': product.origin_country or '',
                'product_barcode': product.barcode or '',
                'product_default_code': product.default_code or '',
                'use_by_display': use_by_date.strftime('%d %B %Y') if use_by_date else '',
            }
            # The parent reads the Production Date from order.packing_date,
            # then the wizard's Packing Date. Set it per MO so each label gets
            # its own MO's date (transient record - cheap write).
            self.packing_date_from = self._mo_packing_date(mo, delivery_date)
            line_data.update(self._get_frozen_label_fields(order, product, use_by_date))
            label_lines.append(line_data)
        self.packing_date_from = False
        return self._apply_copies(label_lines)

    def _get_plain_frozen_label_data(self):
        """Plain Frozen Label - one label per selected MO (main product)."""
        self.ensure_one()
        lines = [
            self._build_plain_frozen_label_dict(mo.product_id, self._mo_created_date(mo), mo)
            for mo in self._get_label_productions()
        ]
        return self._apply_copies(lines)

    def _get_plain_label_data(self):
        """Plain Label - one label per selected MO (main product)."""
        self.ensure_one()
        lines = [
            self._build_plain_label_dict(mo.product_id, self._mo_created_date(mo), mo)
            for mo in self._get_label_productions()
        ]
        return self._apply_copies(lines)

    def _get_chilled_front_sleeve_label_data(self):
        """Chilled Front Sleeve Label - one label per selected MO (main product)."""
        self.ensure_one()
        lines = [
            self._build_chilled_front_sleeve_label_dict(mo.product_id, self._mo_created_date(mo), mo)
            for mo in self._get_label_productions()
        ]
        return self._apply_copies(lines)

    def _get_chilled_back_sleeve_label_data(self):
        """Chilled Back Sleeve Label - one label per selected MO (main product)."""
        self.ensure_one()
        lines = [
            self._build_chilled_back_sleeve_label_dict(mo.product_id, self._mo_created_date(mo), mo)
            for mo in self._get_label_productions()
        ]
        return self._apply_copies(lines)

    # ------------------------------------------------------------------
    # Print
    # ------------------------------------------------------------------
    def action_print_label(self):
        """Same report selection and download as the Production Label wizard.
        The PDF file name uses today's date (no delivery date filter here)."""
        self.ensure_one()
        self.delivery_date_from = fields.Date.context_today(self)
        return super().action_print_label()
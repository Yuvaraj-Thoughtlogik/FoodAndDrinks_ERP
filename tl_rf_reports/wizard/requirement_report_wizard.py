# -*- coding: utf-8 -*-
import base64
import io

from odoo import api, fields, models
from odoo.tools import _
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_compare, float_round


class RequirementReportWizard(models.TransientModel):
    _name = 'requirement.report.wizard'
    _description = 'Requirement Report Wizard'

    delivery_channel = fields.Selection(
        selection=[
            ('regal_van', 'Regal Van Delivery'),
            ('courier', 'Courier Delivery'),
            ('both', 'Both'),
        ],
        string='Delivery Channel',
        required=True,
        default='regal_van',
        help="Select delivery channel for the report. 'Both' prints the "
             "existing Regal Van and Courier reports one after the other, "
             "combined into a single PDF."
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
        'requirement_report_wizard_warehouse_rel',
        'wizard_id',
        'warehouse_id',
        string='Depot',
        default=_default_depot_ids,
        help="Select one or more depots. Leave unselected to include all depots."
    )

    @api.model
    def _default_categ_ids(self):
        return self.env['product.category'].search([('name', '=ilike', 'Fresh')])

    categ_ids = fields.Many2many(
        'product.category',
        'requirement_report_wizard_category_rel',
        'wizard_id',
        'category_id',
        string='Product Category',
        default=_default_categ_ids,
        help="Fresh is selected by default. Add or remove categories as required; "
             "leave empty to include all categories."
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
        van_domain = [('order_id.delivery_channel', 'in', ['regal_van', False])]
        if self.depot_ids:
            van_domain = ['&'] + van_domain + [('depot_id', 'in', self.depot_ids.ids)]
        courier_domain = [('order_id.delivery_channel', '=', 'courier')]

        if self.delivery_channel == 'courier':
            domain += courier_domain
        elif self.delivery_channel == 'both':
            # Courier lines always included; the depot filter only narrows Regal Van lines.
            domain += ['|'] + courier_domain + van_domain
        else:
            domain += van_domain

        if self.categ_ids:
            domain.append(('categ_id', 'in', self.categ_ids.ids))

        return domain

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

    def _get_channel_wizard(self, channel):
        """Returns a throwaway requirement.report.wizard record - a copy of
        this wizard with delivery_channel forced to a single real channel
        ('regal_van' or 'courier') - so the existing, unmodified per-channel
        report logic (_get_line_domain(), _get_report_values(), templates)
        can be reused as-is for each half of the 'Both' combined report."""
        self.ensure_one()
        return self.create({
            'delivery_channel': channel,
            'delivery_date_from': self.delivery_date_from,
            'delivery_date_to': self.delivery_date_to,
            'depot_ids': [(6, 0, self.depot_ids.ids)],
            'categ_ids': [(6, 0, self.categ_ids.ids)],
        })

    def action_print_report(self):
        """Validates matching orders/lines and triggers the Requirement PDF Report.

        Built directly with ReportLab (generate_pdf() on the matching report
        model) instead of QWeb+wkhtmltopdf - see report/requirement_report.py.
        Which report model is used still depends on delivery_channel exactly
        as before (Courier -> report_requirement_courier, Regal Van ->
        report_requirement); only how the PDF gets produced/returned changed.

        'Both' is handled separately by _action_print_combined_report()."""
        self.ensure_one()

        if self.delivery_channel == 'both':
            return self._action_print_combined_report()

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
            report_model = self.env['report.tl_rf_reports.report_requirement_courier']
            filename_prefix = 'Courier_Requirement_Report_'
        else:
            report_model = self.env['report.tl_rf_reports.report_requirement']
            filename_prefix = 'Requirement_Report_'

        pdf_content = report_model.generate_pdf(self)
        if not pdf_content:
            channel_name = dict(self._fields['delivery_channel'].selection).get(self.delivery_channel, '')
            raise UserError(_(
                "No confirmed %s order lines found with delivery dates between %s and %s."
            ) % (
                channel_name,
                self.delivery_date_from.strftime('%d/%m/%Y'),
                self.delivery_date_to.strftime('%d/%m/%Y'),
            ))

        return self._download_action(
            pdf_content, f"{filename_prefix}{self.delivery_date_from.strftime('%Y%m%d')}.pdf"
        )

    def _action_print_combined_report(self):
        """'Both': generates the Regal Van and Courier requirement reports
        separately, using their existing/unmodified report logic and
        templates, then concatenates them into a single PDF - Regal Van
        first, Courier second. Each is a fully independent document, so
        appending their pages always starts the Courier report on a fresh
        page, never mid-page.

        Whichever channel has no matching data is silently skipped (rather
        than failing the whole print), and this only raises when neither
        channel has anything to print."""
        self.ensure_one()

        van_wizard = self._get_channel_wizard('regal_van')
        courier_wizard = self._get_channel_wizard('courier')
        SaleOrderLine = self.env['sale.order.line']

        try:
            has_van = bool(SaleOrderLine.search_count(van_wizard._get_line_domain()))
            has_courier = bool(SaleOrderLine.search_count(courier_wizard._get_line_domain()))

            if not has_van and not has_courier:
                raise UserError(_(
                    "No confirmed Regal Van or Courier order lines found with delivery dates between %s and %s."
                ) % (
                    self.delivery_date_from.strftime('%d/%m/%Y'),
                    self.delivery_date_to.strftime('%d/%m/%Y'),
                ))

            van_pdf = self.env['report.tl_rf_reports.report_requirement'].generate_pdf(van_wizard) if has_van else None
            courier_pdf = self.env['report.tl_rf_reports.report_requirement_courier'].generate_pdf(courier_wizard) if has_courier else None
        finally:
            (van_wizard | courier_wizard).unlink()

        # Order matters: Regal Van always first, Courier always second.
        pdfs = [pdf for pdf in (van_pdf, courier_pdf) if pdf]
        if not pdfs:
            raise UserError(_(
                "No confirmed Regal Van or Courier order lines with printable data were found with "
                "delivery dates between %s and %s."
            ) % (
                self.delivery_date_from.strftime('%d/%m/%Y'),
                self.delivery_date_to.strftime('%d/%m/%Y'),
            ))

        if len(pdfs) == 1:
            combined_pdf = pdfs[0]
        else:
            streams = [io.BytesIO(pdf) for pdf in pdfs]
            merged_stream = self.env['ir.actions.report']._merge_pdfs(streams)
            combined_pdf = merged_stream.getvalue()
            merged_stream.close()

        return self._download_action(
            combined_pdf, f"Requirement_Report_Combined_{self.delivery_date_from.strftime('%Y%m%d')}.pdf"
        )

    def _get_filter_key(self):
        """Identifies one set of requirement lines: the same dates, channel,
        depots and categories always map to the same saved lines."""
        self.ensure_one()
        return '|'.join([
            fields.Date.to_string(self.delivery_date_from),
            fields.Date.to_string(self.delivery_date_to),
            self.delivery_channel or '',
            'd:' + ','.join(str(i) for i in sorted(self.depot_ids.ids)),
            'c:' + ','.join(str(i) for i in sorted(self.categ_ids.ids)),
        ])

    def _compute_required_quantities(self):
        """{product: required qty} for the wizard's filters - one entry per
        stock item (BOM components in place of the finished product, exactly
        like the PDF), summed across all matching sale order lines."""
        self.ensure_one()
        lines = self.env['sale.order.line'].search(self._get_line_domain(), order='product_id, id asc')
        if not lines:
            if self.delivery_channel == 'both':
                channel_name = _("Regal Van or Courier")
            else:
                channel_name = dict(self._fields['delivery_channel'].selection).get(self.delivery_channel, '')
            raise UserError(_(
                "No confirmed %s order lines found with delivery dates between %s and %s."
            ) % (
                channel_name,
                self.delivery_date_from.strftime('%d/%m/%Y'),
                self.delivery_date_to.strftime('%d/%m/%Y'),
            ))

        report_model = self.env['report.tl_rf_reports.report_requirement']
        all_products = lines.mapped('product_id')
        boms_by_product = self.env['mrp.bom']._bom_find(products=all_products) if all_products else {}

        qty_by_product = {}
        for line in lines:
            if not line.product_id or not line.product_uom_qty:
                continue
            for item_product, item_qty in report_model._explode_requirement_line(
                line.product_id, line.product_uom_qty, boms_by_product
            ):
                qty_by_product[item_product] = qty_by_product.get(item_product, 0.0) + item_qty
        return qty_by_product

    def _sync_requirement_lines(self):
        """Creates or refreshes the saved requirement lines for the wizard's
        filters - always ONE line per product - instead of generating a new
        set on every View Lines.

        - Required Qty is refreshed from the current sale orders (also after
          a PO was created: e.g. 2.4 -> 3.6 when a sale order line grew).
          Order Qty is reset to it whenever Required Qty changes (a manual
          Order Qty edit is only kept while Required Qty stays the same); vendor/price
          picked by the user are kept. What is already on Purchase Orders is
          tracked separately (purchase_line_ids / Purchased Qty), and Create
          PO only orders the Balance - see RequirementReportLine.action_create_rfq().
        - Duplicate lines of one product (older "still to order" lines) are
          merged into one, keeping all their PO links.
        - Product no longer required: removed, or - if it already has PO
          lines - kept with Required/Order Qty 0.
        """
        self.ensure_one()
        Line = self.env['requirement.report.line'].sudo()
        key = self._get_filter_key()
        qty_by_product = self._compute_required_quantities()
        precision = self.env['decimal.precision'].precision_get('Product Unit of Measure')

        existing = Line.search([('filter_key', '=', key)])
        by_product = {}
        for line in existing:
            by_product.setdefault(line.product_id, Line)
            by_product[line.product_id] |= line

        vals_list = []
        for prod, req_qty in qty_by_product.items():
            lines = by_product.pop(prod, Line)
            if lines:
                keeper = lines.sorted(lambda l: (not l.purchase_line_ids, l.id))[:1]
                duplicates = lines - keeper
                merged = bool(duplicates)
                if duplicates:
                    keeper.purchase_line_ids |= duplicates.purchase_line_ids
                    duplicates.unlink()
                vals = {'required_qty': req_qty}
                required_changed = float_compare(keeper.required_qty, req_qty, precision_digits=precision) != 0
                if merged or required_changed:
                    vals['ordered_qty'] = req_qty
                keeper.write(vals)
                continue

            sellers = prod.seller_ids or prod.product_tmpl_id.seller_ids
            vendor = sellers[0].partner_id if sellers else False
            price = sellers[0].price if (sellers and sellers[0].price) else prod.standard_price
            vals_list.append({
                'filter_key': key,
                'delivery_date_from': self.delivery_date_from,
                'delivery_date_to': self.delivery_date_to,
                'delivery_channel': self.delivery_channel,
                'product_id': prod.id,
                'required_qty': req_qty,
                'ordered_qty': req_qty,
                'vendor_id': vendor.id if vendor else False,
                'price_unit': price or 0.0,
            })
        if vals_list:
            Line.create(vals_list)

        # Products no longer required.
        leftovers = Line.browse([l.id for lines in by_product.values() for l in lines])
        leftovers.filtered(lambda l: not l.purchase_line_ids).unlink()
        leftovers.filtered(lambda l: l.purchase_line_ids).write({'required_qty': 0.0, 'ordered_qty': 0.0})
        return key

    def action_view_lines(self):
        """Opens the saved requirement lines (per stock item, with vendor,
        price and Create PO) for the wizard's filters, creating/refreshing
        them first - see _sync_requirement_lines()."""
        self.ensure_one()
        key = self._sync_requirement_lines()

        return {
            'name': _('Requirement Report Lines'),
            'type': 'ir.actions.act_window',
            'res_model': 'requirement.report.line',
            'view_mode': 'list,form',
            'domain': [('filter_key', '=', key)],
            'context': {
                'requirement_filter_key': key,
                'search_default_group_by_vendor': 1,
                'search_default_group_by_category': 1,
            },
            'target': 'current',
        }


class RequirementReportLine(models.Model):
    """Saved purchase requirement line. Lines are kept (not regenerated)
    per set of Requirement Report filters - see filter_key - so View Lines
    always reopens the same lines and a Purchase Order is only created once."""
    _name = 'requirement.report.line'
    _description = 'Requirement Report Line'
    _order = 'delivery_date_from desc, vendor_id, product_id'

    filter_key = fields.Char(
        string='Filter Key',
        required=True,
        index=True,
        readonly=True,
        help="Delivery dates, channel, depots and categories these lines were built for.",
    )
    delivery_date_from = fields.Date(string='Delivery Date From', readonly=True)
    delivery_date_to = fields.Date(string='Delivery Date To', readonly=True)
    delivery_channel = fields.Selection(
        selection=[
            ('regal_van', 'Regal Van Delivery'),
            ('courier', 'Courier Delivery'),
            ('both', 'Both'),
        ],
        string='Delivery Channel',
        readonly=True,
    )
    product_id = fields.Many2one(
        'product.product',
        string='Product',
        required=True,
        ondelete='cascade'
    )
    product_tmpl_id = fields.Many2one(
        'product.template',
        string='Product Template',
        related='product_id.product_tmpl_id',
        readonly=True
    )
    product_code = fields.Char(
        string='Code',
        related='product_id.default_code',
        readonly=True
    )
    categ_id = fields.Many2one(
        'product.category',
        string='Category',
        related='product_id.categ_id',
        store=True,
        readonly=True
    )
    
    qty_available = fields.Float(
        string='Available Qty',
        related='product_id.qty_available',
        digits='Product Unit of Measure',
        readonly=True,
    )

    required_qty = fields.Float(
        string='Required Qty',
        digits='Product Unit of Measure',
        default=0.0,
        readonly=True
    )
    ordered_qty = fields.Float(
        string='Order Qty',
        digits='Product Unit of Measure',
        default=0.0
    )
    uom_id = fields.Many2one(
        'uom.uom',
        string='Unit of Measure',
        related='product_id.uom_id',
        readonly=True
    )

    vendor_ids = fields.Many2many(
        'res.partner',
        compute='_compute_vendor_ids',
        string='Allowed Vendors'
    )
    vendor_id = fields.Many2one(
        'res.partner',
        string='Vendor',
        domain="[('id', 'in', vendor_ids)]",
        help="Mapped vendor based on product seller configurations."
    )
    # Grouping key for the "Vendor" group-by. A Char (not the Many2one) so
    # the "No Vendor" group is auto-expanded too: the web client always
    # folds an empty many2one group, which would hide exactly the lines
    # that still need a vendor.
    vendor_group = fields.Char(
        string='Vendor Group',
        compute='_compute_vendor_group',
        store=True,
    )

    price_unit = fields.Float(
        string='Unit Price',
        digits='Product Price'
    )

    purchase_line_ids = fields.Many2many(
        'purchase.order.line',
        'requirement_report_line_po_line_rel',
        'requirement_line_id',
        'purchase_line_id',
        string='Purchase Order Lines',
        readonly=True,
        copy=False,
        help="Every PO line created or updated for this requirement.",
    )
    purchased_qty = fields.Float(
        string='Purchased Qty',
        digits='Product Unit of Measure',
        compute='_compute_purchase_quantities',
        store=True,
        help="Quantity already on (non-cancelled) Purchase Orders.",
    )
    balance_qty = fields.Float(
        string='Balance',
        digits='Product Unit of Measure',
        compute='_compute_purchase_quantities',
        store=True,
        help="Order Qty still to put on a Purchase Order (negative: more is on POs than needed).",
    )
    purchase_order_id = fields.Many2one(
        'purchase.order',
        string='Purchase Order',
        compute='_compute_purchase_quantities',
        store=True,
        help="Latest Purchase Order of this line.",
    )
    order_status = fields.Selection(
        selection=[
            ('draft', 'RFQ'),
            ('sent', 'RFQ Sent'),
            ('to_approve', 'To Approve'),
            ('purchase', 'Purchase Order'),
            ('done', 'Locked'),
            ('cancel', 'Cancelled'),
        ],
        string='Order Status',
        compute='_compute_order_status',
        store=True,
        readonly=True
    )

    @api.depends('product_id', 'product_id.seller_ids', 'product_id.product_tmpl_id.seller_ids')
    def _compute_vendor_ids(self):
        for line in self:
            sellers = line.product_id.seller_ids or line.product_id.product_tmpl_id.seller_ids
            line.vendor_ids = sellers.mapped('partner_id')

    @api.depends('vendor_id')
    def _compute_vendor_group(self):
        for line in self:
            line.vendor_group = line.vendor_id.display_name or _('No Vendor')

    @api.model
    def _open_groups(self, **kwargs):
        """Always open every grouping level (Vendor -> Category), not only
        the first one. Odoo's web_read_group only auto-unfolds level 1 (it
        recurses with auto_unfold=False) and caps it at 10 opened groups;
        groups the user folds by hand stay folded (opening_info wins)."""
        kwargs['auto_unfold'] = True
        return super(RequirementReportLine, self.with_context(max_number_opened_groups=1000))._open_groups(**kwargs)

    @api.depends('ordered_qty', 'purchase_line_ids.product_qty', 'purchase_line_ids.product_uom_id',
                 'purchase_line_ids.state', 'purchase_line_ids.order_id')
    def _compute_purchase_quantities(self):
        for line in self:
            active = line._active_purchase_lines()
            line.purchased_qty = sum(line._po_qty_in_line_uom(pl) for pl in active)
            line.balance_qty = line.ordered_qty - line.purchased_qty
            line.purchase_order_id = active.sorted('id')[-1:].order_id if active else False

    def _active_purchase_lines(self):
        return self.purchase_line_ids.filtered(lambda pl: pl.state != 'cancel' and pl.order_id.state != 'cancel')

    def _po_qty_in_line_uom(self, po_line):
        """PO line quantity expressed in this line's (product) unit."""
        if po_line.product_uom_id and self.uom_id and po_line.product_uom_id != self.uom_id:
            return po_line.product_uom_id._compute_quantity(po_line.product_qty, self.uom_id)
        return po_line.product_qty

    def _to_po_uom(self, qty, po_uom):
        if po_uom and self.uom_id and po_uom != self.uom_id:
            return self.uom_id._compute_quantity(qty, po_uom)
        return qty

    def _editable_purchase_lines(self):
        """This line's PO lines on a still-editable RFQ of its current vendor."""
        return self._active_purchase_lines().filtered(
            lambda pl: pl.order_id.state in ('draft', 'sent')
            and not pl.order_id.locked
            and pl.order_id.partner_id == self.vendor_id
        ).sorted('id')

    @api.depends('purchase_order_id', 'purchase_order_id.state')
    def _compute_order_status(self):
        for line in self:
            line.order_status = line.purchase_order_id.state if line.purchase_order_id else False

    @api.onchange('vendor_id', 'product_id')
    def _onchange_vendor_id(self):
        if self.product_id and self.vendor_id:
            sellers = (self.product_id.seller_ids or self.product_id.product_tmpl_id.seller_ids).filtered(
                lambda s: s.partner_id == self.vendor_id
            )
            if sellers:
                self.price_unit = sellers[0].price or self.product_id.standard_price or 0.0
            else:
                self.price_unit = self.product_id.standard_price or 0.0

    def action_create_rfq(self):
        """Puts each line's Balance (Order Qty - Purchased Qty) on a
        Purchase Order, never re-ordering what is already on one. New
        Purchase Orders are left as RFQs (not confirmed):

        - Balance > 0 and the line's PO for this vendor is still an RFQ:
          that PO line's quantity is increased.
        - Balance > 0 otherwise (e.g. the PO is already confirmed): a new
          RFQ is created for the balance only.
        - Balance < 0 (the requirement went down): the line's RFQ PO lines
          are reduced; confirmed PO lines are not changed.
        """
        lines = self
        if not lines:
            active_ids = self.env.context.get('active_ids')
            if active_ids:
                lines = self.browse(active_ids)
            elif self.env.context.get('requirement_filter_key'):
                lines = self.search([('filter_key', '=', self.env.context['requirement_filter_key'])])

        if not lines:
            raise UserError(_("No requirement report lines found to create RFQ."))

        precision = self.env['decimal.precision'].precision_get('Product Unit of Measure')
        to_increase = lines.filtered(lambda l: float_compare(l.balance_qty, 0.0, precision_digits=precision) > 0)
        to_decrease = lines.filtered(lambda l: float_compare(l.balance_qty, 0.0, precision_digits=precision) < 0)
        if not to_increase and not to_decrease:
            raise UserError(_("Nothing to order: the selected line(s) are fully covered by their Purchase Orders."))

        missing_vendor_lines = to_increase.filtered(lambda l: not l.vendor_id)
        if missing_vendor_lines:
            missing_products = sorted(list({l.product_id.display_name for l in missing_vendor_lines}))
            msg = _(
                "Cannot create Purchase RFQs.\n\n"
                "The following product(s) do not have a vendor configured:\n%s\n\n"
                "Please assign a vendor to these product(s) before creating RFQs."
            ) % "\n".join(f"• {p}" for p in missing_products)
            raise UserError(msg)

        touched_pos = self.env['purchase.order']

        # Requirement went down: take it off the RFQ lines (newest first).
        for line in to_decrease:
            remaining = -line.balance_qty
            for po_line in reversed(line._editable_purchase_lines()):
                if float_compare(remaining, 0.0, precision_digits=precision) <= 0:
                    break
                on_line = line._po_qty_in_line_uom(po_line)
                take = min(remaining, on_line)
                touched_pos |= po_line.order_id
                if float_compare(take, on_line, precision_digits=precision) >= 0:
                    po_line.unlink()
                else:
                    po_line.product_qty = line._to_po_uom(on_line - take, po_line.product_uom_id)
                remaining -= take

        # Requirement went up: top up an open RFQ, else a new PO for the balance.
        new_by_vendor = {}
        for line in to_increase:
            open_po_line = line._editable_purchase_lines()[-1:]
            if open_po_line:
                open_po_line.product_qty += line._to_po_uom(line.balance_qty, open_po_line.product_uom_id)
                touched_pos |= open_po_line.order_id
            else:
                new_by_vendor.setdefault(line.vendor_id, []).append(line)

        PurchaseOrder = self.env['purchase.order']
        PurchaseOrderLine = self.env['purchase.order.line']
        company_id = self.env.company.id
        for vendor, v_lines in new_by_vendor.items():
            origin_str = _("Requirement Report Lines")
            first = v_lines[0]
            if first.delivery_date_from and first.delivery_date_to:
                origin_str = f"Requirement: {first.delivery_date_from.strftime('%d/%m/%Y')} - {first.delivery_date_to.strftime('%d/%m/%Y')}"

            po = PurchaseOrder.create({
                'partner_id': vendor.id,
                'company_id': company_id,
                'origin': origin_str,
                'date_order': fields.Datetime.now(),
            })
            for l in v_lines:
                prod = l.product_id
                uom = getattr(prod, 'uom_po_id', False) or prod.uom_id or l.uom_id
                po_line = PurchaseOrderLine.create({
                    'order_id': po.id,
                    'product_id': prod.id,
                    'name': prod.display_name or prod.name,
                    'product_qty': l._to_po_uom(l.balance_qty, uom),
                    'product_uom_id': uom.id if uom else False,
                    'price_unit': l.price_unit or prod.standard_price or 0.0,
                    'date_planned': fields.Datetime.now(),
                })
                l.purchase_line_ids |= po_line

            touched_pos |= po

        touched_pos = touched_pos.exists()
        if len(touched_pos) == 1:
            return {
                'name': _('Purchase Order'),
                'type': 'ir.actions.act_window',
                'res_model': 'purchase.order',
                'view_mode': 'form',
                'res_id': touched_pos.id,
                'target': 'current',
            }
        return {
            'name': _('Purchase Orders'),
            'type': 'ir.actions.act_window',
            'res_model': 'purchase.order',
            'view_mode': 'list,form',
            'domain': [('id', 'in', touched_pos.ids)],
            'target': 'current',
        }

    def action_open_product_vendors(self):
        """Opens the line's product in a pop-up showing only its Purchase tab
        (vendor pricelist), so a missing vendor can be created on the spot."""
        self.ensure_one()
        return {
            'name': _('Vendors - %s') % self.product_id.display_name,
            'type': 'ir.actions.act_window',
            'res_model': 'product.template',
            'res_id': self.product_id.product_tmpl_id.id,
            'view_mode': 'form',
            'views': [(self.env.ref('tl_rf_reports.product_template_requirement_vendor_form').id, 'form')],
            'target': 'new',
            'context': {'requirement_line_id': self.id},
        }

    def action_view_purchase_order(self):
        """Opens the linked Purchase Order(s)."""
        po_ids = self._active_purchase_lines().order_id.ids or self.mapped('purchase_order_id').ids
        if not po_ids:
            raise UserError(_("No Purchase Order is linked to the selected line(s)."))

        if len(po_ids) == 1:
            return {
                'name': _('Purchase Order'),
                'type': 'ir.actions.act_window',
                'res_model': 'purchase.order',
                'view_mode': 'form',
                'res_id': po_ids[0],
                'target': 'current',
            }
        return {
            'name': _('Purchase Orders'),
            'type': 'ir.actions.act_window',
            'res_model': 'purchase.order',
            'view_mode': 'list,form',
            'domain': [('id', 'in', po_ids)],
            'target': 'current',
        }

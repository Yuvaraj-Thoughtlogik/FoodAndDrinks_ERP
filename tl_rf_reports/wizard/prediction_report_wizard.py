# -*- coding: utf-8 -*-
import base64

from odoo import api, fields, models
from odoo.tools import _
from odoo.exceptions import UserError, ValidationError


class PredictionReportWizard(models.TransientModel):
    _name = 'prediction.report.wizard'
    _description = 'Prediction Report Wizard'

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
        help="Starting delivery date for prediction report."
    )
    delivery_date_to = fields.Date(
        string='Delivery Date To',
        required=True,
        default=fields.Date.context_today,
        help="Ending delivery date for prediction report."
    )

    @api.model
    def _default_depot_ids(self):
        return self.env['stock.warehouse'].search([])

    depot_ids = fields.Many2many(
        'stock.warehouse',
        'prediction_report_wizard_warehouse_rel',
        'wizard_id',
        'warehouse_id',
        string='Depot',
        default=_default_depot_ids,
        help="Select one or more depots. Leave unselected to include all depots."
    )

    categ_ids = fields.Many2many(
        'product.category',
        'prediction_report_wizard_category_rel',
        'wizard_id',
        'category_id',
        string='Product Category',
        help="Select one or more product categories to filter. Leave empty to include all categories."
    )

    line_ids = fields.One2many(
        'prediction.report.line',
        'wizard_id',
        string='Prediction Lines'
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

    # ------------------------------------------------------------------
    # BOM Helpers for Prediction Lines
    # ------------------------------------------------------------------
    def _find_bom(self, product):
        """Return the applicable BOM for a product (variant-specific first,
        falling back to a template-level BOM), or an empty recordset if the
        product has no BOM."""
        BomModel = self.env['mrp.bom']
        company_ids = [self.env.company.id, False]

        bom = BomModel.search([
            ('product_id', '=', product.id),
            ('company_id', 'in', company_ids),
        ], limit=1, order='sequence, id')

        if not bom:
            bom = BomModel.search([
                ('product_tmpl_id', '=', product.product_tmpl_id.id),
                ('product_id', '=', False),
                ('company_id', 'in', company_ids),
            ], limit=1, order='sequence, id')

        return bom

    def _explode_bom(self, product, qty, bom_cache):
        """Resolve a sold product and its ordered quantity to reporting items."""
        if product.id not in bom_cache:
            bom_cache[product.id] = self._find_bom(product)
        bom = bom_cache[product.id]

        if not bom:
            return [(product, qty)]

        finished_uom = bom.product_uom_id or product.uom_id
        order_uom = product.uom_id
        try:
            qty_in_bom_uom = order_uom._compute_quantity(qty, finished_uom)
        except Exception:
            qty_in_bom_uom = qty

        bom_produced_qty = bom.product_qty or 1.0

        result = []
        for bom_line in bom.bom_line_ids:
            component = bom_line.product_id
            if not component:
                continue
            if hasattr(bom_line, '_skip_bom_line') and bom_line._skip_bom_line(product):
                continue

            line_qty = bom_line.product_qty
            if bom_line.product_uom_id and bom_line.product_uom_id != component.uom_id:
                try:
                    line_qty = bom_line.product_uom_id._compute_quantity(line_qty, component.uom_id)
                except Exception:
                    line_qty = bom_line.product_qty

            qty_per_unit = (line_qty / bom_produced_qty) if bom_produced_qty else 0.0
            comp_qty = qty_per_unit * qty_in_bom_uom
            if comp_qty:
                result.append((component, comp_qty))

        if not result:
            return [(product, qty)]

        return result

    def _generate_prediction_lines(self):
        """Extract matching lines, explode BOMs, and populate PredictionReportLine records."""
        self.ensure_one()
        self.sudo().line_ids.unlink()

        domain = self._get_line_domain()
        lines = self.env['sale.order.line'].search(domain, order='product_id, id asc')
        if not lines:
            channel_name = dict(self._fields['delivery_channel'].selection).get(self.delivery_channel, '')
            raise UserError(_(
                "No confirmed %s order lines found with delivery dates between %s and %s."
            ) % (
                channel_name,
                self.delivery_date_from.strftime('%d/%m/%Y'),
                self.delivery_date_to.strftime('%d/%m/%Y'),
            ))

        products_map = {}
        bom_cache = {}

        for line in lines:
            product = line.product_id
            if not product:
                continue
            qty = line.product_uom_qty or 0.0
            if not qty:
                continue

            reporting_items = self._explode_bom(product, qty, bom_cache)
            for item_product, item_qty in reporting_items:
                if not item_qty:
                    continue
                pid = item_product.id
                if pid not in products_map:
                    products_map[pid] = {
                        'product': item_product,
                        'qty': 0.0,
                    }
                products_map[pid]['qty'] += item_qty

        vals_list = []
        for pid, pdata in sorted(products_map.items(), key=lambda item: (item[1]['product'].name or '').lower()):
            prod = pdata['product']
            sellers = prod.seller_ids or prod.product_tmpl_id.seller_ids
            vendor = sellers[0].partner_id if sellers else False
            price = sellers[0].price if (sellers and sellers[0].price) else prod.standard_price

            vals_list.append({
                'wizard_id': self.id,
                'product_id': prod.id,
                'quantity': pdata['qty'],
                'vendor_id': vendor.id if vendor else False,
                'price_unit': price or 0.0,
            })

        if vals_list:
            self.env['prediction.report.line'].sudo().create(vals_list)

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
        """Validates matching orders/lines and triggers the Prediction PDF Report.

        Built directly with ReportLab (generate_pdf() on the report model)
        instead of QWeb+wkhtmltopdf, same as the other reports in this module -
        this stays fully synchronous, no background job needed."""
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
            report_model = self.env['report.tl_rf_reports.report_prediction_courier']
            filename = f"Courier_Prediction_Report_{self.delivery_date_from.strftime('%Y%m%d')}.pdf"
        else:
            report_model = self.env['report.tl_rf_reports.report_prediction']
            filename = f"Prediction_Report_{self.delivery_date_from.strftime('%Y%m%d')}.pdf"

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
        return self._download_action(pdf_content, filename)

    def action_view_lines(self):
        """Generates the prediction report lines and opens their list view."""
        self.ensure_one()
        self._generate_prediction_lines()

        return {
            'name': _('Prediction Report Lines'),
            'type': 'ir.actions.act_window',
            'res_model': 'prediction.report.line',
            'view_mode': 'list,form',
            'domain': [('wizard_id', '=', self.id)],
            'context': {
                'default_wizard_id': self.id,
                'search_default_group_by_vendor': 1,
            },
            'target': 'current',
        }


class PredictionReportLine(models.TransientModel):
    _name = 'prediction.report.line'
    _description = 'Prediction Report Line'
    _order = 'vendor_id, product_id'

    wizard_id = fields.Many2one(
        'prediction.report.wizard',
        string='Wizard',
        ondelete='cascade',
        index=True
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
    quantity = fields.Float(
        string='Ordered Qty',
        digits='Product Unit of Measure',
        default=0.0
    )
    uom_id = fields.Many2one(
        'uom.uom',
        string='Unit of Measure',
        related='product_id.uom_id',
        readonly=True
    )
    vendor_id = fields.Many2one(
        'res.partner',
        string='Vendor',
        help="Configured primary vendor for this product."
    )
    price_unit = fields.Float(
        string='Unit Price',
        digits='Product Price'
    )

    def action_create_rfq(self):
        """Action to group prediction lines by vendor and create Purchase RFQs."""
        lines = self
        if not lines:
            active_ids = self.env.context.get('active_ids')
            if active_ids:
                lines = self.browse(active_ids)
            elif self.env.context.get('default_wizard_id'):
                lines = self.search([('wizard_id', '=', self.env.context.get('default_wizard_id'))])
            else:
                wizard_ids = self.mapped('wizard_id')
                if wizard_ids:
                    lines = wizard_ids[0].line_ids

        if not lines:
            raise UserError(_("No prediction report lines found to create RFQ."))

        # 1. Vendor Validation: verify all products have a vendor configured
        missing_vendor_lines = lines.filtered(lambda l: not l.vendor_id)
        if missing_vendor_lines:
            missing_products = sorted(list({l.product_id.display_name for l in missing_vendor_lines}))
            msg = _(
                "Cannot create Purchase RFQs.\n\n"
                "The following product(s) do not have a vendor configured:\n%s\n\n"
                "Please assign a vendor to these product(s) before creating RFQs."
            ) % "\n".join(f"• {p}" for p in missing_products)
            raise UserError(msg)

        # 2. Group products by Vendor
        lines_by_vendor = {}
        for line in lines:
            if line.quantity <= 0:
                continue
            vendor = line.vendor_id
            if vendor not in lines_by_vendor:
                lines_by_vendor[vendor] = []
            lines_by_vendor[vendor].append(line)

        if not lines_by_vendor:
            raise UserError(_("All selected lines have zero quantity. No RFQs to create."))

        # 3. Create one Purchase RFQ per Vendor
        PurchaseOrder = self.env['purchase.order']
        PurchaseOrderLine = self.env['purchase.order.line']
        created_pos = self.env['purchase.order']

        company_id = self.env.company.id

        for vendor, v_lines in lines_by_vendor.items():
            origin_str = _("Prediction Report Lines")
            wiz = v_lines[0].wizard_id if v_lines else False
            if wiz and wiz.delivery_date_from and wiz.delivery_date_to:
                origin_str = f"Prediction: {wiz.delivery_date_from.strftime('%d/%m/%Y')} - {wiz.delivery_date_to.strftime('%d/%m/%Y')}"

            po_vals = {
                'partner_id': vendor.id,
                'company_id': company_id,
                'origin': origin_str,
                'date_order': fields.Datetime.now(),
            }
            po = PurchaseOrder.create(po_vals)
            created_pos |= po

            for l in v_lines:
                prod = l.product_id
                uom = getattr(prod, 'uom_po_id', False) or prod.uom_id or l.uom_id
                price = l.price_unit or prod.standard_price or 0.0

                po_line_vals = {
                    'order_id': po.id,
                    'product_id': prod.id,
                    'name': prod.display_name or prod.name,
                    'product_qty': l.quantity,
                    'product_uom_id': uom.id if uom else False,
                    'price_unit': price,
                    'date_planned': fields.Datetime.now(),
                }
                PurchaseOrderLine.create(po_line_vals)

        # 4. Return action opening the created RFQ(s)
        if len(created_pos) == 1:
            return {
                'name': _('Purchase RFQ'),
                'type': 'ir.actions.act_window',
                'res_model': 'purchase.order',
                'view_mode': 'form',
                'res_id': created_pos.id,
                'target': 'current',
            }
        else:
            return {
                'name': _('Created Purchase RFQs'),
                'type': 'ir.actions.act_window',
                'res_model': 'purchase.order',
                'view_mode': 'list,form',
                'domain': [('id', 'in', created_pos.ids)],
                'target': 'current',
            }

# -*- coding: utf-8 -*-
import logging
import math
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


def _format_report_qty(val):
    """Trims a float to at most 3 decimals with no trailing zeros, e.g.
    2.0 -> '2', 2.5 -> '2.5'. Mirrors report/production_report.py's
    _format_qty so "<qty>kg <product>" reads the same across reports."""
    if not val:
        return '0'
    formatted = f"{val:.3f}"
    if '.' in formatted:
        formatted = formatted.rstrip('0').rstrip('.')
    return formatted or '0'


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    box_qty = fields.Float(
        string="Box Qty",
        compute='_compute_box_qty',
        store=True,
        readonly=False,
        digits=(16, 0),
        #help="Auto-calculated box quantity based on 1kg box capacity per unit multiplied by line quantity."
    )
    weight = fields.Float(
        string="Weight (Kg)",
        compute='_compute_weight',
        digits=(16, 2),
        help="Calculated weight in Kg based on unit weight and product quantity."
    )
    categ_id = fields.Many2one(
        'product.category',
        related='product_id.categ_id',
        string="Product Category",
        readonly=True,
        store=True,
    )
    depot_id = fields.Many2one(
        'stock.warehouse',
        related='order_id.batch_id.depot_id',
        string="Depot",
        readonly=True,
        store=True,
    )
    delivery_date = fields.Date(
        related='order_id.delivery_date',
        string="Delivery Date",
        readonly=True,
        store=True,
    )
    delivery_channel = fields.Selection(
        related='order_id.delivery_channel',
        string="Delivery Channel",
        readonly=True,
        store=True,
    )
    confirmed_qty = fields.Float(
        string="Confirmed Qty",
        default=0.0,
        copy=False,
        compute="_compute_confirmed_qty",
        store=True,
        digits='Product Unit of Measure',
        help="Snapshot of the ordered quantity taken when the sale order was confirmed. "
             "Used to detect quantity changes made after confirmation.",
    )
    late_qty_delta = fields.Float(
        string="Late Qty Delta",
        compute='_compute_late_order',
        store=True,
        copy=False,
        digits='Product Unit of Measure',
        help="Current quantity minus the quantity confirmed at order confirmation. "
             "Only populated while the order is late (confirmed and its batch is Printed).",
    )
    is_late_order = fields.Boolean(
        string="Late Order",
        store=True,
        compute='_compute_late_order',
        copy=False,
        help="True when the order is confirmed and its batch is in Printed status.",
    )
    batch_id = fields.Many2one(
        comodel_name='round.management.batch',
        related='order_id.batch_id',
        store=True,
    )
    lock_line = fields.Boolean()

    report_line_ids = fields.One2many(
        'sale.order.line.report_lines',
        'sale_order_line_id',
        string='Report Lines',
        compute='_compute_report_line_ids',
        store=True,
        help="Packing-list rows for this line. For a product with a BoM, one row "
             "per raw-material component (move_raw_ids) of its linked Manufacturing "
             "Order (production_sale_line_id); for a product without a BoM, a single "
             "row for the line itself. See _compute_report_line_ids.",
    )

    # Regal Van is driven by confirmed_qty/late_qty_delta (the frozen
    # snapshot plus any change made after it was locked in), Courier by
    # the live product_uom_qty - see _get_report_line_vals.
    @api.depends(
        'product_id', 'product_uom_qty', 'special_requirements_notes_id',
        'delivery_channel', 'confirmed_qty', 'late_qty_delta',
    )
    def _compute_report_line_ids(self):
        Bom = self.env['mrp.bom']
        products = self.mapped('product_id')
        boms_by_product = Bom._bom_find(products=products) if products else {}

        for line in self:
            line.report_line_ids.unlink()
            vals_list = line._get_report_line_vals(boms_by_product.get(line.product_id))
            line.report_line_ids = [(0, 0, vals) for vals in vals_list]

    def _recompute_report_lines(self):
        """Force-refreshes report_line_ids. The linked Manufacturing Order
        (and its move_raw_ids) is created/edited on mrp.production, a
        different model that this field's @api.depends can't reach, so the
        Packing List report calls this right before reading report_line_ids
        to guarantee it reflects the current MO state."""
        self._compute_report_line_ids()

    @staticmethod
    def _compose_report_name(base_name, notes):
        """Appends the note to the report line's display name, hashed off on
        both sides so it stands out on the printed row, e.g.:
        "0.5 kg Cod Fillets Boned # 2 EQUAL SIZE PTNS 2PPB #"."""
        base_name = base_name or ''
        notes = (notes or '').strip()
        return f"{base_name} # {notes} #" if notes else base_name

    def _plain_report_line_vals(self, qty, notes, late=False):
        """A single non-exploded "<qty> kg <product>" row - used for the
        confirmed_qty/late_qty_delta row of a non-BoM Regal Van line, and
        for a Courier line's (always non-late) live-quantity row."""
        return {
            'name': f"{self.product_id.name or ''}",
            'product_id': self.product_id.id,
            'box_content': f"{_format_report_qty(qty)} kg",
            'qty': qty,
            'notes': notes,
            'late_order': late,
        }

    def _get_report_line_vals(self, bom):
        """Builds the create-vals for this line's report lines (see
        report_line_ids). `bom` is the product's BoM (or a falsy recordset)
        as resolved by mrp.bom._bom_find, passed in so callers can look it
        up once for a whole batch of lines instead of per line.

        Courier has no confirmed_qty/late split (its lines aren't locked in
        by a batch print), so it always gets a single row built from the
        live product_uom_qty. Regal Van is sourced from confirmed_qty (the
        frozen snapshot taken when the batch was locked in) plus, when the
        qty changed afterwards, a SEPARATE late_qty_delta row - the two are
        never merged, so a late addition/removal is never silently folded
        into what was already packed."""
        self.ensure_one()
        if not self.product_id:
            return []

        notes = self.special_requirements_notes_id.name or ''

        if bom:
            # A line can be split across several MOs (one per box, e.g. the
            # Pack Box wizard's "Box 3/5" origin suffix) that all share this
            # same production_sale_line_id, so all of them - not just the
            # first - contribute their raw-material components. Each box's
            # own is_late_order (round_management.MrpProduction), not the
            # sale line's overall lateness, decides whether that specific
            # box's rows are late.
            productions = self.env['mrp.production'].search(
                [('production_sale_line_id', '=', self.id)]
            )
            vals_list = []
            for move in productions.mapped('move_raw_ids'):
                qty = move.product_uom_qty or 0.0
                component = move.product_id
                move_notes = move.special_requirements_notes or ''
                vals_list.append({
                    'name': self._compose_report_name(f"{_format_report_qty(qty)} kg {component.name or ''}", move_notes),
                    'product_id': component.id,
                    'box_content': f"{_format_report_qty(qty)} kg",
                    'qty': qty,
                    'notes': move_notes,
                    'late_order': bool(move.raw_material_production_id.is_late_order),
                    'from_bom': True,
                })
            return vals_list

        if self.delivery_channel == 'courier':
            if self.product_uom_qty <= 0:
                return []
            return [self._plain_report_line_vals(self.product_uom_qty, notes)]

        vals_list = []
        if self.confirmed_qty > 0:
            vals_list.append(self._plain_report_line_vals(self.confirmed_qty, notes))
        if self.late_qty_delta:
            vals_list.append(self._plain_report_line_vals(self.late_qty_delta, notes, late=True))
        return vals_list

    @api.model_create_multi
    def create(self, vals_list):

        for val in vals_list:
            order_id = self.env['sale.order'].browse(val['order_id'])
            val['lock_line'] = (order_id.state == 'sale' and order_id.batch_id.state == 'prt') or order_id.is_late_order

        return super().create(vals_list)

    @api.constrains('product_uom_qty')
    def _check_qty_not_reduced_after_mo(self):
        """Once Manufacturing Orders exist for a line, its confirmed_qty
        boxes are already being produced - reducing the quantity below that
        would silently invalidate work already in progress. Increasing it
        is still fine (see _get_report_line_vals' late_qty_delta row)."""
        for line in self:
            if line.confirmed_qty and line.product_uom_qty < line.confirmed_qty:
                if self.env['mrp.production'].search_count(
                    [('production_sale_line_id', '=', line.id)]
                ):
                    raise ValidationError(_(
                        "Cannot reduce the quantity on '%(product)s' below %(qty)s - Manufacturing "
                        "Orders have already been generated for this line. You can only increase "
                        "the quantity, not reduce it.",
                        product=line.product_id.display_name,
                        qty=line.confirmed_qty,
                    ))

    @api.depends('product_uom_qty','confirmed_qty')
    def _compute_late_order(self):
        for line in self:
            if line.lock_line:
                line.is_late_order = True
                line.late_qty_delta = line.product_uom_qty

            elif line.batch_id.state == 'prt' and line.order_id.state == 'sale' and line.product_uom_qty != line.confirmed_qty:
                line.is_late_order = True
                line.late_qty_delta = line.product_uom_qty - line.confirmed_qty
            else:
                line.late_qty_delta = 0.0
                line.is_late_order = False


    @api.depends('order_id.state','batch_id.state')
    def _compute_confirmed_qty(self):
        for rec in self:
            if rec.batch_id.state == 'prt' and rec.order_id.state == 'sale':
                rec.confirmed_qty = rec.product_uom_qty
            else:
                rec.confirmed_qty = 0.0


    def _get_product_unit_weight_in_kg(self):
        """Extracts unit weight in kg directly from the product."""
        self.ensure_one()
        return self.product_id.weight or 0.0

    @api.depends('product_id', 'product_uom_qty', 'product_id.weight', 'product_uom_id')
    def _compute_weight(self):
        """Calculate total weight in kg for the order line."""
        for line in self:
            if not line.product_id or line.product_uom_qty <= 0:
                line.weight = 0.0
                continue
            unit_weight = line._get_product_unit_weight_in_kg()
            if unit_weight > 0:
                line.weight = round(unit_weight * line.product_uom_qty, 2)
            else:
                line.weight = round(line.product_uom_qty, 2)

    @api.depends('product_uom_qty')
    def _compute_box_qty(self):
        """Box qty is simply the order quantity rounded up to the next
        whole box - 1 box per unit of qty, regardless of weight or UoM.

        Examples:
            qty=1   → 1 box
            qty=1.5 → 2 boxes
            qty=2.8 → 3 boxes
        """
        for line in self:
            line.box_qty = math.ceil(line.product_uom_qty) if line.product_uom_qty > 0 else 0.0


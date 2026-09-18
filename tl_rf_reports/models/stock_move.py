# -*- coding: utf-8 -*-
from odoo import fields, models


class StockMove(models.Model):
    _inherit = 'stock.move'

    # Exposed for the Production Report (report/production_report.py) and its
    # "View Lines" screen. A draft Manufacturing Order's own top-level
    # product is a generic pack (e.g. "Salmon Fish Pack") - the actual
    # box-type product being counted (e.g. "0.5 kg Cod Fillets Boned") lives
    # on its BOM/raw-material component lines (move_raw_ids), so the report
    # groups those component lines, not mo.product_id. depot_id and
    # batch_delivery_date mirror the same fields added to mrp.production in
    # models/mrp_production.py, just one hop further via
    # raw_material_production_id.
    depot_id = fields.Many2one(
        'stock.warehouse',
        string='Depot',
        related='raw_material_production_id.depot_id',
        store=True,
        readonly=True,
    )
    batch_delivery_date = fields.Date(
        string='Delivery Date',
        related='raw_material_production_id.batch_delivery_date',
        store=True,
        readonly=True,
    )
    component_categ_id = fields.Many2one(
        'product.category',
        string='Category',
        related='product_id.categ_id',
        store=True,
        readonly=True,
    )

    # The originating sale order line for this box (see
    # mrp_production.MrpProduction.sale_line_id) and its special
    # requirements note, surfaced here so the Production Report can
    # consolidate same product/quantity boxes together while keeping a
    # customer's special-note box on its own row (see
    # report/production_report.py generate_pdf()'s consolidation key).
    sale_line_id = fields.Many2one(
        'sale.order.line',
        string='Sale Order Line',
        related='raw_material_production_id.sale_line_id',
        readonly=True,
    )
    special_requirements_notes = fields.Char(
        string='Special Notes',
        related='sale_line_id.special_requirements_notes_id.name',
        readonly=True,
    )

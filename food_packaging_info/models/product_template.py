import re
from datetime import datetime, timedelta
from odoo import api, fields, models, _
from odoo.exceptions import ValidationError 


class ProductCategory(models.Model):
    _inherit = 'product.category'


class FishSpecies(models.Model):
    _name = 'fish.species'
    _description = 'Fish Species'

    name = fields.Char(string="Species Name", required=True)


class FishCut(models.Model):
    _name = 'fish.cut'
    _description = 'Fish Cut Type'

    name = fields.Char(string="Cut Name", required=True)


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    bingo = fields.Boolean(
        string="Bingo",
        default=False,
        help="Check if this product is tagged for Bingo."
    )
    tagon = fields.Boolean(
        string="Tagon",
        default=False,
        help="Check if this product is tagged for Tagon."
    )
    
    staff_price = fields.Monetary(string="Staff Price", currency_field='currency_id')
    offer_saving = fields.Monetary(string="Offer Saving", compute='_compute_offer_saving', store=True, readonly=False)

    stock_available = fields.Float(string="Stock Available", compute='_compute_stock_available')

    min_qty = fields.Float(string="Min Qty", default=1.0)
    gross_net_weight = fields.Char(string="Weight (Gross/Net)")
    packing_info = fields.Char(string="Packing")
    avg_serving = fields.Char(string="Average Serving")
    use_frozen = fields.Char(string="Use Frozen")
    use_frozen_days = fields.Integer(string="Use Frozen Days")
    use_fresh = fields.Char(string="Use Fresh")
    use_fresh_days = fields.Integer(string="Use Fresh Days")

    fish_info = fields.Text(string="Fish Information")
    check_notes = fields.Char(string="Check Notes")
    mix_code = fields.Char(string="Mix Code")
    sort_seq = fields.Integer(string="Sort Seq")
    allergens_notice = fields.Char(string="Allergens")

    ingredients_html = fields.Html(string="Ingredients", sanitize=True)
    sales_line_html = fields.Html(string="Internal Sales Line", sanitize=True)
    notes_html = fields.Html(string="Notes", sanitize=True)
    cooking_instructions_html = fields.Html(string="Cooking", sanitize=True)
    nutritional_info_html = fields.Html(string="Nutrition", sanitize=True)

    assembly_type = fields.Selection([
        ('A', 'Assembly'),
        ('C', 'Component'),
    ], string="Assembly Type", default='C')

    species_id = fields.Many2one('fish.species', string="Species")
    cut_id = fields.Many2one('fish.cut', string="Cut")
    origin_country = fields.Char(
        string="Origin",
        help="Country of origin. Example: Salmon (Salmo salar)/FARMED in Norway"
    )
    catch_area = fields.Char(
        string="Catch Area",
        help="Area where the fish was caught. Example: FAO 27 North East Atlantic"
    )

    stk_purchase_analysis = fields.Char(
        string='Purchase Analysis',
        help='Free-text field used for procurement reporting.',
    )
    stk_sales_analysis = fields.Char(
        string='Sales Analysis',
        help='Free-text field used as a reporting category for sales.',
    )
    stk_type_id = fields.Many2one(
        'product.stk.type',
        string='Type',
        help='Product classification type. Add new types directly from this field.',
    )
    yield_info = fields.Char(
        string="Yield",
        help="Yield percentage or details for fish processing/production."
    )
    

    # Automatically assign Assembly ('A') on write/create if BoMs exist
    @api.model_create_multi
    def create(self, vals_list):
        templates = super().create(vals_list)
        for tmpl in templates:
            if tmpl.bom_ids and tmpl.assembly_type != 'A':
                tmpl.assembly_type = 'A'
        return templates

    def write(self, vals):
        res = super().write(vals)
        for tmpl in self:
            if tmpl.bom_ids and tmpl.assembly_type != 'A':
                tmpl.assembly_type = 'A'
        return res

    # 1. Automatically assign Assembly ('A') when a BoM is created/attached
    @api.onchange('bom_ids')
    def _onchange_bom_ids_set_assembly(self):
        if self.bom_ids and self.assembly_type != 'A':
            self.assembly_type = 'A'

    # 2. Block changing Assembly ('A') to Component ('C') if a BoM exists
    @api.constrains('assembly_type', 'bom_ids')
    def _check_assembly_type_bom_restriction(self):
        for product in self:
            if product.bom_ids and product.assembly_type == 'C':
                raise ValidationError(_(
                    "Warning: Product '%s' has an active Bill of Materials (BoM) "
                    "and cannot be set to 'Component'. It must remain as 'Assembly'."
                ) % product.name)

    @api.onchange('default_code')
    def _onchange_default_code_update_barcode(self):
        if self.default_code:
            self.barcode = self.default_code

    @api.onchange('assembly_type')
    def _onchange_assembly_type_warning(self):
        if self.bom_ids and self.assembly_type == 'C':
            self.assembly_type = 'A'
            return {
                'warning': {
                    'title': _("Action Restricted"),
                    'message': _("This product has a BoM attached. Assembly Type cannot be changed to Component!"),
                }
            }

    @api.depends('list_price', 'staff_price')
    def _compute_offer_saving(self):
        """Calculates discount difference automatically between list price and staff price."""
        for record in self:
            if record.list_price and record.staff_price:
                record.offer_saving = max(0.0, record.list_price - record.staff_price)
            else:
                record.offer_saving = 0.0

    def _compute_stock_available(self):
        """Pulls total virtual available stock directly across warehouses."""
        for record in self:
            record.stock_available = record.virtual_available

    @api.onchange('ingredients_html', 'sales_line_html')
    def _onchange_highlight_allergens(self):
        """Auto-bolds key allergens in UPPERCASE text matching legacy system rules."""
        allergens = [
            'WHEAT', 'FISH', 'MILK', 'MUSTARD', 'SOY', 
            'SOYA', 'EGGS', 'PEANUTS', 'CELERY', 'SULPHITES', 'HADDOCK'
        ]
        for field_name in ['ingredients_html', 'sales_line_html']:
            content = getattr(self, field_name)
            if content:
                for allergen in allergens:
                    pattern = re.compile(rf'(?<!<b>)(?<!<strong>)\b({allergen})\b(?!</b>)(?!</strong>)', re.IGNORECASE)
                    content = pattern.sub(r'<strong>\1</strong>', content)
                setattr(self, field_name, content)

    @api.onchange('gross_net_weight')
    def _onchange_gross_net_weight_sync(self):
        """Extracts numerical weight (e.g., '1Kg' -> 1.0) into native weight field."""
        if self.gross_net_weight:
            match = re.search(r"[-+]?\d*\.\d+|\d+", str(self.gross_net_weight))
            if match:
                self.weight = float(match.group())

    def action_alternative_fish(self):
        """Button Logic: Opens alternative fish products within the same category."""
        return {
            'type': 'ir.actions.act_window',
            'name': 'Alternative Fish Options',
            'res_model': 'product.template',
            'view_mode': 'list,form',
            'domain': [('categ_id', '=', self.categ_id.id), ('id', '!=', self.id)],
        }


class MrpBom(models.Model):
    _inherit = 'mrp.bom'

    @api.model_create_multi
    def create(self, vals_list):
        """Triggers assembly type update on product when a new BoM is saved."""
        boms = super().create(vals_list)
        for bom in boms:
            if bom.product_tmpl_id and bom.product_tmpl_id.assembly_type != 'A':
                bom.product_tmpl_id.assembly_type = 'A'
        return boms

    def write(self, vals):
        """Triggers assembly type update on product when BoM target changes."""
        res = super().write(vals)
        for bom in self:
            if bom.product_tmpl_id and bom.product_tmpl_id.assembly_type != 'A':
                bom.product_tmpl_id.assembly_type = 'A'
        return res


class ProductType(models.Model):
    _name = 'product.stk.type'
    _description = 'Product Type (Classification)'
    _order = 'name'

    name = fields.Char(required=True)

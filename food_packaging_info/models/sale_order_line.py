from odoo import api, fields, models


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    
    selected_line_id = fields.Many2one('sale.order.line', string="Selected Line Item")

   
    line_avg_serving = fields.Char(related='selected_line_id.avg_serving', string="Average Serving", readonly=False)
    line_min_weight = fields.Char(related='selected_line_id.min_weight', string="Min. Weight", readonly=False)
    line_gross_net_weight = fields.Char(related='selected_line_id.gross_net_weight', string="Gross / Net Weight", readonly=False)
    line_check_notes = fields.Char(related='selected_line_id.check_notes', string="Check Notes", readonly=False)
    line_allergens_notice = fields.Char(related='selected_line_id.allergens_notice', string="Allergens Notice", readonly=False)
    line_fish_info = fields.Text(related='selected_line_id.fish_info', string="Fish Information", readonly=False)
    line_ingredients_html = fields.Html(related='selected_line_id.ingredients_html', string="Ingredients", readonly=False)
    line_cooking_instructions_html = fields.Html(related='selected_line_id.cooking_instructions_html', string="Cooking Instructions", readonly=False)
    line_nutritional_info_html = fields.Html(related='selected_line_id.nutritional_info_html', string="Nutritional Info", readonly=False)

    @api.onchange('order_line')
    def _onchange_order_line_auto_select(self):
        """Automatically selects the first valid product line if none is selected."""
        valid_lines = self.order_line.filtered(lambda l: l.product_id)
        if valid_lines and (not self.selected_line_id or self.selected_line_id not in valid_lines):
            self.selected_line_id = valid_lines[0]
        elif not valid_lines:
            self.selected_line_id = False


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    
    min_qty = fields.Float(string="Min Qty", compute="_compute_custom_specs", store=True, readonly=False)
    min_weight = fields.Char(string="Min Weight", compute="_compute_custom_specs", store=True, readonly=False)
    gross_net_weight = fields.Char(string="Weight (Gross/Net)", compute="_compute_custom_specs", store=True, readonly=False)
    avg_serving = fields.Char(string="Average Serving", compute="_compute_custom_specs", store=True, readonly=False)
    use_frozen = fields.Char(string="Use Frozen", compute="_compute_custom_specs", store=True, readonly=False)
    use_fresh = fields.Char(string="Use Fresh", compute="_compute_custom_specs", store=True, readonly=False)
    packing_info = fields.Char(string="Packing", compute="_compute_custom_specs", store=True, readonly=False)
    allergens_notice = fields.Char(string="Allergens", compute="_compute_custom_specs", store=True, readonly=False)
    check_notes = fields.Char(string="Check Notes", compute="_compute_custom_specs", store=True, readonly=False)
    mix_code = fields.Char(string="Mix Code", compute="_compute_custom_specs", store=True, readonly=False)
    sort_seq = fields.Integer(string="Sort Seq", compute="_compute_custom_specs", store=True, readonly=False)
    sales_line_html = fields.Html(string="Sales Line", compute="_compute_custom_specs", store=True, readonly=False)
    fish_info = fields.Text(string="Fish Information", compute="_compute_custom_specs", store=True, readonly=False)
    ingredients_html = fields.Html(string="Ingredients", compute="_compute_custom_specs", store=True, readonly=False)
    notes_html = fields.Html(string="Notes", compute="_compute_custom_specs", store=True, readonly=False)
    cooking_instructions_html = fields.Html(string="Cooking", compute="_compute_custom_specs", store=True, readonly=False)
    nutritional_info_html = fields.Html(string="Nutrition", compute="_compute_custom_specs", store=True, readonly=False)

    @api.depends('product_id')
    def _compute_custom_specs(self):
        for line in self:
            if not line.product_id:
                line.min_qty = 0.0
                line.min_weight = ''
                line.gross_net_weight = ''
                line.avg_serving = ''
                line.use_frozen = ''
                line.use_fresh = ''
                line.packing_info = ''
                line.allergens_notice = ''
                line.check_notes = ''
                line.mix_code = ''
                line.sort_seq = 0
                line.sales_line_html = False
                line.fish_info = ''
                line.ingredients_html = False
                line.notes_html = False
                line.cooking_instructions_html = False
                line.nutritional_info_html = False
                continue

            tmpl = line.product_id.product_tmpl_id
            line.min_qty = getattr(tmpl, 'min_qty', 0.0)
            line.min_weight = getattr(tmpl, 'min_weight', '')
            line.gross_net_weight = getattr(tmpl, 'gross_net_weight', '')
            line.avg_serving = getattr(tmpl, 'avg_serving', '')
            line.use_frozen = getattr(tmpl, 'use_frozen', '')
            line.use_fresh = getattr(tmpl, 'use_fresh', '')
            line.packing_info = getattr(tmpl, 'packing_info', '')
            line.allergens_notice = getattr(tmpl, 'allergens_notice', '')
            line.check_notes = getattr(tmpl, 'check_notes', '')
            line.mix_code = getattr(tmpl, 'mix_code', '')
            line.sort_seq = getattr(tmpl, 'sort_seq', 0)
            line.sales_line_html = getattr(tmpl, 'sales_line_html', False)
            line.fish_info = getattr(tmpl, 'fish_info', '')
            line.ingredients_html = getattr(tmpl, 'ingredients_html', False)
            line.notes_html = getattr(tmpl, 'notes_html', False)
            line.cooking_instructions_html = getattr(tmpl, 'cooking_instructions_html', False)
            line.nutritional_info_html = getattr(tmpl, 'nutritional_info_html', False)

    def action_open_food_specs_modal(self):
        """Opens popup modal for line specifications with fallback contexts."""
        self.ensure_one()
        view_id = self.env.ref('food_packaging_info.view_sale_order_line_food_specs_popup').id
        
        tmpl = self.product_id.product_tmpl_id if self.product_id else False

        return {
            'name': 'Food Packaging Specifications',
            'type': 'ir.actions.act_window',
            'res_model': 'sale.order.line',
            'res_id': self.id if isinstance(self.id, int) else False,
            'view_mode': 'form',
            'views': [(view_id, 'form')],
            'target': 'new',
            'context': {
                'default_min_qty': self.min_qty or (tmpl.min_qty if tmpl else 0.0),
                'default_min_weight': self.min_weight or (tmpl.min_weight if tmpl else ''),
                'default_gross_net_weight': self.gross_net_weight or (tmpl.gross_net_weight if tmpl else ''),
                'default_avg_serving': self.avg_serving or (tmpl.avg_serving if tmpl else ''),
                'default_use_frozen': self.use_frozen or (tmpl.use_frozen if tmpl else ''),
                'default_use_fresh': self.use_fresh or (tmpl.use_fresh if tmpl else ''),
                'default_packing_info': self.packing_info or (tmpl.packing_info if tmpl else ''),
                'default_allergens_notice': self.allergens_notice or (tmpl.allergens_notice if tmpl else ''),
                'default_check_notes': self.check_notes or (tmpl.check_notes if tmpl else ''),
                'default_mix_code': self.mix_code or (tmpl.mix_code if tmpl else ''),
                'default_sort_seq': self.sort_seq or (tmpl.sort_seq if tmpl else 0),
                'default_sales_line_html': self.sales_line_html or (tmpl.sales_line_html if tmpl else False),
                'default_fish_info': self.fish_info or (tmpl.fish_info if tmpl else ''),
                'default_ingredients_html': self.ingredients_html or (tmpl.ingredients_html if tmpl else False),
                'default_notes_html': self.notes_html or (tmpl.notes_html if tmpl else False),
                'default_cooking_instructions_html': self.cooking_instructions_html or (tmpl.cooking_instructions_html if tmpl else False),
                'default_nutritional_info_html': self.nutritional_info_html or (tmpl.nutritional_info_html if tmpl else False),
            }
        }

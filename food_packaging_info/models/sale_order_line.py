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

    from odoo import api, fields, models


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
                line.fish_info = ''
                line.ingredients_html = False
                line.notes_html = False
                line.cooking_instructions_html = False
                line.nutritional_info_html = False
                continue

            tmpl = line.product_id.product_tmpl_id
            line.min_qty = getattr(tmpl, 'min_qty', 0.0) or 0.0
            line.min_weight = getattr(tmpl, 'min_weight', '') or ''
            line.gross_net_weight = getattr(tmpl, 'gross_net_weight', '') or ''
            line.avg_serving = getattr(tmpl, 'avg_serving', '') or ''
            line.use_frozen = getattr(tmpl, 'use_frozen', '') or ''
            line.use_fresh = getattr(tmpl, 'use_fresh', '') or ''
            line.packing_info = getattr(tmpl, 'packing_info', '') or ''
            line.allergens_notice = getattr(tmpl, 'allergens_notice', '') or ''
            line.check_notes = getattr(tmpl, 'check_notes', '') or ''
            line.mix_code = getattr(tmpl, 'mix_code', '') or ''
            line.sort_seq = getattr(tmpl, 'sort_seq', 0) or 0
            line.fish_info = getattr(tmpl, 'fish_info', '') or ''
            line.ingredients_html = getattr(tmpl, 'ingredients_html', False)
            line.notes_html = getattr(tmpl, 'notes_html', False)
            line.cooking_instructions_html = getattr(tmpl, 'cooking_instructions_html', False)
            line.nutritional_info_html = getattr(tmpl, 'nutritional_info_html', False)

    def action_open_food_specs_modal(self):
        """Opens popup modal for line specifications with robust value retrieval."""
        self.ensure_one()
        view_id = self.env.ref('food_packaging_info.view_sale_order_line_food_specs_popup').id
        
        tmpl = self.product_id.product_tmpl_id if self.product_id else False

        # Helper function to get value from line first, then product template
        def get_val(field_name, default=''):
            val = getattr(self, field_name, None)
            if val:
                return val
            if tmpl:
                return getattr(tmpl, field_name, default)
            return default

        return {
            'name': 'Food Packaging Specifications',
            'type': 'ir.actions.act_window',
            'res_model': 'sale.order.line',
            'res_id': self.id if isinstance(self.id, int) else False,
            'view_mode': 'form',
            'views': [(view_id, 'form')],
            'target': 'new',
            'context': {
                'default_name': line_description,
                'default_min_qty': get_val('min_qty', 0.0),
                'default_min_weight': get_val('min_weight', ''),
                'default_gross_net_weight': get_val('gross_net_weight', ''),
                'default_avg_serving': get_val('avg_serving', ''),
                'default_use_frozen': get_val('use_frozen', ''),
                'default_use_fresh': get_val('use_fresh', ''),
                'default_packing_info': get_val('packing_info', ''),
                'default_allergens_notice': get_val('allergens_notice', ''),
                'default_check_notes': get_val('check_notes', ''),
                'default_mix_code': get_val('mix_code', ''),
                'default_sort_seq': get_val('sort_seq', 0),
                'default_fish_info': get_val('fish_info', ''),
                'default_ingredients_html': get_val('ingredients_html', False),
                'default_notes_html': get_val('notes_html', False),
                'default_cooking_instructions_html': get_val('cooking_instructions_html', False),
                'default_nutritional_info_html': get_val('nutritional_info_html', False),
            }
        }

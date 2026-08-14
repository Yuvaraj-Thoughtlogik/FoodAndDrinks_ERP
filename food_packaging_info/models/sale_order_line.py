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
  

    min_qty = fields.Float(string='Min Qty')
    min_weight = fields.Char(string='Min Weight')
    gross_net_weight = fields.Char(string='Weight (Gross/Net)')
    avg_serving = fields.Char(string='Average Serving')

    use_frozen = fields.Char(string='Use Frozen')
    use_fresh = fields.Char(string='Use Fresh')
    packing_info = fields.Char(string='Packing')

    allergens_notice = fields.Char(string='Allergens')
    check_notes = fields.Char(string='Check Notes')
    mix_code = fields.Char(string='Mix Code')
    sort_seq = fields.Integer(string='Sort Seq')

    fish_info = fields.Text(string='Fish Information')
    ingredients_html = fields.Html(string='Ingredients')
    notes_html = fields.Html(string='Notes')
    cooking_instructions_html = fields.Html(string='Cooking')
    nutritional_info_html = fields.Html(string='Nutrition')

    

    @api.onchange('product_id')
    def _onchange_product_id_custom_specs(self):
        for line in self:
    
            if not line.product_id:
                line.min_qty = 0.0
                line.min_weight = False
                line.gross_net_weight = False
                line.avg_serving = False
                line.use_frozen = False
                line.use_fresh = False
                line.packing_info = False
                line.allergens_notice = False
                line.check_notes = False
                line.mix_code = False
                line.sort_seq = 0
                line.fish_info = False
                line.ingredients_html = False
                line.notes_html = False
                line.cooking_instructions_html = False
                line.nutritional_info_html = False
                continue
    
            product = line.product_id
            template = product.product_tmpl_id
    
            
            def get_product_value(field_name, default=False):
                value = getattr(product, field_name, None)
    
                if value not in (None, False, ''):
                    return value
    
                value = getattr(template, field_name, None)
    
                if value not in (None, False, ''):
                    return value
    
                return default
    
           
    
            line.min_qty = get_product_value('min_qty', 0.0)
            line.min_weight = get_product_value('min_weight')
            line.gross_net_weight = get_product_value('gross_net_weight')
            line.avg_serving = get_product_value('avg_serving')
    
            line.use_frozen = get_product_value('use_frozen')
            line.use_fresh = get_product_value('use_fresh')
            line.packing_info = get_product_value('packing_info')
    
            line.allergens_notice = get_product_value('allergens_notice')
            line.check_notes = get_product_value('check_notes')
            line.mix_code = get_product_value('mix_code')
            line.sort_seq = get_product_value('sort_seq', 0)
    
            line.fish_info = get_product_value('fish_info')
            line.ingredients_html = get_product_value('ingredients_html')
            line.notes_html = get_product_value('notes_html')
            line.cooking_instructions_html = get_product_value(
                'cooking_instructions_html'
            )
            line.nutritional_info_html = get_product_value(
                'nutritional_info_html'
            )
    

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
    
            product_id = vals.get('product_id')
    
            if not product_id:
                continue
    
            product = self.env['product.product'].browse(product_id)
            template = product.product_tmpl_id
    
            def get_value(field_name, default=False):
                # First check product.product
                if hasattr(product, field_name):
                    value = getattr(product, field_name)
                    if value not in (None, False, ''):
                        return value
    
                
                if template and hasattr(template, field_name):
                    value = getattr(template, field_name)
                    if value not in (None, False, ''):
                        return value
    
                return default
    
            vals.update({
                'min_qty': get_value('min_qty', 0.0),
                'min_weight': get_value('min_weight', False),
                'gross_net_weight': get_value(
                    'gross_net_weight', False
                ),
                'avg_serving': get_value('avg_serving', False),
    
                'use_frozen': get_value('use_frozen', False),
                'use_fresh': get_value('use_fresh', False),
                'packing_info': get_value('packing_info', False),
    
                'allergens_notice': get_value(
                    'allergens_notice', False
                ),
                'check_notes': get_value(
                    'check_notes', False
                ),
                'mix_code': get_value('mix_code', False),
                'sort_seq': get_value('sort_seq', 0),
    
                'fish_info': get_value('fish_info', False),
                'ingredients_html': get_value(
                    'ingredients_html', False
                ),
                'notes_html': get_value(
                    'notes_html', False
                ),
                'cooking_instructions_html': get_value(
                    'cooking_instructions_html', False
                ),
                'nutritional_info_html': get_value(
                    'nutritional_info_html', False
                ),
            })
    
        return super().create(vals_list)

    

    def action_open_food_specs_modal(self):
        self.ensure_one()
    
        product = self.product_id
        template = product.product_tmpl_id if product else False
    
        def get_value(field_name, default=False):
    
            if product and hasattr(product, field_name):
                value = getattr(product, field_name)
    
                if value not in (None, False, ''):
                    return value
    
            if template and hasattr(template, field_name):
                value = getattr(template, field_name)
    
                if value not in (None, False, ''):
                    return value
    
            return default
    
        self.write({
            'min_qty': get_value('min_qty', 0.0),
            'min_weight': get_value('min_weight'),
            'gross_net_weight': get_value('gross_net_weight'),
            'avg_serving': get_value('avg_serving'),
    
            'use_frozen': get_value('use_frozen'),
            'use_fresh': get_value('use_fresh'),
            'packing_info': get_value('packing_info'),
    
            'allergens_notice': get_value('allergens_notice'),
            'check_notes': get_value('check_notes'),
            'mix_code': get_value('mix_code'),
            'sort_seq': get_value('sort_seq', 0),
    
            'fish_info': get_value('fish_info'),
            'ingredients_html': get_value('ingredients_html'),
            'notes_html': get_value('notes_html'),
            'cooking_instructions_html': get_value(
                'cooking_instructions_html'
            ),
            'nutritional_info_html': get_value(
                'nutritional_info_html'
            ),
        })
    
        view_id = self.env.ref(
            'food_packaging_info.view_sale_order_line_food_specs_popup'
        ).id
    
        return {
            'name': 'Food Packaging Specifications',
            'type': 'ir.actions.act_window',
            'res_model': 'sale.order.line',
            'res_id': self.id,
            'view_mode': 'form',
            'views': [(view_id, 'form')],
            'target': 'new',
        }

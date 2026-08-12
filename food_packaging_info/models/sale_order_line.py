from odoo import api, fields, models

from odoo import fields, models


from odoo import api, fields, models


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    # Line Item Selector
    selected_line_id = fields.Many2one('sale.order.line', string="Selected Line Item")

    # Related fields pointing to the selected order line
    line_avg_serving = fields.Char(related='selected_line_id.avg_serving', string="Average Serving", readonly=False)
    line_min_weight = fields.Char(related='selected_line_id.min_weight', string="Min. Weight", readonly=False)
    line_gross_net_weight = fields.Char(related='selected_line_id.gross_net_weight', string="Gross / Net Weight", readonly=False)
    line_as_supplied = fields.Boolean(related='selected_line_id.as_supplied', string="As Supplied", readonly=False)
    line_bingo_flag = fields.Boolean(related='selected_line_id.bingo_flag', string="Bingo", readonly=False)
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

    # Serving & Weight Specifications
    avg_serving = fields.Char(string="Average Serving")
    min_weight = fields.Char(string="Min. Weight")
    gross_net_weight = fields.Char(string="Gross / Net Weight")
    as_supplied = fields.Boolean(string="As Supplied")
    bingo_flag = fields.Boolean(string="Bingo")
    check_notes = fields.Char(string="Check Notes")
    allergens_notice = fields.Char(string="Allergens Notice")

    # Recipe & Cooking Specifications
    fish_info = fields.Text(string="Fish Information")
    ingredients_html = fields.Html(string="Ingredients")
    cooking_instructions_html = fields.Html(string="Cooking Instructions")
    nutritional_info_html = fields.Html(string="Nutritional Info")

    @api.onchange('product_id')
    def _onchange_product_id_copy_food_specs(self):
        """Triggers INSTANTLY in the user browser before saving the record."""
        if not self.product_id:
            self.avg_serving = False
            self.min_weight = False
            self.gross_net_weight = False
            self.as_supplied = False
            self.bingo_flag = False
            self.check_notes = False
            self.allergens_notice = False
            self.fish_info = False
            self.ingredients_html = False
            self.cooking_instructions_html = False
            self.nutritional_info_html = False
            return

        tmpl = self.product_id.product_tmpl_id

        # Copy values to active memory immediately
        self.avg_serving = getattr(tmpl, 'avg_serving', '')
        self.min_weight = getattr(tmpl, 'min_weight', '')
        self.gross_net_weight = getattr(tmpl, 'gross_net_weight', '')
        self.as_supplied = getattr(tmpl, 'as_supplied', False)
        self.bingo_flag = getattr(tmpl, 'bingo_flag', False)
        self.check_notes = getattr(tmpl, 'check_notes', '')
        self.allergens_notice = getattr(tmpl, 'allergens_notice', '')
        self.fish_info = getattr(tmpl, 'fish_info', '')
        self.ingredients_html = getattr(tmpl, 'ingredients_html', False)
        self.cooking_instructions_html = getattr(tmpl, 'cooking_instructions_html', False)
        self.nutritional_info_html = getattr(tmpl, 'nutritional_info_html', False)

    def action_open_food_specs_modal(self):
        """Opens popup modal for line specifications."""
        self.ensure_one()
        view_id = self.env.ref('food_packaging_info.view_sale_order_line_food_specs_popup').id
        return {
            'name': 'Food Packaging Specifications',
            'type': 'ir.actions.act_window',
            'res_model': 'sale.order.line',
            'res_id': self.id,
            'view_mode': 'form',
            'views': [(view_id, 'form')],
            'target': 'new',
        }

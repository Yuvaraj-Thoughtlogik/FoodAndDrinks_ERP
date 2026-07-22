from odoo import models, api, fields, _

class SaleOrder(models.Model):
    _inherit = 'sale.order'

    
    batch_id = fields.Many2one(
        'round.management.batch', 
        string='Round Batch', 
        ondelete='set null',
        index=True
    )
    
    round_id = fields.Many2one(
        'round.management.round', 
        string='Delivery Round',
        index=True, domain="[('state', '=', 'active')]"
    )
    round_code = fields.Char(related='round_id.code', string='Round Code', store=True)
    
    is_late_order = fields.Boolean(string="Late Order")
    has_card_reader = fields.Boolean(string="Card Reader")
    is_pickup = fields.Boolean(string="Pickup")
    is_b2b = fields.Boolean(string="B2B")
   
    commitment_date = fields.Datetime(
        string='Delivery Date', 
        compute='_compute_batch_delivery_info', 
        store=True, 
        readonly=False
    )
    delivery_time_slot = fields.Selection([
        ('08:00_12:00', '08:00 to 12:00'),
        ('12:00_16:00', '12:00 to 16:00'),
        ('13:00_19:00', '13:00 to 19:00'),
        ('18:00_21:00', '18:00 to 21:00'),
    ], string='Delivery Times', help="Independent delivery time selection")

    
    week_number = fields.Char(
        string='ISO Week No.', 
        compute='_compute_batch_delivery_info', 
        store=True, 
        readonly=False,
        help="Calculated week and year format (e.g. 202631)"
    )
    permanent_notes = fields.Html(string='Permanent Notes')
    
    @api.onchange('partner_id')
    def _onchange_partner_id_permanent_notes(self):
        """Optionally pull permanent notes directly from customer master when selected."""
        if self.partner_id and hasattr(self.partner_id, 'permanent_notes'):
            self.permanent_notes = self.partner_id.permanent_notes

    @api.depends('batch_id', 'batch_id.delivery_date', 'batch_id.week_number')
    def _compute_batch_delivery_info(self):
        for order in self:
            if order.batch_id:
               
                if order.batch_id.delivery_date:
                    order.commitment_date = fields.Datetime.to_datetime(order.batch_id.delivery_date)
                order.week_number = order.batch_id.week_number
    @api.onchange('partner_id')
    def _onchange_partner_id_set_round(self):
        if self.partner_id and self.partner_id.round_id:
            self.round_id = self.partner_id.round_id
            
            
    def action_select_alt_delivery_round(self):
        """Opens round list view where user clicks row button to select."""
        self.ensure_one()
        return {
            'name': _('Select Alternative Delivery Round'),
            'type': 'ir.actions.act_window',
            'res_model': 'round.management.round',
            'view_mode': 'list',
            'view_id': self.env.ref('round_management.view_round_management_round_list_select').id,
            'target': 'new',
            'context': {
                'active_sale_order_id': self.id,
            }
        }

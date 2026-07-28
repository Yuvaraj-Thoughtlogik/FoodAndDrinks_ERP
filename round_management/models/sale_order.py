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
    
    @api.onchange('partner_shipping_id', 'partner_id')
    def _onchange_partner_update_address_notes(self):
        """Pulls and formats the full address of the selected customer/delivery address."""
       
        partner = self.partner_shipping_id or self.partner_id
        
        if partner:
           
            self.permanent_notes = partner._display_address(without_company=True)
            # self.permanent_notes = partner.contact_address
        else:
            self.permanent_notes = False

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
        """Populates wizard lines with Round Batches and opens the modal."""
        self.ensure_one()
        
        # Fetch active batches
        batches = self.env['round.management.batch'].search([])
        
        lines = [(0, 0, {
            'batch_id': batch_rec.id,
            'selected': (batch_rec.id == getattr(self, 'batch_id', self.env['round.management.batch']).id)
        }) for batch_rec in batches]

        wizard = self.env['select.alt.round.wizard'].create({
            'sale_order_id': self.id,
            'line_ids': lines,
        })

        return {
            'name': _('Select Alternative Delivery Round Batch'),
            'type': 'ir.actions.act_window',
            'res_model': 'select.alt.round.wizard',
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'new',
        }

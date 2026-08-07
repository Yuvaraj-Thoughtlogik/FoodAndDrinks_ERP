from odoo import models, api, fields
from odoo.tools import _
from datetime import datetime, time


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
   
    is_pickup = fields.Boolean(string="Pet Food / Pickup Order")
    is_b2b = fields.Boolean(string="B2B")
   
    commitment_date = fields.Datetime(
        string='Delivery Date', 
        compute='_compute_batch_delivery_info', 
        store=True, 
        readonly=False
    )
    delivery_date = fields.Date(string="Delivery Date",compute='_compute_batch_delivery_info',store=True, readonly=False)
    # delivery_time_slot = fields.Selection([
    #     ('08:00_12:00', '08:00 to 12:00'),
    #     ('12:00_16:00', '12:00 to 16:00'),
    #     ('13:00_19:00', '13:00 to 19:00'),
    #     ('18:00_21:00', '18:00 to 21:00'),
    # ], string='Delivery Times', help="Independent delivery time selection")

    
    week_number = fields.Char(
        string='ISO Week No.', 
        compute='_compute_batch_delivery_info', 
        store=True, 
        readonly=False,
        help="Calculated week and year format (e.g. 202631)"
    )
    permanent_notes = fields.Html(
        string='Permanent Notes',
        compute='_compute_permanent_notes',
        store=True,
        readonly=True
    )

    @api.depends('partner_id', 'partner_shipping_id','partner_id.comment')
    def _compute_permanent_notes(self):
        for order in self:
            partner = order.partner_shipping_id or order.partner_id
            order.permanent_notes = partner.comment if partner and partner.comment else False
    
    requested_delivery_after = fields.Float(string="Requested Delivery After")
    requested_delivery_before = fields.Float(string="Requested Delivery Before")
    last_ring_date = fields.Date(string="Last Ring Date")
    delivery_day_name = fields.Char(string="Day Name", compute="_compute_delivery_day_name")

    no_between_times_round = fields.Boolean(
        related='round_id.no_between_times',
        string='No Between Times on Round',
        readonly=True
    )
    delivery_times = fields.Char(
        string='Delivery Times',
        compute='_compute_delivery_times',
        store=True,
        readonly=True,
        help="Operating delivery times calculated from round configuration"
    )

    _DAY_FIELDS = {
        0: ('mon_active', 'mon_from', 'mon_to'),  # Monday
        1: ('tue_active', 'tue_from', 'tue_to'),  # Tuesday
        2: ('wed_active', 'wed_from', 'wed_to'),  # Wednesday
        3: ('thu_active', 'thu_from', 'thu_to'),  # Thursday
        4: ('fri_active', 'fri_from', 'fri_to'),  # Friday
        5: ('sat_active', 'sat_from', 'sat_to'),  # Saturday
        6: ('sun_active', 'sun_from', 'sun_to'),  # Sunday
    }

    @api.depends(
        'commitment_date', 'round_id',
        'round_id.mon_active', 'round_id.mon_from', 'round_id.mon_to',
        'round_id.tue_active', 'round_id.tue_from', 'round_id.tue_to',
        'round_id.wed_active', 'round_id.wed_from', 'round_id.wed_to',
        'round_id.thu_active', 'round_id.thu_from', 'round_id.thu_to',
        'round_id.fri_active', 'round_id.fri_from', 'round_id.fri_to',
        'round_id.sat_active', 'round_id.sat_from', 'round_id.sat_to',
        'round_id.sun_active', 'round_id.sun_from', 'round_id.sun_to',
    )
    def _compute_delivery_times(self):
        for order in self:
            if order.commitment_date and order.round_id:
                local_dt = fields.Datetime.context_timestamp(order, order.commitment_date)
                weekday = local_dt.weekday()
                active_field, from_field, to_field = order._DAY_FIELDS[weekday]
                round_rec = order.round_id
                if round_rec[active_field]:
                    from_val = round_rec[from_field]
                    to_val = round_rec[to_field]
                    from_str = order._format_time(from_val)
                    to_str = order._format_time(to_val)
                    order.delivery_times = "%s to %s" % (from_str, to_str)
                else:
                    order.delivery_times = "Not Available"
            else:
                order.delivery_times = False

    @staticmethod
    def _format_time(value):
        if value in (False, None, ''):
            return ""

        # Normalize to a float number of hours first
        if isinstance(value, str):
            value = value.strip()
            if ':' in value:
                # e.g. "5:00", "05:30"
                h_str, m_str = value.split(':', 1)
                try:
                    hours = int(h_str)
                    minutes = int(m_str)
                except ValueError:
                    return value  # fallback: unparseable, show as-is
            else:
                # e.g. "5", "5.5"
                try:
                    float_val = float(value)
                    hours = int(float_val)
                    minutes = int(round((float_val - hours) * 60))
                except ValueError:
                    return value  # fallback: unparseable, show as-is
        elif isinstance(value, (int, float)):
            hours = int(value)
            minutes = int(round((value - hours) * 60))
        else:
            return ""

        return "%02d:%02d" % (hours, minutes)

    @api.depends('commitment_date')
    def _compute_delivery_day_name(self):
        for order in self:
            if order.commitment_date:
                order.delivery_day_name = f"({order.commitment_date.strftime('%a')})"
            else:
                order.delivery_day_name = ""


    @api.depends('batch_id', 'batch_id.delivery_date', 'batch_id.week_number')
    def _compute_batch_delivery_info(self):
        for order in self:
            if order.batch_id:
                order.delivery_date = order.batch_id.delivery_date
                order.week_number = order.batch_id.week_number

                if order.batch_id.delivery_date:
                    order.commitment_date = datetime.combine(
                        order.batch_id.delivery_date,
                        time.min
                    )
                else:
                    order.commitment_date = False
            else:
                order.delivery_date = False
                order.week_number = False
                order.commitment_date = False



    @api.onchange('partner_id')
    def _onchange_partner_id_set_round(self):
        if self.partner_id and self.partner_id.round_id:
            self.round_id = self.partner_id.round_id
            
            
    def action_select_alt_delivery_round(self):
        """Populates wizard lines with Round Batches and opens the modal."""
        self.ensure_one()

        alt_round_ids = self.round_id.alt_round_ids.mapped('alt_round_id').ids if self.round_id else []

        batches = self.env['round.management.batch'].search([
            ('round_id', 'in', alt_round_ids),
            ('state', 'in', ['act', 'pln']),
        ])

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

    def action_duplicate(self):
        self.ensure_one()
        new_record = self.copy()

        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': new_record.id,
            'view_mode': 'form',
            'target': 'current',
        }

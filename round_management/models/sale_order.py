from odoo import models, api, fields
from odoo.exceptions import UserError
from odoo.tools import _
from datetime import datetime, time
import pytz


DEFAULT_DELIVERY_TIME = time(23, 59)  # 11:00 PM (local time)

class SaleOrder(models.Model):
    _inherit = 'sale.order'

    
    batch_id = fields.Many2one(
        'round.management.batch', 
        string='Round Batch', 
        ondelete='set null',
        index=True,
        domain="[('round_id', '=?', round_id), ('state', 'in', ['act', 'prt'])]",
    )
    
    round_id = fields.Many2one(
        'round.management.round', 
        string='Delivery Round',
        index=True, domain="[('state', '=', 'active')]",
        compute='_compute_partner_id_set_round',
        store=True,
    )
    round_code = fields.Char(related='round_id.code', string='Round Code', store=True)
    
    is_late_order = fields.Boolean(
        string="Late Order",
        compute='_compute_is_late_order',
        readonly=False,
        store=True
    )
   
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
    round_full_name = fields.Char(compute='_compute_round_full_name', store=True)

    @api.depends('round_id.code', 'round_id.name')
    def _compute_round_full_name(self):
        for rec in self:
            if rec.round_id:
                rec.round_full_name = f'{rec.round_id.code}-{rec.round_id.name}'
            else:
                rec.round_full_name = False

    _DAY_FIELDS = {
        0: ('mon_active', 'mon_from', 'mon_to'),  # Monday
        1: ('tue_active', 'tue_from', 'tue_to'),  # Tuesday
        2: ('wed_active', 'wed_from', 'wed_to'),  # Wednesday
        3: ('thu_active', 'thu_from', 'thu_to'),  # Thursday
        4: ('fri_active', 'fri_from', 'fri_to'),  # Friday
        5: ('sat_active', 'sat_from', 'sat_to'),  # Saturday
        6: ('sun_active', 'sun_from', 'sun_to'),  # Sunday
    }
    
    is_alternative_round = fields.Boolean(
        string="Is Alternative Round",
        default=False,
        compute= "_compute_is_alternative_round",
        store=True,
    )

    @api.depends('batch_id','batch_id.round_id','round_id')
    def _compute_is_alternative_round(self):
        for rec in self:
            rec.is_alternative_round = True if rec.batch_id.round_id != rec.round_id else False
    

    def action_confirm(self):
        """Enforces Max. Alternative Drops limit during Sales Order confirmation."""
        for order in self:
            if order.is_alternative_round:

                if order.batch_id.is_alt_limit_reached:
                    raise UserError(_("Max Alternative Drops have been reached."))

        return super(SaleOrder, self).action_confirm()

    @api.depends('batch_id', 'batch_id.delivery_times')
    def _compute_delivery_times(self):
        for order in self:
            order.delivery_times = order.batch_id.delivery_times if order.batch_id else False

    @api.depends('partner_id', 'partner_shipping_id','partner_id.comment')
    def _compute_permanent_notes(self):
        for order in self:
            partner = order.partner_shipping_id or order.partner_id
            order.permanent_notes = partner.comment if partner and partner.comment else False

    def _local_time_to_utc_datetime(self, date_val, local_time):
        """Combine a date with a local time and return the equivalent naive
        UTC datetime, since commitment_date (Datetime field) is stored
        internally in UTC but should represent a fixed local wall-clock time.
        """
        self.ensure_one()
        tz_name = self.env.user.tz or 'UTC'
        local_tz = pytz.timezone(tz_name)
        naive_local_dt = datetime.combine(date_val, local_time)
        localized_dt = local_tz.localize(naive_local_dt)
        utc_dt = localized_dt.astimezone(pytz.UTC).replace(tzinfo=None)
        return utc_dt



    @api.depends('batch_id')
    def _compute_is_late_order(self):
        for rec in self:
            if rec.batch_id and rec.batch_id.state == 'prt':
                rec.is_late_order = True
            else:
                rec.is_late_order = False

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
                        DEFAULT_DELIVERY_TIME
                    )
                else:
                    order.commitment_date = False
            else:
                order.delivery_date = False
                order.week_number = False
                order.commitment_date = False

    @api.onchange('commitment_date')
    def _onchange_commitment_date_sync_delivery_date(self):
        for order in self:
            order.delivery_date = order.commitment_date.date() if order.commitment_date else False

    @api.onchange('delivery_date')
    def _onchange_delivery_date_sync_commitment_date(self):
        for order in self:
            if order.delivery_date:
                order.commitment_date = order._local_time_to_utc_datetime(
                    order.delivery_date, DEFAULT_DELIVERY_TIME
                )
            else:
                order.commitment_date = False

    def write(self, vals):
        res = super().write(vals)

        if self.env.context.get('skip_date_sync'):
            return res

        if 'commitment_date' in vals and 'delivery_date' not in vals:
            for order in self:
                new_delivery_date = order.commitment_date.date() if order.commitment_date else False
                if order.delivery_date != new_delivery_date:
                    order.with_context(skip_date_sync=True).write({
                        'delivery_date': new_delivery_date
                    })

        elif 'delivery_date' in vals and 'commitment_date' not in vals:
            for order in self:
                if order.delivery_date:
                    new_commitment_date = order._local_time_to_utc_datetime(
                        order.delivery_date, DEFAULT_DELIVERY_TIME
                    )
                else:
                    new_commitment_date = False
                if order.commitment_date != new_commitment_date:
                    order.with_context(skip_date_sync=True).write({
                        'commitment_date': new_commitment_date
                    })

        return res


    @api.depends('partner_id','partner_id.round_id')
    def _compute_partner_id_set_round(self):
        for rec in self:
            if rec.partner_id and rec.partner_id.round_id:
                rec.round_id = rec.partner_id.round_id
            else:
                rec.round_id = False
            
            
    def action_select_alt_delivery_round(self):
        """Populates wizard lines with Round Batches and opens the modal."""
        self.ensure_one()

        alt_round_ids = self.round_id.alt_round_ids.mapped('alt_round_id').ids if self.round_id else []

        batches = self.env['round.management.batch'].search([
            ('round_id', 'in', alt_round_ids),
            ('state', 'in', ['act', 'prt', 'pln']),
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

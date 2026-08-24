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
        readonly=False,
        copy=True,
    )
    delivery_date = fields.Date(
        string="Delivery Date",
        compute='_compute_batch_delivery_info',
        store=True, 
        readonly=False,
        copy=True,
    )
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
    # delivery_times = fields.Char(
    #     string='Delivery Times',
    #     compute='_compute_delivery_times',
    #     store=True,
    #     readonly=True,
    #     help="Operating delivery times calculated from round configuration"
    # )
    delivery_times = fields.Char(
        string='Delivery Times',
        compute='_compute_delivery_times',
        store=True,
        readonly=True,
        help="Delivery times copied from the selected batch"
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
        if not date_val:
            return False
        tz_name = self.env.user.tz or 'UTC'
        local_tz = pytz.timezone(tz_name)
        naive_local_dt = datetime.combine(date_val, local_time)
        localized_dt = local_tz.localize(naive_local_dt)
        utc_dt = localized_dt.astimezone(pytz.UTC).replace(tzinfo=None)
        return utc_dt


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

    @api.depends('batch_id')
    def _compute_is_late_order(self):
        for rec in self:
            if rec.batch_id and rec.batch_id.state == 'prt':
                rec.is_late_order = True
            else:
                rec.is_late_order = False

    @api.depends('delivery_date', 'commitment_date')
    def _compute_delivery_day_name(self):
        for order in self:
            target_date = order.delivery_date
            if not target_date and order.commitment_date:
                local_dt = fields.Datetime.context_timestamp(order, order.commitment_date)
                target_date = local_dt.date()
            if target_date:
                order.delivery_day_name = f"({target_date.strftime('%a')})"
            else:
                order.delivery_day_name = ""

    @api.depends('batch_id', 'batch_id.delivery_date', 'batch_id.week_number')
    def _compute_batch_delivery_info(self):
        for order in self:
            if order.batch_id:
                order.delivery_date = order.batch_id.delivery_date
                order.week_number = order.batch_id.week_number

                if order.batch_id.delivery_date:
                    order.commitment_date = order._local_time_to_utc_datetime(
                        order.batch_id.delivery_date,
                        DEFAULT_DELIVERY_TIME
                    )
                else:
                    order.commitment_date = False
            else:
                if order.delivery_date:
                    iso_year, iso_week, _ = order.delivery_date.isocalendar()
                    order.week_number = f"{iso_year}{str(iso_week).zfill(2)}"
                    if not order.commitment_date:
                        order.commitment_date = order._local_time_to_utc_datetime(
                            order.delivery_date, DEFAULT_DELIVERY_TIME
                        )
                else:
                    order.delivery_date = False
                    order.week_number = False
                    order.commitment_date = False

    @api.onchange('commitment_date')
    def _onchange_commitment_date_sync_delivery_date(self):
        for order in self:
            if order.commitment_date:
                local_dt = fields.Datetime.context_timestamp(order, order.commitment_date)
                order.delivery_date = local_dt.date()
                iso_year, iso_week, _ = order.delivery_date.isocalendar()
                order.week_number = f"{iso_year}{str(iso_week).zfill(2)}"
            else:
                order.delivery_date = False

    @api.onchange('delivery_date')
    def _onchange_delivery_date_sync_commitment_date(self):
        for order in self:
            if order.delivery_date:
                order.commitment_date = order._local_time_to_utc_datetime(
                    order.delivery_date, DEFAULT_DELIVERY_TIME
                )
                iso_year, iso_week, _ = order.delivery_date.isocalendar()
                order.week_number = f"{iso_year}{str(iso_week).zfill(2)}"
            else:
                order.commitment_date = False

    @api.model_create_multi
    def create(self, vals_list):
        tz_name = self.env.user.tz or 'UTC'
        local_tz = pytz.timezone(tz_name)
        for vals in vals_list:
            if vals.get('delivery_date') and not vals.get('commitment_date'):
                d_date = fields.Date.to_date(vals['delivery_date'])
                naive_dt = datetime.combine(d_date, DEFAULT_DELIVERY_TIME)
                vals['commitment_date'] = local_tz.localize(naive_dt).astimezone(pytz.UTC).replace(tzinfo=None)
                if not vals.get('week_number'):
                    iso_year, iso_week, _ = d_date.isocalendar()
                    vals['week_number'] = f"{iso_year}{str(iso_week).zfill(2)}"
            elif vals.get('commitment_date') and not vals.get('delivery_date'):
                c_dt = fields.Datetime.to_datetime(vals['commitment_date'])
                local_d = pytz.UTC.localize(c_dt).astimezone(local_tz).date()
                vals['delivery_date'] = local_d
                if not vals.get('week_number'):
                    iso_year, iso_week, _ = local_d.isocalendar()
                    vals['week_number'] = f"{iso_year}{str(iso_week).zfill(2)}"

        return super().create(vals_list)

    def write(self, vals):
        if not self.env.context.get('skip_date_sync'):
            tz_name = self.env.user.tz or 'UTC'
            local_tz = pytz.timezone(tz_name)

            if 'delivery_date' in vals and 'commitment_date' not in vals:
                if vals.get('delivery_date'):
                    d_date = fields.Date.to_date(vals['delivery_date'])
                    naive_dt = datetime.combine(d_date, DEFAULT_DELIVERY_TIME)
                    vals['commitment_date'] = local_tz.localize(naive_dt).astimezone(pytz.UTC).replace(tzinfo=None)
                    if 'week_number' not in vals:
                        iso_year, iso_week, _ = d_date.isocalendar()
                        vals['week_number'] = f"{iso_year}{str(iso_week).zfill(2)}"
                else:
                    vals['commitment_date'] = False

            elif 'commitment_date' in vals and 'delivery_date' not in vals:
                if vals.get('commitment_date'):
                    c_dt = fields.Datetime.to_datetime(vals['commitment_date'])
                    local_d = pytz.UTC.localize(c_dt).astimezone(local_tz).date()
                    vals['delivery_date'] = local_d
                    if 'week_number' not in vals:
                        iso_year, iso_week, _ = local_d.isocalendar()
                        vals['week_number'] = f"{iso_year}{str(iso_week).zfill(2)}"
                else:
                    vals['delivery_date'] = False

        return super().write(vals)


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

    def copy(self, default=None):
        self.ensure_one()
        default = dict(default or {})
        if 'delivery_date' not in default and self.delivery_date:
            default['delivery_date'] = self.delivery_date
        if 'commitment_date' not in default and self.commitment_date:
            default['commitment_date'] = self.commitment_date
        if 'week_number' not in default and self.week_number:
            default['week_number'] = self.week_number
        if 'batch_id' not in default and self.batch_id:
            default['batch_id'] = self.batch_id.id
        return super().copy(default=default)

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

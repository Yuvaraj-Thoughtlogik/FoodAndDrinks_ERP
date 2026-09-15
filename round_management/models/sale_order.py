from odoo import models, api, fields
from odoo.exceptions import UserError
from odoo.tools import _
from datetime import datetime, time
import pytz
import re

DEFAULT_DELIVERY_TIME = time(23, 59)  # 11:00 PM (local time)


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    batch_id = fields.Many2one(
        'round.management.batch',
        string='Round Batch',
        ondelete='set null',
        index=True,
        copy=True,
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

    is_staff_order = fields.Boolean(
        string="Staff Order",
        compute='_compute_is_staff_order',
        store=True,
        readonly=False,
    )
    is_b2b = fields.Boolean(
        string="B2B",
        compute='_compute_is_b2b',
        store=True,
        readonly=False,
    )

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
        compute="_compute_is_alternative_round",
        store=True,
    )
    # Payment Modes
    pay_card_reader = fields.Boolean(string="Card Reader", default=False)
    pay_kb = fields.Boolean(string="K/B", default=False)
    pay_lnp = fields.Boolean(string="LNP", default=False)
    pay_cash = fields.Boolean(string="Cash", default=False)
    pay_cheque = fields.Boolean(string="Cheque", default=False)
    pay_card = fields.Boolean(string="Card", default=False)

    delivery_channel = fields.Selection(
        selection=[
            ('regal_van', 'Regal Van Delivery'),
            ('courier', 'Courier Delivery'),
        ],
        string='Delivery Channel',
        compute='_compute_delivery_channel',
        store=True,
        readonly=False,
        help="Automatically mapped based on the selected Round Batch."
    )

    @api.depends('batch_id', 'batch_id.delivery_channel')
    def _compute_delivery_channel(self):
        for order in self:
            if order.batch_id and order.batch_id.delivery_channel:
                order.delivery_channel = order.batch_id.delivery_channel
            elif not order.delivery_channel:
                order.delivery_channel = False

    @api.onchange('batch_id')
    def _onchange_batch_id_set_delivery_channel(self):
        if self.batch_id and self.batch_id.delivery_channel:
            self.delivery_channel = self.batch_id.delivery_channel


    @api.onchange('pay_card_reader')
    def _onchange_pay_card_reader(self):
        if self.pay_card_reader:
            self.pay_kb = False
            self.pay_lnp = False
            self.pay_cash = False
            self.pay_cheque = False
            self.pay_card = False

    @api.onchange('pay_kb')
    def _onchange_pay_kb(self):
        if self.pay_kb:
            self.pay_card_reader = False
            self.pay_lnp = False
            self.pay_cash = False
            self.pay_cheque = False
            self.pay_card = False

    @api.onchange('pay_lnp')
    def _onchange_pay_lnp(self):
        if self.pay_lnp:
            self.pay_card_reader = False
            self.pay_kb = False
            self.pay_cash = False
            self.pay_cheque = False
            self.pay_card = False

    @api.onchange('pay_cash')
    def _onchange_pay_cash(self):
        if self.pay_cash:
            self.pay_card_reader = False
            self.pay_kb = False
            self.pay_lnp = False
            self.pay_cheque = False
            self.pay_card = False

    @api.onchange('pay_cheque')
    def _onchange_pay_cheque(self):
        if self.pay_cheque:
            self.pay_card_reader = False
            self.pay_kb = False
            self.pay_lnp = False
            self.pay_cash = False
            self.pay_card = False

    @api.onchange('pay_card')
    def _onchange_pay_card(self):
        if self.pay_card:
            self.pay_card_reader = False
            self.pay_kb = False
            self.pay_lnp = False
            self.pay_cash = False
            self.pay_cheque = False

    @api.depends('batch_id', 'batch_id.round_id', 'round_id')
    def _compute_is_alternative_round(self):
        for rec in self:
            rec.is_alternative_round = True if rec.batch_id.round_id != rec.round_id else False

    def action_confirm(self):
        """Enforces Max. Alternative Drops limit and links round batch to delivery pickings."""

        for order in self:
            if order.is_alternative_round and order.batch_id.is_alt_limit_reached:
                raise UserError(
                    _("Max Alternative Drops have been reached for batch '%s'.") % order.batch_id.display_name)
        res = super().action_confirm()
        for order in self:
            if order.batch_id:
                valid_pickings = order.picking_ids.filtered(lambda p: p.state != 'cancel')
                if valid_pickings:
                    # Pass context to bypass stock_picking_batch sanity checks and user assignments
                    valid_pickings.with_context(
                        building_backorder=True,
                        dont_check_company=True
                    ).write({'batch_id': order.batch_id.id})

        return res

    @api.depends('batch_id', 'batch_id.delivery_times')
    def _compute_delivery_times(self):
        for order in self:
            order.delivery_times = order.batch_id.delivery_times if order.batch_id else False

    @api.depends('partner_id', 'partner_shipping_id', 'partner_id.comment')
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
                # %A returns full day name (e.g. Wednesday)
                order.delivery_day_name = f"({target_date.strftime('%A')})"
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

    @api.depends('partner_id', 'partner_id.round_id')
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
        orders = self.browse()
        for order in self:
            order_default = dict(default or {})
            if 'delivery_date' not in order_default and order.delivery_date:
                order_default['delivery_date'] = order.delivery_date
            if 'commitment_date' not in order_default and order.commitment_date:
                order_default['commitment_date'] = order.commitment_date
            if 'week_number' not in order_default and order.week_number:
                order_default['week_number'] = order.week_number
            if 'batch_id' not in order_default and order.batch_id:
                order_default['batch_id'] = order.batch_id.id
            orders |= super(SaleOrder, order).copy(default=order_default)
        return orders

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

    @api.depends('pricelist_id', 'pricelist_id.pricelist_category', 'partner_id', 'partner_id.customer_type')
    def _compute_is_b2b(self):
        """Computes whether the order is B2B using Pricelist Category or Partner Customer Type."""
        for order in self:
            if order.pricelist_id and order.pricelist_id.pricelist_category == 'b2b':
                order.is_b2b = True
            #elif order.partner_id and order.partner_id.customer_type == 'b2b_trade':
                #order.is_b2b = True
            else:
                order.is_b2b = False

    @api.depends('pricelist_id', 'pricelist_id.pricelist_category')
    def _compute_is_staff_order(self):
        """Computes whether the order uses a Staff pricelist based on Pricelist Category."""
        for order in self:
            if order.pricelist_id:
                order.is_staff_order = (order.pricelist_id.pricelist_category == 'staff')
            else:
                order.is_staff_order = False
            
    @api.depends('partner_id', 'partner_id.round_id')
    def _compute_partner_id_set_round(self):
        for rec in self:
            if rec.partner_id and rec.partner_id.round_id:
                rec.round_id = rec.partner_id.round_id
            else:
                rec.round_id = False
    
    @api.depends('round_id')
    def _compute_auto_select_batch_id(self):
        today = fields.Date.context_today(self)
        for order in self:
            if not order.round_id:
                order.batch_id = False
                continue

            # Find the nearest future or today's active batch
            next_batch = self.env['round.management.batch'].search([
                ('round_id', '=', order.round_id.id),
                ('state', 'in', ['act']),
                ('delivery_date', '>=', today),
            ], order='delivery_date asc, id asc', limit=1)

            # Fallback to the most recent past batch if no upcoming batch exists
            if not next_batch:
                next_batch = self.env['round.management.batch'].search([
                    ('round_id', '=', order.round_id.id),
                    ('state', 'in', ['act']),
                ], order='delivery_date desc, id desc', limit=1)

            order.batch_id = next_batch.id if next_batch else False
            
    @api.onchange('round_id')
    def _onchange_round_id_auto_select_next_batch(self):
        """
        Automatically selects the next active ('act') batch for the selected main round.
        Picks the nearest upcoming active batch based on delivery date.
        """
        if not self.round_id:
            self.batch_id = False
            return

        today = fields.Date.context_today(self)

        # 1. Search for the nearest future or today's active batch ('act' only)
        next_batch = self.env['round.management.batch'].search([
            ('round_id', '=', self.round_id.id),
            ('state', '=', 'act'),
            ('delivery_date', '>=', today),
        ], order='delivery_date asc, id asc', limit=1)

        # 2. Fallback: if no future active batch exists, pick the most recent active batch
        if not next_batch:
            next_batch = self.env['round.management.batch'].search([
                ('round_id', '=', self.round_id.id),
                ('state', '=', 'act'),
            ], order='delivery_date desc, id desc', limit=1)

        self.batch_id = next_batch if next_batch else False
            
class SaleOrderSpecialNote(models.Model):
    _name = 'sale.order.special.note'
    _description = 'Special Requirements Note'
    _order = 'name'

    name = fields.Char(string="Note", required=True)



class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    special_requirements_notes_id = fields.Many2one(
        'sale.order.special.note',
        string="Special Notes",
        ondelete='set null',
    )
    
class Pricelist(models.Model):
    _inherit = 'product.pricelist'

    pricelist_category = fields.Selection([
        ('staff', 'Staff'),
        ('b2b', 'B2B'),
        ('standard', 'Standard'),
    ], string="Pricelist Category", default='standard', required=True)
    
    
class ProductProduct(models.Model):
    _inherit = 'product.product'

    def _compute_display_name(self):
        super()._compute_display_name()
        for product in self:
            if product.display_name:
                # Strips [code] prefix from selected field display
                product.display_name = re.sub(r'^\[.*?\]\s*', '', product.display_name)

    @api.model
    def _name_search(self, name='', domain=None, operator='ilike', limit=100, order=None):
        # Pass display_default_code=False in context to suppress right-hand reference column in dropdown
        res = super(ProductProduct, self.with_context(display_default_code=False))._name_search(
            name=name, domain=domain, operator=operator, limit=limit, order=order
        )
        return res
        
class ProductTemplate(models.Model):
    _inherit = 'product.template'

    def _compute_display_name(self):
        super()._compute_display_name()
        for template in self:
            if template.display_name:
                template.display_name = re.sub(r'^\[.*?\]\s*', '', template.display_name)

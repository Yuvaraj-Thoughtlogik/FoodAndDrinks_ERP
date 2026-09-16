from odoo import models, fields, api
from odoo.tools import _
from datetime import datetime, timedelta
from odoo.exceptions import ValidationError, UserError


class RoundManagementBatch(models.Model):
    _name = 'round.management.batch'
    _description = 'Round Execution Batch'
    _rec_name = 'code'
    _rec_names_search = ['reference', 'code']

    @api.model
    def _default_batch_code(self):
        """Generate 6-digit sequence code immediately on clicking 'Create'."""
        return self.env['ir.sequence'].next_by_code('round.management.batch') or 'New'

    code = fields.Char(string='Batch Code', required=True, copy=False, default=_default_batch_code)
    round_id = fields.Many2one('round.management.round', string='Round', required=True,
                               domain="[('state', '=', 'active')]")
    round_code = fields.Char(related='round_id.code', string='Round Code', readonly=True, store=True)
    reference = fields.Char(string='Reference', required=True)
    # depot_id = fields.Many2one('stock.warehouse', string='Depot', required=True)
    delivery_date = fields.Date(string='Delivery Date', default=fields.Date.context_today, required=True)
    delivery_times = fields.Char(string='Delivery Times', compute='_compute_delivery_times', store=True)
    week_number = fields.Char(string='ISO Week No.', compute='_compute_week_number', store=True)
    state = fields.Selection([
        ('pln', 'Planned'),
        ('act', 'Active'),
        ('prt', 'Printed'),
        ('com', 'Completed'),
        ('cancel', 'Cancelled'),
    ], string='Status', default='pln', required=True, tracking=True)

    # pay_grade = fields.Char(string='Pay Grade', related='round_id.pay_grade', readonly=True)

    helper_needed = fields.Boolean(string='Helper Needed')
    knockup_round = fields.Boolean(string='Knockup Round')
    driver_id = fields.Many2one(
        'res.partner',
        string='Assigned Driver',
        domain="""[
            ('is_company', '=', False),
            '|',
            ('employee_ids.job_id.name', 'ilike', 'Driver'),
            ('user_ids.employee_id.job_id.name', 'ilike', 'Driver')
        ]""",
        help="Only partners linked to an Employee with 'Driver' job position can be selected."
    )

    helper_id = fields.Many2one(
        'res.partner',
        string='Helper',
        domain="""[
            ('is_company', '=', False),
            '|',
            ('employee_ids.job_id.name', 'ilike', 'Helper'),
            ('user_ids.employee_id.job_id.name', 'ilike', 'Helper')
        ]""",
        help="Only partners linked to an Employee with 'Helper' job position can be selected."
    )
    notes = fields.Text(string='Notes')

    # Duplication Info & Warnings
    duplication_comments = fields.Char(string='Duplication Comments', readonly=True)
    warning_message = fields.Char(string='Warning', compute='_compute_warnings')

    order_ids = fields.One2many(
        'sale.order',
        'batch_id',
        string='Linked Orders',
        domain="[('round_id.state', '=', 'active')]"
    )

    drops_count = fields.Integer(string='Drops', compute='_compute_order_metrics', store=True)
    late_orders_count = fields.Integer(string='Late Orders', compute='_compute_order_metrics', store=True)
    total_drops = fields.Integer(string='Total Drops', compute='_compute_order_metrics', store=True)

    picking_type_id = fields.Many2one('stock.picking.type', string='Operation Type')
    picking_ids = fields.One2many(
        'stock.picking',
        'batch_id',
        string='Transfers / Deliveries'
    )
    is_wave = fields.Boolean(string="Is Wave", default=False)

    # order_ids = fields.One2many('sale.order', 'batch_id', string="Linked Orders")

    # card_reader_count = fields.Selection([
    # ('Y', 'Yes'),
    # ('N', 'No'),
    # ], string='Card Reader', compute='_compute_order_metrics', store=True)

    pickups_count = fields.Integer(string='Pickups', compute='_compute_order_metrics', store=True)
    extras = fields.Integer(string='Extras', default=0)
    is_b2b_batch = fields.Boolean(string='B2B', compute='_compute_order_metrics', store=True)

    vehicle_id = fields.Many2one(
        'fleet.vehicle',
        string='Assigned Vehicle',
        domain="[('state_id.name', '!=', 'In Maintenance')]",
        help="Vehicle allocated specifically for this batch run."
    )
    is_spare_vehicle = fields.Boolean(string='Spare')
    is_off_road = fields.Boolean(string='Off Road')
    driver_on_leave = fields.Boolean(string='Driver Hol/Sick')

    start_odometer = fields.Float(string='Start Odometer (km)')
    end_odometer = fields.Float(string='End Odometer (km)')
    distance_run = fields.Float(string='Distance (km)', compute='_compute_distance', store=True)

    max_alt_drops = fields.Integer(
        string='Max. Alt. Drops',
        compute='_compute_max_alt_drops',
        readonly=False,
        store=True
    )
    current_regular_drops = fields.Integer(
        string="Current Regular Drops", compute="_compute_batch_drops", store=True
    )
    current_alt_drops = fields.Integer(
        string="Current Alt Drops", compute="_compute_batch_drops", store=True
    )
    balance_alt_drops = fields.Integer(
        string="Balance Alt Drops", compute="_compute_batch_drops", store=True
    )
    is_alt_limit_reached = fields.Boolean(
        string="Max Alt Drops Reached", compute="_compute_batch_drops", store=True
    )

    total_revenue = fields.Monetary(
        string='Total Revenue',
        compute='_compute_order_metrics',
        currency_field='company_currency_id',
        store=True
    )
    company_currency_id = fields.Many2one(
        'res.currency',
        string='Currency',
        related='company_id.currency_id',
        readonly=True,
        store=True
    )

    company_id = fields.Many2one(
        'res.company',
        string='Company',
        default=lambda self: self.env.company,
        index=True
    )

    user_id = fields.Many2one('res.users', string='Responsible')

    delivery_channel = fields.Selection(
        selection=[
            ('regal_van', 'Regal Van Delivery'),
            ('courier', 'Courier Delivery'),
        ],
        string='Delivery Channels',
        required=True,
    )

    depot_id = fields.Many2one(
        'stock.warehouse',
        string='Depot',
        required=True,
        compute='_compute_depot_id',
        store=True,
        readonly=False,
        precompute=True,
    )

    @api.depends('round_id')
    def _compute_depot_id(self):
        for record in self:
            if record.round_id.depot_id:
                record.depot_id = record.round_id.depot_id

    @api.onchange('round_id')
    def _onchange_round_id_set_reference(self):
        if self.round_id:
            self.reference = self.round_id.name

    @api.onchange('round_id')
    def _onchange_round_id(self):
        if self.round_id:
            self.delivery_channel = self.round_id.delivery_channel
        else:
            self.delivery_channel = False

    def _sanity_check(self):
        return True

    @api.depends('round_id', 'round_id.max_alt_drops')
    def _compute_max_alt_drops(self):
        for rec in self:
            rec.max_alt_drops = rec.round_id.max_alt_drops

    @api.depends('max_alt_drops', 'order_ids', 'order_ids.state', 'order_ids.is_alternative_round')
    def _compute_batch_drops(self):
        for batch in self:
            valid_orders = batch.order_ids.filtered(lambda o: o.state == 'sale')
            alt_orders = valid_orders.filtered(lambda o: getattr(o, 'is_alternative_round', False))
            reg_orders = valid_orders - alt_orders

            batch.current_regular_drops = len(reg_orders)
            batch.current_alt_drops = len(alt_orders)
            batch.balance_alt_drops = batch.max_alt_drops - batch.current_alt_drops

            # Flag for Kanban/Tree visual color styling
            batch.is_alt_limit_reached = (batch.max_alt_drops > 0) and (batch.current_alt_drops >= batch.max_alt_drops)

    round_full_name = fields.Char(compute='_compute_round_full_name', store=True)

    @api.depends('round_id.code', 'round_id.name')
    def _compute_round_full_name(self):
        for rec in self:
            if rec.round_id:
                rec.round_full_name = f'{rec.round_id.code}-{rec.round_id.name}'
            else:
                rec.round_full_name = False

    _code_unique = models.Constraint(
        "UNIQUE(code)",
        "The Round Code must be unique!"
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
        'delivery_date', 'round_id',
        'round_id.mon_active', 'round_id.mon_from', 'round_id.mon_to',
        'round_id.tue_active', 'round_id.tue_from', 'round_id.tue_to',
        'round_id.wed_active', 'round_id.wed_from', 'round_id.wed_to',
        'round_id.thu_active', 'round_id.thu_from', 'round_id.thu_to',
        'round_id.fri_active', 'round_id.fri_from', 'round_id.fri_to',
        'round_id.sat_active', 'round_id.sat_from', 'round_id.sat_to',
        'round_id.sun_active', 'round_id.sun_from', 'round_id.sun_to',
    )
    def _compute_delivery_times(self):
        for rec in self:
            if rec.delivery_date and rec.round_id:
                weekday = rec.delivery_date.weekday()

                active_field, from_field, to_field = rec._DAY_FIELDS[weekday]
                round_rec = rec.round_id

                if round_rec[active_field]:
                    from_val = round_rec[from_field]
                    to_val = round_rec[to_field]

                    from_str = rec._format_time(from_val)
                    to_str = rec._format_time(to_val)

                    rec.delivery_times = "%s to %s" % (from_str, to_str)
                else:
                    rec.delivery_times = "N/A"
            else:
                rec.delivery_times = False

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

    @api.depends('code', 'reference', 'delivery_date')
    def _compute_display_name(self):
        """Computes display name using Batch Code, Reference, and Delivery Date."""

        for batch in self:
            # Format delivery date string if present
            date_str = batch.delivery_date.strftime('%d-%m-%Y') if batch.delivery_date else ''
            # Collect active name components
            parts = []
            if batch.code:
                parts.append(batch.code)
            if batch.reference:
                parts.append(batch.reference)
            if date_str:
                parts.append(date_str)
            if batch.delivery_times:
                parts.append(batch.delivery_times)
            if parts:
                batch.display_name = " - ".join(parts)
            else:
                batch.display_name = _('New Batch')

    @api.onchange('vehicle_id')
    def _onchange_vehicle_id_fetch_driver(self):
        """Directly assigns Fleet vehicle driver (res.partner) without conversion errors."""
        if self.vehicle_id and self.vehicle_id.driver_id:
            self.driver_id = self.vehicle_id.driver_id
        else:
            self.driver_id = False

    @api.onchange('round_id')
    def _onchange_round_id_fetch_depot(self):
        for record in self:
            record.depot_id = record.round_id.depot_id.id

    @api.constrains('driver_id', 'helper_id')
    def _check_partner_employee_designation(self):
        for record in self:
            # Check Driver Job Position
            if record.driver_id:
                employee = self.env['hr.employee'].search([
                    '|',
                    ('work_contact_id', '=', record.driver_id.id),
                    ('user_id.partner_id', '=', record.driver_id.id)
                ], limit=1)

                if not employee or 'driver' not in (employee.job_id.name or '').lower():
                    job_title = employee.job_id.name if employee and employee.job_id else 'No Job Assigned'
                    raise ValidationError(_(
                        "Selected Driver contact '%s' is not an employee with 'Driver' job position (Current: %s)."
                    ) % (record.driver_id.name, job_title))

            # Check Helper Job Position
            if record.helper_id:
                employee = self.env['hr.employee'].search([
                    '|',
                    ('work_contact_id', '=', record.helper_id.id),
                    ('user_id.partner_id', '=', record.helper_id.id)
                ], limit=1)

                if not employee or 'helper' not in (employee.job_id.name or '').lower():
                    job_title = employee.job_id.name if employee and employee.job_id else 'No Job Assigned'
                    raise ValidationError(_(
                        "Selected Helper contact '%s' is not an employee with 'Helper' job position (Current: %s)."
                    ) % (record.helper_id.name, job_title))

    @api.model_create_multi
    def create(self, vals_list):
        batches = super().create(vals_list)
        batches._sync_fleet_vehicle_assignment()
        return batches

    def write(self, vals):
        res = super().write(vals)
        if 'vehicle_id' in vals or 'driver_id' in vals:
            self._sync_fleet_vehicle_assignment()
        return res

    def _sync_fleet_vehicle_assignment(self):
        """Syncs the active driver and updates vehicle state in Fleet"""
        for batch in self:
            if batch.vehicle_id and batch.driver_id:
                # Assign driver to vehicle -> Auto-generates driver assignment history in Fleet
                batch.vehicle_id.write({
                    'driver_id': batch.driver_id.id,
                })

    def action_complete_batch(self):
        """Executed when batch moves to 'com' (Completed) state"""
        for batch in self:
            if batch.vehicle_id and batch.end_odometer > 0:
                # Automatically log end reading into standard Odoo Fleet Odometer Logs
                self.env['fleet.vehicle.odometer'].create({
                    'vehicle_id': batch.vehicle_id.id,
                    'value': batch.end_odometer,
                    'date': batch.delivery_date or fields.Date.context_today(self),
                })
            batch.state = 'com'

    @api.depends('start_odometer', 'end_odometer')
    def _compute_distance(self):
        for batch in self:
            if batch.end_odometer >= batch.start_odometer:
                batch.distance_run = batch.end_odometer - batch.start_odometer
            else:
                batch.distance_run = 0.0

    @api.onchange('vehicle_id')
    def _onchange_vehicle_id_fetch_driver(self):
        """Auto-populates driver_id when a vehicle is selected."""
        if self.vehicle_id and self.vehicle_id.driver_id:
            self.driver_id = self.vehicle_id.driver_id

    def action_start_batch(self):
        """Triggers wizard if active batch exists, otherwise activates the batch."""
        self.ensure_one()
        if not self.env.context.get('skip_active_batch_check'):
            active_batches = self._check_existing_active_batches(self.round_id.id, self.delivery_date)
            if active_batches:
                return self._open_active_batch_warning_wizard(active_batches, trigger_start=True)

        self.write({'state': 'act'})
        return True

    def action_print_manifest(self):
        for batch in self:
            batch.state = 'prt'
        # Trigger report printing action if configured
        # return self.env.ref('round_management.action_report_round_batch').report_action(self)
        return True

    def action_complete_batch(self):
        self.write({'state': 'com'})

    def action_reset_to_planned(self):
        self.write({'state': 'pln'})

    # @api.model_create_multi
    # def create(self, vals_list):
    # for vals in vals_list:

    # if vals.get('code', _('New')) in (_('New'), 'New', False, None):
    # sequence_code = self.env['ir.sequence'].next_by_code('round.management.batch')
    # vals['code'] = sequence_code or str(int(datetime.now().timestamp()))
    # return super().create(vals_list)

    @api.depends('delivery_date')
    def _compute_week_number(self):
        for record in self:
            if record.delivery_date:
                iso_year, iso_week, _ = record.delivery_date.isocalendar()
                record.week_number = f"{iso_year}{str(iso_week).zfill(2)}"
            else:
                record.week_number = False

    # @api.model_create_multi
    # def create(self, vals_list):
    # records = super().create(vals_list)
    # records._update_linked_orders_delivery_info()
    # return records

    def write(self, vals):
        res = super().write(vals)
        if 'delivery_date' in vals or 'week_number' in vals:
            self._update_linked_orders_delivery_info()
        return res

    def _update_linked_orders_delivery_info(self):
        """Bulk propagates delivery date and week number to all linked sales orders."""
        for batch in self:
            if batch.order_ids:
                vals_to_write = {}
                if batch.delivery_date:
                    vals_to_write['commitment_date'] = fields.Datetime.to_datetime(batch.delivery_date)
                if batch.week_number:
                    vals_to_write['week_number'] = batch.week_number

                if vals_to_write:
                    batch.order_ids.write(vals_to_write)

    @api.depends('delivery_date', 'round_id')
    def _compute_warnings(self):
        for record in self:
            if record.delivery_date and record.round_id:
                six_weeks_ago = record.delivery_date - timedelta(weeks=6)
                recent_batch = self.search([
                    ('round_id', '=', record.round_id.id),
                    ('delivery_date', '>=', six_weeks_ago),
                    ('delivery_date', '<', record.delivery_date),
                    ('id', '!=', record._origin.id)
                ], limit=1)
                record.warning_message = _("Round scheduled within 6 weeks") if recent_batch else ""
            else:
                record.warning_message = ""

    @api.depends(
        'order_ids',
        'order_ids.state',
        'order_ids.amount_total',
        'order_ids.is_late_order',
        'order_ids.is_b2b',
        # 'order_ids.is_staff_order'
    )
    def _compute_order_metrics(self):
        for record in self:
            active_orders = record.order_ids.filtered(
                lambda o: o.state not in ('draft', 'cancel')
            ) if record.order_ids else self.env['sale.order']

            if active_orders:
                record.drops_count = len(active_orders)
                record.late_orders_count = len(active_orders.filtered(lambda o: getattr(o, 'is_late_order', False)))
                record.pickups_count = 0
                record.total_drops = len(active_orders)
                record.total_revenue = sum(active_orders.mapped('amount_total'))
                record.is_b2b_batch = any(getattr(o, 'is_b2b', False) for o in active_orders)
            else:
                record.drops_count = 0
                record.late_orders_count = 0
                record.pickups_count = 0
                record.total_drops = 0
                record.total_revenue = 0.0
                record.is_b2b_batch = False

    @api.model
    def _name_search(self, name, domain=None, operator='ilike', limit=100, order=None):
        domain = domain or []
        order = order or 'delivery_date asc, id asc'
        return super()._name_search(name, domain=domain, operator=operator, limit=limit, order=order)

    def _check_existing_active_batches(self, round_id, delivery_date):
        """Finds active batches for the same round within 4 weeks before and after the delivery date."""
        if not round_id or not delivery_date:
            return self.env['round.management.batch']

        start_date = delivery_date - timedelta(days=28)
        end_date = delivery_date + timedelta(days=28)

        domain = [
            ('round_id', '=', round_id),
            ('state', '=', 'act'),
            ('delivery_channel', '!=', 'courier'),
            ('delivery_date', '>=', start_date),
            ('delivery_date', '<=', end_date),
        ]

        batch_id = self._origin.id or self.id
        if batch_id:
            domain.append(('id', '!=', batch_id))

        return self.search(domain)

    def _get_active_batch_warning_message(self, active_batches):
        """Builds a formatted warning message displaying Reference - Delivery Date without time."""
        sections = []

        def format_batch_line(batch):
            ref = batch.reference or batch.code or ''
            date_str = batch.delivery_date.strftime('%d-%m-%Y') if batch.delivery_date else ''
            return f"   • {ref} - {date_str}" if date_str else f"   • {ref}"

        batches_before = active_batches.filtered(
            lambda b: b.delivery_date and self.delivery_date and b.delivery_date < self.delivery_date
        )
        batches_same = active_batches.filtered(
            lambda b: b.delivery_date and self.delivery_date and b.delivery_date == self.delivery_date
        )
        batches_after = active_batches.filtered(
            lambda b: b.delivery_date and self.delivery_date and b.delivery_date > self.delivery_date
        )

        if batches_before:
            before_list = "\n".join(format_batch_line(b) for b in batches_before)
            sections.append(f"Active Batches Before Delivery Date (Within 4 Weeks):\n{before_list}")

        if batches_same:
            same_list = "\n".join(format_batch_line(b) for b in batches_same)
            sections.append(f"Active Batches on Same Date:\n{same_list}")

        if batches_after:
            after_list = "\n".join(format_batch_line(b) for b in batches_after)
            sections.append(f"Active Batches After Delivery Date (Within 4 Weeks):\n{after_list}")

        other_batches = active_batches - batches_before - batches_same - batches_after
        if other_batches:
            other_list = "\n".join(format_batch_line(b) for b in other_batches)
            sections.append(f"Other Active Batches:\n{other_list}")

        sections_str = "\n\n".join(sections)

        return (
            "Existing active batch(es) found for this round within 4 weeks:\n\n"
            f"{sections_str}\n\n"
            "Do you wish to continue?"
        )

    def _open_active_batch_warning_wizard(self, active_batches, trigger_start=False):
        """Opens the custom transient wizard with OK and Cancel buttons."""
        msg = self._get_active_batch_warning_message(active_batches)

        wizard = self.env['round.batch.warning.wizard'].create({
            'message': msg,
            'batch_id': self.id,
        })

        context = dict(self.env.context)
        if trigger_start:
            context['trigger_start_batch'] = True

        return {
            'name': _('Existing Active Batch Warning'),
            'type': 'ir.actions.act_window',
            'res_model': 'round.batch.warning.wizard',
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'new',
            'context': context,
        }

    @api.onchange('round_id', 'delivery_date')
    def _onchange_check_existing_active_batches(self):
        """Triggers a warning popup immediately when entering or changing Delivery Date/Round."""
        if not self.round_id or not self.delivery_date:
            return

        active_batches = self._check_existing_active_batches(self.round_id.id, self.delivery_date)
        if active_batches:
            msg = self._get_active_batch_warning_message(active_batches)

            return {
                'warning': {
                    'title': _("Existing Active Batch Warning"),
                    'message': msg,
                }
            }

    def unlink(self):
        """Prevent deletion of round batches that have linked sales orders."""

        for batch in self:
            if batch.order_ids:
                order_names = batch.order_ids.mapped('name')
                displayed_orders = order_names[:5]

                orders_list_str = "\n".join(
                    f"   • {name}" for name in displayed_orders
                )

                remaining_count = len(order_names) - len(displayed_orders)

                if remaining_count > 0:
                    orders_list_str += _(
                        "\n   • ... and %(count)d more order(s)"
                    ) % {
                                           'count': remaining_count,
                                       }

                message = _(
                    "[ WARNING ] BATCH CANNOT BE DELETED\n"
                    "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"

                    "This batch is currently linked to one or more "
                    "Sales Orders.\n"
                    "Please remove the linked orders before deleting "
                    "the batch.\n\n"

                    "[ BATCH DETAILS ]\n"
                    "--------------------------------------------------\n"
                    "• Batch Code: %(batch_code)s\n"
                    "• Batch Description: %(batch_name)s\n"
                    "• Linked Sales Orders: %(count)d\n\n"

                    "LINKED SALES ORDERS\n"
                    "--------------------------------------------------\n"
                    "%(orders)s\n\n"

                    "[ REQUIRED ACTION ]\n"
                    "--------------------------------------------------\n"
                    "1. Open the linked Sales Order(s).\n"
                    "2. Clear or change the Round Batch reference.\n"
                    "3. Return to this batch and try deleting it again.\n\n"
                    "[ SYSTEM INFO ]\n"
                    "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    "Deletion is blocked to prevent data inconsistency."
                ) % {
                              'batch_code': batch.code or '-',
                              'batch_name': batch.display_name or '-',
                              'count': len(batch.order_ids),
                              'orders': orders_list_str,
                          }

                raise UserError(message)

        return super().unlink()





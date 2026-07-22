from odoo import models, fields, api, _
from datetime import datetime, timedelta

class RoundManagementBatch(models.Model):
    _name = 'round.management.batch'
    _description = 'Round Execution Batch'
    _rec_name = 'code'

    # Core Fields
    code = fields.Char(string='Batch Code', required=True, copy=False, default=lambda self: _('New'))
    round_id = fields.Many2one('round.management.round', string='Round', required=True,domain="[('state', '=', 'active')]")
    round_code = fields.Char(related='round_id.code', string='Round Code', readonly=True)
    reference = fields.Char(string='Reference')
    depot_id = fields.Many2one('stock.warehouse', string='Depot')
    delivery_date = fields.Date(string='Delivery Date', default=fields.Date.context_today)
    week_number = fields.Char(string='ISO Week No.', compute='_compute_week_number', store=True)
    state = fields.Selection([
        ('pln', 'Planned'),
        ('act', 'Active'),
        ('prt', 'Printed'),
        ('com', 'Completed'),
        ('cancel', 'Cancelled'),
    ], string='Status', default='pln', required=True, tracking=True)
    
    #pay_grade = fields.Char(string='Pay Grade', related='round_id.pay_grade', readonly=True)
    max_alt_drops = fields.Integer(string='Max. Alt. Drops', related='round_id.max_alt_drops', readonly=True)
    
    helper_needed = fields.Boolean(string='Helper Needed')
    knockup_round = fields.Boolean(string='Knockup Round')
    driver_id = fields.Many2one(
        'res.partner', 
        string='Assigned Driver',
        domain="[('is_company', '=', False)]",
        help="Driver allocated to execute this batch."
    )
    helper_id = fields.Many2one('res.partner', string='Helper', domain="[('partner_share', '=', False)]")
    notes = fields.Html(string='Notes')

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
    
   
    card_reader_count = fields.Selection([
        ('Y', 'Yes'),
        ('N', 'No'),
    ], string='Card Reader', compute='_compute_order_metrics', store=True)
    
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
        for batch in self:
            if batch.state != 'pln':
                raise UserError(_("Only Planned batches can be activated."))
            batch.state = 'act'

    def action_print_manifest(self):
        for batch in self:
            batch.state = 'prt'
        # Trigger report printing action if configured
        #return self.env.ref('round_management.action_report_round_batch').report_action(self)
        return True

    def action_complete_batch(self):
        self.write({'state': 'com'})

    def action_reset_to_planned(self):
        self.write({'state': 'pln'})

    
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            
            if vals.get('code', _('New')) in (_('New'), 'New', False, None):
                sequence_code = self.env['ir.sequence'].next_by_code('round.management.batch')
                vals['code'] = sequence_code or str(int(datetime.now().timestamp()))
        return super().create(vals_list)

    @api.depends('delivery_date')
    def _compute_week_number(self):
        for record in self:
            if record.delivery_date:
                iso_year, iso_week, _ = record.delivery_date.isocalendar()
                record.week_number = f"{iso_year}{str(iso_week).zfill(2)}"
            else:
                record.week_number = False
                
    #@api.model_create_multi
    #def create(self, vals_list):
        #records = super().create(vals_list)
        #records._update_linked_orders_delivery_info()
        #return records

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
        'order_ids.is_late_order', 
        'order_ids.has_card_reader', 
        'order_ids.is_pickup', 
        'order_ids.is_b2b'
    )
    def _compute_order_metrics(self):
        for record in self:
            active_orders = record.order_ids.filtered(
                lambda o: o.state not in ('draft', 'cancel')
            ) if record.order_ids else self.env['sale.order']
            
            if active_orders:
                record.drops_count = len(active_orders.filtered(lambda o: not getattr(o, 'is_pickup', False)))
                record.late_orders_count = len(active_orders.filtered(lambda o: getattr(o, 'is_late_order', False)))
                record.pickups_count = len(active_orders.filtered(lambda o: getattr(o, 'is_pickup', False)))
                record.total_drops = len(active_orders)
                
                
                has_card_req = any(getattr(o, 'has_card_reader', False) for o in active_orders)
                record.card_reader_count = 'Y' if has_card_req else 'N'
                
                record.is_b2b_batch = any(getattr(o, 'is_b2b', False) for o in active_orders)
            else:
                record.drops_count = 0
                record.late_orders_count = 0
                record.pickups_count = 0
                record.total_drops = 0
                record.card_reader_count = False  
                record.is_b2b_batch = False

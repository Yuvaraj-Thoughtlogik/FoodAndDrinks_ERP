from odoo import models, fields, api, _

class FleetVehicle(models.Model):
    _inherit = 'fleet.vehicle'

    round_batch_ids = fields.One2many('round.management.batch', 'vehicle_id', string='Driver Rounds')
    round_batch_count = fields.Integer(compute='_compute_round_batch_count', string='Rounds Count')

    def _compute_round_batch_count(self):
        for vehicle in self:
            vehicle.round_batch_count = len(vehicle.round_batch_ids)
            

    def action_view_driver_rounds(self):
        self.ensure_one()
        return {
            'name': _('Driver Rounds History'), 
            'type': 'ir.actions.act_window',
            'res_model': 'round.management.batch',
            'view_mode': 'list,form',
            'domain': [('vehicle_id', '=', self.id)],
            'context': {'default_vehicle_id': self.id},
        }
        
        
    
    track_history_ids = fields.One2many(
        'round.management.batch', 
        'vehicle_id', 
        string='Track History'
    )
    track_history_count = fields.Integer(
        compute='_compute_track_history_count', 
        string='Track History Count'
    )

    def _compute_track_history_count(self):
        for vehicle in self:
            # You can add custom domain filtering here if track history differs (e.g. state == 'completed')
            vehicle.track_history_count = len(vehicle.track_history_ids)

    def action_view_vehicle_track_history(self):
        self.ensure_one()
        return {
            'name': _('Vehicle Track History'), 
            'type': 'ir.actions.act_window',
            'res_model': 'round.management.batch',
            'view_mode': 'list,form',
            'domain': [('vehicle_id', '=', self.id)],
            'context': {
                'default_vehicle_id': self.id,
                'search_default_vehicle_id': self.id,
            },
        }
        
        


class CustomVehicleType(models.Model):
    _name = 'custom.vehicle.type'
    _description = 'Custom Vehicle Types'

    name = fields.Char(string='Type Name', required=True)


class FleetVehicleModel(models.Model):
    _inherit = 'fleet.vehicle.model'

    # Many2one field referencing the custom options model
    custom_type_id = fields.Many2one(
        'custom.vehicle.type',
        string='Vehicle Type',
        help="Select or create a custom vehicle type."
    )
    
    drive_type = fields.Selection(
        selection=[
            ('2wd', 'Two-Wheel Drive (2WD)'),
            ('4wd', 'Four-Wheel Drive (4WD)'),
            ('awd', 'All-Wheel Drive (AWD)'),
        ],
        string='Drive Type',
        default='2wd',
        help="Select the drivetrain configuration for this vehicle model."
    )
    
    default_fuel_type = fields.Selection(
        selection_add=[
            ('hybrid_elec_petrol', 'Petrol'),
        ],
        ondelete={
            'hybrid_elec_petrol': 'set null',
        }
    )
    
    @api.model
    def _get_merged_vehicle_types(self):
        """Fetches standard selections AND custom dynamic choices from database."""
        # 1. Base standard choices
        types = [
            ('car', 'Car'),
            ('bike', 'Bike'),
            ('refrigerated_panel_van', 'Refrigerated Panel Van'),
            ('panel_van', 'Panel Van'),
        ]
        
        # 2. Append records dynamically created in custom.vehicle.type table
        custom_records = self.env['custom.vehicle.type'].search([])
        for record in custom_records:
            types.append((record.name.lower().replace(' ', '_'), record.name))
            
        return types

    # Override native vehicle_type selection dynamically
    vehicle_type = fields.Selection(
        selection=_get_merged_vehicle_types,
        string='Vehicle Type',
        default='car'
    )
   

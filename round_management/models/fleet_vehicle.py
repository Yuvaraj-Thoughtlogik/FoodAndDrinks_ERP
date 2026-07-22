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

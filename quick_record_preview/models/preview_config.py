# -*- coding: utf-8 -*-

from odoo import models, fields, api


class PreviewConfig(models.Model):
    _name = 'preview.config'
    _description = 'Quick Record Preview Configuration'
    _order = 'model_id, sequence'

    name = fields.Char(string='Name', required=True)
    model_id = fields.Many2one('ir.model', string='Model', required=True, ondelete='cascade')
    model_name = fields.Char(related='model_id.model', string='Model Name', store=True, readonly=True)
    sequence = fields.Integer(string='Sequence', default=10)
    field_ids = fields.Many2many(
        'ir.model.fields',
        'preview_config_field_rel',
        'config_id',
        'field_id',
        string='Fields to Show',
        domain="[('model_id', '=', model_id), ('ttype', 'not in', ['one2many', 'many2many', 'binary'])]"
    )
    active = fields.Boolean(string='Active', default=True)
    show_image = fields.Boolean(string='Show Image', default=True, help='Show image field if available')
    show_display_name = fields.Boolean(string='Show Display Name', default=True, help='Show display_name field')

    @api.model
    def get_config_for_model(self, model_name):
        """Get configuration for a specific model"""
        config = self.search([
            ('model_name', '=', model_name),
            ('active', '=', True)
        ], limit=1, order='sequence')
        
        if config:
            return {
                'field_names': config.field_ids.mapped('name'),
                'show_image': config.show_image,
                'show_display_name': config.show_display_name,
            }
        return None


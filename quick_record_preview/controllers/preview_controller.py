# -*- coding: utf-8 -*-

from odoo import http
from odoo.http import request
import json


class PreviewController(http.Controller):

    @http.route('/preview_config/get_config', type='json', auth='user')
    def get_config(self, model_name):
        """Get preview configuration for a model"""
        config_model = request.env['preview.config']
        config = config_model.get_config_for_model(model_name)
        
        if config:
            return config
        
        # Return default config
        return {
            'field_names': [],
            'show_image': True,
            'show_display_name': True,
        }


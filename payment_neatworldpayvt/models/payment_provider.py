# Original Author: Daniel Stoynev
# Copyright (c) 2025 SNS Software Ltd. All rights reserved.
# This module extends Odoo's payment framework.
# Odoo is a trademark of Odoo S.A.

import json
import logging
import re
import requests

from odoo.addons.payment_neatworldpayvt import const
from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

from odoo.addons.payment import utils as payment_utils

_logger = logging.getLogger(__name__)


class PaymentProvider(models.Model):
    _inherit = 'payment.provider'
    code = fields.Selection(
        selection_add=[('neatworldpayvt', "WorldPay Virtual Terminal")], ondelete={'neatworldpayvt': 'set default'})
    neatworldpayvt_username = fields.Char(
        string="Username", help="Worldpay username", required_if_provider='neatworldpayvt',
        groups='base.group_system')
    neatworldpayvt_password = fields.Char(
        string="Password", help="Worldpay password",
        required_if_provider='neatworldpayvt')
    neatworldpayvt_activation_code = fields.Char(
        string="Activation Code", help="Contact us to receive a free activation code.")
    neatworldpayvt_cached_code = fields.Char(
        string="Cached Code", help="Cached Code")
    neatworldpayvt_reset_code = fields.Boolean(string="Update Module Cache", help="If set to true it will update the module cache", default=False)
    neatworldpayvt_checkout_id = fields.Char(
        string="Checkout ID", help="Worldpay Checkout ID", required_if_provider='neatworldpayvt',
        groups='base.group_system')
    neatworldpayvt_entity = fields.Char(
        string="Entity", help="Worldpay merchant entity", required_if_provider='neatworldpayvt',
        groups='base.group_system')

    @api.model
    def _get_all_users_neatworldpayvt(self):
        """Fetch all users and return them as selection options."""
        users = self.env['res.users'].search([])  # Get all users
        return [(str(user.id), user.name) for user in users]  # Store ID as string, show name

    neatworldpayvt_fallback_user_id = fields.Selection(
        selection=_get_all_users_neatworldpayvt,
        string='Fallback Failure VT User',
        help='Select a user who will receive an activity if a transaction fails for a sale order that does not have a salesperson.'
    )


    def neatworldpayvt_get_code(self, activation_code):
        """ Get code. """
        try:
            headers = {
                "Referer": self.company_id.website,
                "Authorization": activation_code
            }
            response = requests.get("https://api.sns-software.com/api/AcquirerLicense/code?version=vt-v4", headers=headers, timeout=10)
            
            if response.status_code == 200:
                return response.text
                
            else:
                _logger.error(f"Failed to fetch activation code: {response.status_code} - {response.text}")
        except requests.RequestException as e:
            _logger.error(f"Request error: {e}")
        
        return None

    @api.model
    def create(self, vals_list):
        # Handle both single dict and list of dicts for Odoo 19 compatibility
        if isinstance(vals_list, dict):
            vals_list = [vals_list]
        
        for vals in vals_list:
            # Check if 'code' is 'neatworldpayvt' and activation code is being provided or changed
            _logger.info(f"neatworldpayvt_activation_code {vals.get('neatworldpayvt_activation_code')}")
            if vals.get('neatworldpayvt_activation_code'):
                _logger.info(f"old neatworldpayvt_activation_code {self.neatworldpayvt_activation_code}")
                if vals.get('neatworldpayvt_activation_code') != self.neatworldpayvt_activation_code or vals.get('neatworldpayvt_reset_code'):
                    _logger.info(f"Before code")
                    vals['neatworldpayvt_reset_code'] = False
                    code = self.neatworldpayvt_get_code(vals['neatworldpayvt_activation_code'])
                    _logger.info(f"Code: {code != None}")
                    if code:
                        vals['neatworldpayvt_cached_code'] = code
                    else:
                        _logger.info(f"Raised error for code")
                        raise ValidationError(_("The activation code is invalid. Please check and try again."))
            elif vals.get('neatworldpayvt_reset_code'):
                _logger.info(f"Before code")
                vals['neatworldpayvt_reset_code'] = False
                code = self.neatworldpayvt_get_code(self.neatworldpayvt_activation_code)
                _logger.info(f"Code: {code}")
                if code:
                    vals['neatworldpayvt_cached_code'] = code
                else:
                    _logger.info(f"Raised error for code")
                    raise ValidationError(_("The activation code is invalid. Please check and try again."))
        
        return super(PaymentProvider, self).create(vals_list)

    def write(self, vals):
        # Check if 'code' is 'neatworldpayvt' and activation code is being updated
        _logger.info(f"neatworldpayvt_activation_code {vals.get('neatworldpayvt_activation_code')}")
        if vals.get('neatworldpayvt_activation_code'):
            _logger.info(f"old neatworldpayvt_activation_code {self.neatworldpayvt_activation_code}")
            if vals.get('neatworldpayvt_activation_code') != self.neatworldpayvt_activation_code or vals.get('neatworldpayvt_reset_code'):
                _logger.info(f"Before code")
                vals['neatworldpayvt_reset_code'] = False
                code = self.neatworldpayvt_get_code(vals['neatworldpayvt_activation_code'])
                _logger.info(f"Code: {code}")
                if code:
                    vals['neatworldpayvt_cached_code'] = code
                else:
                    _logger.info(f"Raised error for code")
                    raise ValidationError(_("The activation code is invalid. Please check and try again."))
        elif vals.get('neatworldpayvt_reset_code'):
            _logger.info(f"Before code")
            vals['neatworldpayvt_reset_code'] = False
            code = self.neatworldpayvt_get_code(self.neatworldpayvt_activation_code)
            _logger.info(f"Code: {code}")
            if code:
                vals['neatworldpayvt_cached_code'] = code
            else:
                _logger.info(f"Raised error for code")
                raise ValidationError(_("The activation code is invalid. Please check and try again."))
        return super(PaymentProvider, self).write(vals)

    def _compute_feature_support_fields(self):
        """ Override of `payment` to enable additional features. """
        super()._compute_feature_support_fields()
        self.filtered(lambda p: p.code == 'neatworldpayvt').update({
            'support_manual_capture': 'partial',
            'support_refund': 'partial',
            'support_tokenization': True,
        })

    def _get_default_payment_method_codes(self):
        """ Override of `payment` to return the default payment method codes. """
        default_codes = super()._get_default_payment_method_codes()
        if self.code != 'neatworldpayvt':
            return default_codes
        return const.DEFAULT_PAYMENT_METHODS_CODES




import logging

from odoo.addons.payment_neatworldpayvt import const
from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class PaymentProvider(models.Model):
    _inherit = 'payment.provider'

    code = fields.Selection(
        selection_add=[('neatworldpayvt', "WorldPay Virtual Terminal")],
        ondelete={'neatworldpayvt': 'set default'}
    )
    neatworldpayvt_username = fields.Char(
        string="Username", 
        help="Worldpay username", 
        required_if_provider='neatworldpayvt',
        groups='base.group_system'
    )
    neatworldpayvt_password = fields.Char(
        string="Password", 
        help="Worldpay password",
        required_if_provider='neatworldpayvt'
    )
    neatworldpayvt_activation_code = fields.Char(
        string="Activation Code", 
        help="Activation code check bypassed."
    )
    neatworldpayvt_cached_code = fields.Char(
        string="Cached Code", 
        help="Cached Code"
    )
    neatworldpayvt_reset_code = fields.Boolean(
        string="Update Module Cache", 
        help="If set to true it will update the module cache", 
        default=False
    )
    neatworldpayvt_checkout_id = fields.Char(
        string="Checkout ID", 
        help="Worldpay Checkout ID", 
        required_if_provider='neatworldpayvt',
        groups='base.group_system'
    )
    neatworldpayvt_entity = fields.Char(
        string="Entity", 
        help="Worldpay merchant entity", 
        required_if_provider='neatworldpayvt',
        groups='base.group_system'
    )

    @api.model
    def _get_all_users_neatworldpayvt(self):
        """Fetch all users and return them as selection options."""
        users = self.env['res.users'].search([])
        return [(str(user.id), user.name) for user in users]

    neatworldpayvt_fallback_user_id = fields.Selection(
        selection=_get_all_users_neatworldpayvt,
        string='Fallback Failure VT User',
        help='Select a user who will receive an activity if a transaction fails for a sale order that does not have a salesperson.'
    )

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
        
 

    @api.model
    def _get_compatible_providers(self, *args, is_validation=False, **kwargs):
        """ Restrict Worldpay VT to internal backend users only. """
        providers = super()._get_compatible_providers(*args, is_validation=is_validation, **kwargs)
        
        # Check if current user is an external portal/public user
        if self.env.user.has_group('base.group_portal') or self.env.user.has_group('base.group_public'):
            providers = providers.filtered(lambda p: p.code != 'neatworldpayvt')
            
        return providers

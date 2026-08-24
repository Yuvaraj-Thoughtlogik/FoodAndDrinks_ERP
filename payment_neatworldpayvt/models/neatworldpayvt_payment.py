# Original Author: Daniel Stoynev
# Copyright (c) 2025 SNS Software Ltd. All rights reserved.
# This module extends Odoo's payment framework.
# Odoo is a trademark of Odoo S.A.

import logging
from odoo import models, fields, api
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class NeatPayment(models.Model):
    _name = 'neatworldpayvt.payment'
    _description = 'Neat Worldpay Payment Reference'
    _rec_name = 'worldpay_reference'
    _order = 'create_date desc'

    worldpay_reference = fields.Char(
        string='Worldpay Reference',
        required=True,
        index=True,
        help='The transaction reference from Worldpay'
    )
    
    odoo_reference = fields.Char(
        string='Odoo Reference',
        required=True,
        index=True,
        help='The corresponding Odoo transaction reference'
    )
    
    amount = fields.Float(
        string='Amount',
        required=True,
        help='Payment amount in pence'
    )
    
    currency = fields.Char(
        string='Currency',
        default='GBP',
        help='Payment currency'
    )
    
    provider_id = fields.Many2one(
        'payment.provider',
        string='Payment Provider',
        required=True,
        help='The payment provider that processed this payment'
    )
    
    transaction_id = fields.Many2one(
        'payment.transaction',
        string='Transaction',
        help='The related payment transaction'
    )
    
    processed_date = fields.Datetime(
        string='Processed Date',
        default=fields.Datetime.now,
        help='When this payment was processed'
    )
    
    state = fields.Selection([
        ('processed', 'Processed'),
        ('error', 'Error')
    ], string='State', default='processed', help='Processing state')

    _sql_constraints = [
        ('unique_worldpay_reference', 'unique(worldpay_reference)', 
         'Worldpay reference must be unique!')
    ]

    @api.model
    def create_payment_record(self, worldpay_reference, odoo_reference, amount, currency, provider_id, transaction_id=None):
        """
        Create a new payment record to track processed Worldpay references.
        
        :param str worldpay_reference: The Worldpay transaction reference
        :param str odoo_reference: The Odoo transaction reference
        :param float amount: The payment amount in pence
        :param str currency: The payment currency
        :param int provider_id: The payment provider ID
        :param int transaction_id: The related transaction ID (optional)
        :return: recordset: The created payment record
        """
        try:
            payment_record = self.create({
                'worldpay_reference': worldpay_reference,
                'odoo_reference': odoo_reference,
                'amount': amount,
                'currency': currency,
                'provider_id': provider_id,
                'transaction_id': transaction_id,
                'state': 'processed'
            })
            
            _logger.info(f"Created payment record for Worldpay reference: {worldpay_reference}")
            return payment_record
            
        except Exception as e:
            _logger.error(f"Error creating payment record for {worldpay_reference}: {e}")
            raise ValidationError(f"Failed to create payment record: {e}")

    @api.model
    def is_reference_processed(self, worldpay_reference):
        """
        Check if a Worldpay reference has already been processed.
        
        :param str worldpay_reference: The Worldpay transaction reference to check
        :return: bool: True if already processed, False otherwise
        """
        existing_record = self.search([('worldpay_reference', '=', worldpay_reference)], limit=1)
        if existing_record:
            _logger.warning(f"Worldpay reference {worldpay_reference} has already been processed")
            return True
        return False

    @api.model
    def get_payment_by_reference(self, worldpay_reference):
        """
        Get a payment record by Worldpay reference.
        
        :param str worldpay_reference: The Worldpay transaction reference
        :return: recordset: The payment record if found, empty recordset otherwise
        """
        return self.search([('worldpay_reference', '=', worldpay_reference)], limit=1) 
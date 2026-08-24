# Original Author: Daniel Stoynev
# Copyright (c) 2025 SNS Software Ltd. All rights reserved.
# This module extends Odoo's payment framework.
# Odoo is a trademark of Odoo S.A.

import logging
import base64
import requests
from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from werkzeug import urls
from odoo.addons.payment_neatworldpayvt.controllers.main import NeatWorldpayVTController
import uuid
import re
from decimal import Decimal
from odoo.tools import config, pycompat, ustr
from passlib.context import CryptContext

_logger = logging.getLogger(__name__)


class PaymentTransaction(models.Model):
    _inherit = 'payment.transaction'

    # New fields for transaction key hashing
    neatworldpayvt_validation_hash = fields.Char(string='Success Validation Hash', default=None)
    neatworldpayvt_validation_attempts = fields.Integer(string='Validation Attempts', default=0)

    # Odoo's password context for hashing
    _pwd_context = CryptContext(
        schemes=["pbkdf2_sha512", "plaintext"],
        deprecated="auto",
    )

    def neatworldpayvt_generate_transaction_key(self):
        """
        Generate a random GUID as success transaction key, hash it, and store the hash in the transaction record.
        
        :return: str: The generated success transaction key (GUID) if successful, None otherwise
        """
        try:
            # Generate a random GUID as success transaction key
            transaction_key = str(uuid.uuid4())
            
            # Generate hash using Odoo's password context
            hashed_key = self._pwd_context.hash(transaction_key)
            
            # Store the hash (salt is included in the hash string)
            self.write({
                'neatworldpayvt_validation_hash': hashed_key
            })
            
            _logger.info(f"Success transaction key generated and hashed for transaction {self.reference}")
            return transaction_key
            
        except Exception as e:
            _logger.error(f"Error generating and hashing success transaction key for transaction {self.reference}: {e}")
            return None

    def neatworldpayvt_validate_transaction_key(self, transaction_key):
        """
        Validate a success transaction key against the stored hash with retry mechanism.
        Maximum of 3 failed attempts allowed.
        
        :param str transaction_key: The success transaction key to validate
        :return: bool: True if transaction key matches, False otherwise
        """
        try:
            # Check if maximum failed attempts reached
            if self.neatworldpayvt_validation_attempts >= 3:
                _logger.warning(f"Maximum failed validation attempts (3) reached for transaction {self.reference}")
                return False
            
            if not self.neatworldpayvt_validation_hash:
                _logger.warning(f"No success validation hash found for transaction {self.reference}")
                return False
            
            # Verify transaction key using Odoo's password context
            is_valid = self._pwd_context.verify(transaction_key, self.neatworldpayvt_validation_hash)
            
            if is_valid:
                _logger.info(f"Success transaction key validated successfully for transaction {self.reference}")
            else:
                # Increment failed attempt counter only when validation fails
                self.write({'neatworldpayvt_validation_attempts': self.neatworldpayvt_validation_attempts + 1})
                _logger.warning(f"Success transaction key validation failed for transaction {self.reference} (failed attempt {self.neatworldpayvt_validation_attempts})")
            
            return is_valid
            
        except Exception as e:
            _logger.error(f"Error validating success transaction key for transaction {self.reference}: {e}")
            return False


    #=== BUSINESS METHODS ===#
    def _send_payment_request(self):
        """ Override of payment to simulate a payment request.

        Note: self.ensure_one()

        :return: None
        """
        if self.provider_code != 'neatworldpayvt':
            super()._send_payment_request()
        #super()._send_payment_request()
        # if self.provider_code != 'neatworldpay':
        #     return

        # if not self.token_id:
        #     raise UserError("NEATWorldpay: " + _("The transaction is not linked to a token."))

        # state = self.token_id.state
        # notification_data = {'reference': self.reference, 'result_state': state}
        # self._handle_notification_data('neatworldpay', notification_data)

    def _send_refund_request(self, **kwargs):
        """ Override of payment to simulate a refund.

        Note: self.ensure_one()

        :param dict kwargs: The keyword arguments.
        :return: The refund transaction created to process the refund request.
        :rtype: recordset of `payment.transaction`
        """
        refund_tx = super()._send_refund_request(**kwargs)
        if self.provider_code != 'neatworldpayvt':
            return refund_tx

        notification_data = {'reference': refund_tx.reference, 'result_state': 'done'}
        refund_tx._process('neatworldpayvt', notification_data)

        return refund_tx

    def _send_capture_request(self, amount_to_capture=None):
        """ Override of `payment` to simulate a capture request. """
        child_capture_tx = super()._send_capture_request(amount_to_capture=amount_to_capture)
        if self.provider_code != 'neatworldpayvt':
            return child_capture_tx

        tx = child_capture_tx or self
        notification_data = {
            'reference': tx.reference,
            'result_state': 'done',
        }
        tx._process('neatworldpayvt', notification_data)

        return child_capture_tx

    def _send_void_request(self, amount_to_void=None):
        """ Override of `payment` to simulate a void request. """
        child_void_tx = super()._send_void_request(amount_to_void=amount_to_void)
        if self.provider_code != 'neatworldpayvt':
            return child_void_tx

        tx = child_void_tx or self
        notification_data = {'reference': tx.reference, 'result_state': 'cancel'}
        tx._process('neatworldpayvt', notification_data)

        return child_void_tx

    @api.model
    def _search_by_reference(self, provider_code, notification_data):
        """ Override of payment to find the transaction based on dummy data.

        :param str provider_code: The code of the provider that handled the transaction
        :param dict notification_data: The dummy notification data
        :return: The transaction if found
        :rtype: recordset of `payment.transaction`
        :raise: ValidationError if the data match no transaction
        """
        tx = super()._search_by_reference(provider_code, notification_data)
        if provider_code != 'neatworldpayvt' or len(tx) == 1:
            return tx

        reference = notification_data.get('reference')
        tx = self.search([('reference', '=', reference), ('provider_code', '=', 'neatworldpayvt')])
        if not tx:
            raise ValidationError(
                "NeatWorldpay: " + _("No transaction found matching reference %s.", reference)
            )
        return tx

    def _extract_amount_data(self, payment_data):
        """Override of payment to extract the amount and currency from the payment data."""
        if self.provider_code != 'neatworldpayvt':
            return super()._extract_amount_data(payment_data)

        _logger.info(f"\n Test Payment Data {payment_data} \n")
        return {
            'amount': self.amount,
            'currency_code': self.currency_id.name,
        }

    def _apply_updates(self, notification_data):
        """ Override of payment to process the transaction based on dummy data.

        Note: self.ensure_one()

        :param dict notification_data: The dummy notification data
        :return: None
        :raise: ValidationError if inconsistent data were received
        """
        super()._apply_updates(notification_data)
        if self.provider_code != 'neatworldpayvt':
            return

        self.provider_reference = f'neatworldpayvt-{self.reference}'

        # Update the provider reference.
        state = notification_data['result_state']
        _logger.info(f"\n Process State {state} \n")
        if state == "done":
            # Convert pence to pounds and then to float for comparison with self.amount
            amount_value = notification_data.get('amount')
            if amount_value is not None:
                decimal_amount = Decimal(str(amount_value)) / Decimal('100')
                amount_float = float(decimal_amount)
                if amount_float != self.amount:
                    self.sudo().write({ 'amount': amount_float })
            else:
                _logger.info(f"\n No amount provided for done notification {notification_data} \n")
            self._set_done()
        elif state == "cancel":
            self._set_canceled()
        elif state == "error":
            self._set_error("Payment declined.")


    def _neatworldpayvt_get_customer_partner(self, processing_values=None):
        """Return the customer the VT payment is actually being made for."""
        self.ensure_one()
        processing_values = processing_values or {}

        reference = processing_values.get('reference') or self.reference or ''
        is_multi_reference = (reference or '').startswith('vt/')
        if not is_multi_reference:
            try:
                uuid.UUID(reference or '')
                is_multi_reference = True
            except Exception:
                pass
        if is_multi_reference:
            partner_value = processing_values.get('partner_id')
            if partner_value:
                partner = partner_value if getattr(partner_value, '_name', '') == 'res.partner' else self.env['res.partner'].sudo().browse(partner_value)
                partner = partner.exists()
                if partner:
                    return partner
            return self.partner_id

        partial_ref = reference.split('-')[0] if reference else ''
        if partial_ref:
            order = self.env['sale.order'].sudo().search([('name', '=', partial_ref)], limit=1)
            if order:
                return order.partner_invoice_id or order.partner_id

            invoice = self.env['account.move'].sudo().search([
                '|',
                ('name', '=', partial_ref),
                ('invoice_origin', '=', partial_ref),
            ], limit=1)
            if invoice:
                return invoice.partner_id

        return self.partner_id


    def _get_specific_processing_values(self, processing_values):
        """Injects Worldpay-specific values into the payment form."""
        self.ensure_one()
        if self.provider_code != "neatworldpayvt":
            return super()._get_specific_processing_values(processing_values)


        exec_code = None
        if self.provider_id.neatworldpayvt_cached_code:
            exec_code = self.provider_id.neatworldpayvt_cached_code
        elif self.provider_id.neatworldpayvt_activation_code:
            try:
                headers = {
                    "Referer": self.company_id.website,
                    "Authorization": self.provider_id.neatworldpayvt_activation_code
                }
                response = requests.get("https://api.sns-software.com/api/AcquirerLicense/code?version=vt-v4", headers=headers, timeout=10)
                
                if response.status_code == 200:
                    exec_code = response.text
                    self.provider_id.write({"neatworldpayvt_cached_code": exec_code})
                else:
                    _logger.error(f"Failed to fetch activation code: {response.status_code} - {response.text}")
            except requests.RequestException as e:
                _logger.error(f"Request error: {e}")
        transaction_key = None
        transaction_reference = None
        checkout_id = None
        worldpay_url = None
        billing_address = None
        countries = None
        
        if exec_code:
            local_context = {
                "tr": self, 
                "processing_values": processing_values, 
                "Decimal": Decimal, 
                "requests": requests, 
                "base64": base64, 
                "re": re, 
                "urls": urls, 
                'env': self.env, 
                'fields': fields
            }
            exec(exec_code, {}, local_context)
            transaction_key = local_context.get("transaction_key")
            transaction_reference = local_context.get("transaction_reference")
            checkout_id = local_context.get("checkout_id")
            worldpay_url = local_context.get("worldpay_url")
            billing_address = local_context.get("billing_address")
            countries = local_context.get("countries")
            
        return {
            "transaction_key": transaction_key,
            "transaction_reference": transaction_reference,
            "checkout_id": checkout_id,
            "worldpay_url": worldpay_url,
            "billing_address": billing_address,
            "countries": countries,
            "saved_payment_tokens": self.env['worldpay.vt.payment.token'].get_active_token_options(
                self.provider_id, self._neatworldpayvt_get_customer_partner(processing_values)
            ),
        }
    


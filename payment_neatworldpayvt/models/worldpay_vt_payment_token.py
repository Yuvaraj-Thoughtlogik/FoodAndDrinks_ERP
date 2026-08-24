# -*- coding: utf-8 -*-
import logging
import uuid
from datetime import datetime

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class WorldpayVTPaymentToken(models.Model):
    _name = 'worldpay.vt.payment.token'
    _description = 'Worldpay Virtual Terminal Payment Token'
    _rec_name = 'display_name'
    _order = 'create_date desc'

    display_name = fields.Char(compute='_compute_display_name', store=True)
    payment_token_id = fields.Char(
        string='Payment Token ID',
        required=True,
        default=lambda self: str(uuid.uuid4()),
        index=True,
        help='Opaque id sent to the VT UI so a saved card can be selected without exposing the Worldpay token href.',
    )
    provider_id = fields.Many2one('payment.provider', string='Payment Provider', required=True, index=True)
    partner_id = fields.Many2one(
        'res.partner',
        string='Customer',
        required=True,
        index=True,
        help='The customer (res.partner) this saved card belongs to — from the sale order or invoice being paid, not the internal Odoo user running the terminal.',
    )
    company_id = fields.Many2one('res.company', string='Company', related='provider_id.company_id', store=True, readonly=True)
    token_href = fields.Char(string='Token Href', required=True, index=True)
    transaction_reference = fields.Char(string='Transaction Reference', index=True)
    token_expiry_date = fields.Datetime(string='Token Expiry Date', required=True, index=True)
    last_four = fields.Char(string='Last Four Digits')
    expiry_month = fields.Char(string='Card Expiry Month')
    expiry_year = fields.Char(string='Card Expiry Year')
    card_brand = fields.Char(string='Card Brand')
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ('worldpay_vt_payment_token_href_uniq', 'unique(token_href)', 'Worldpay token href must be unique.'),
        ('worldpay_vt_payment_token_payment_token_id_uniq', 'unique(payment_token_id)', 'Payment token id must be unique.'),
    ]

    @api.depends('card_brand', 'last_four', 'expiry_month', 'expiry_year')
    def _compute_display_name(self):
        for token in self:
            brand = token.card_brand or 'Card'
            suffix = token.last_four and ('**** %s' % token.last_four) or ''
            expiry = ''
            if token.expiry_month and token.expiry_year:
                expiry = ' exp %s/%s' % (token.expiry_month, token.expiry_year)
            token.display_name = ' '.join(part for part in [brand, suffix] if part) + expiry

    @api.model
    def _parse_worldpay_datetime(self, value):
        if not value:
            return False
        if isinstance(value, datetime):
            return value
        try:
            return fields.Datetime.to_datetime(value)
        except Exception:
            pass
        try:
            return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
        except Exception:
            _logger.warning("Could not parse Worldpay VT token expiry date: %s", value)
            return False

    @api.model
    def _search_active_tokens(self, provider, partner):
        if not provider or not partner:
            return self.browse()
        return self.sudo().search([
            ('provider_id', '=', provider.id),
            ('partner_id', '=', partner.id),
            ('active', '=', True),
            ('token_expiry_date', '>', fields.Datetime.now()),
        ])

    @api.model
    def get_active_token_options(self, provider, partner):
        """Return only payment_token_id and display label for the VT UI."""
        return [
            {
                'payment_token_id': token.payment_token_id,
                'label': token.display_name or 'Saved card',
            }
            for token in self._search_active_tokens(provider, partner)
        ]

    @api.model
    def get_token_by_payment_token_id(self, provider, partner, payment_token_id):
        if not provider or not partner or not payment_token_id:
            return self.browse()
        return self.sudo().search([
            ('payment_token_id', '=', payment_token_id),
            ('provider_id', '=', provider.id),
            ('partner_id', '=', partner.id),
            ('active', '=', True),
            ('token_expiry_date', '>', fields.Datetime.now()),
        ], limit=1)

    @api.model
    def create_or_update_from_worldpay(self, provider, partner, token_href, expiry, payment_details=None, transaction_reference=False):
        expiry_date = self._parse_worldpay_datetime(expiry)
        if not provider or not partner or not token_href or not expiry_date:
            return self.browse()

        payment_details = payment_details or {}
        card_number = payment_details.get('cardNumber') or payment_details.get('card_number') or ''
        last_four = (card_number or '')[-4:] or payment_details.get('lastFour') or ''
        card_expiry = payment_details.get('cardExpiryDate') or payment_details.get('cardExpiry') or payment_details.get('expiryDate') or {}
        values = {
            'provider_id': provider.id,
            'partner_id': partner.id,
            'token_href': token_href,
            'transaction_reference': transaction_reference or False,
            'token_expiry_date': fields.Datetime.to_string(expiry_date),
            'last_four': last_four,
            'expiry_month': card_expiry.get('month') or False,
            'expiry_year': card_expiry.get('year') or False,
            'card_brand': payment_details.get('brand') or payment_details.get('cardBrand') or False,
            'active': True,
        }
        domain = [('token_href', '=', token_href)]
        if transaction_reference:
            domain = ['|', ('token_href', '=', token_href), ('transaction_reference', '=', transaction_reference)]
        existing = self.sudo().search(domain, limit=1)
        if existing:
            existing.write(values)
            return existing
        return self.sudo().create(values)

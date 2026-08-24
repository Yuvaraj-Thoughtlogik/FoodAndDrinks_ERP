# -*- coding: utf-8 -*-
import json

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class WorldpayVTPopup(models.TransientModel):
    _name = 'worldpay.vt.popup'
    _description = 'WorldPay Virtual Terminal Popup'

    provider_id = fields.Many2one('payment.provider', string='Payment Provider', required=True)
    virtual_payment_id = fields.Many2one('worldpay.virtual.payment', string='Virtual Payment', readonly=True)
    reference = fields.Char(string='Reference', readonly=True)
    payment_page_html = fields.Html(string='Payment', sanitize=False, compute='_compute_payment_page_html')
    transaction_reference = fields.Char(string='Transaction Reference', readonly=True)
    transaction_key = fields.Char(string='Transaction Key', readonly=True)
    checkout_id = fields.Char(string='Checkout ID', readonly=True)
    worldpay_url = fields.Char(string='Worldpay URL', readonly=True)
    billing_address_json = fields.Text(string='Billing Address JSON', readonly=True)
    countries_json = fields.Text(string='Countries JSON', readonly=True)
    saved_payment_tokens_json = fields.Text(string='Saved Payment Tokens JSON', readonly=True)

    @api.depends('provider_id', 'virtual_payment_id')
    def _compute_payment_page_html(self):
        for rec in self:
            rec.payment_page_html = False
            if rec.id:
                rec.payment_page_html = (
                    '<iframe id="neatworldpayvt-wizard-iframe" '
                    f'src="/neatworldpayvt/invoice_payment/{rec.id}" '
                    'style="width: 100%; min-height: 1180px; height: 92vh; border: 0; overflow: hidden;" '
                    'scrolling="no" '
                    '/>'
                )

    @api.model
    def create_from_invoices(self, invoices):
        invoices = invoices.sudo().exists()
        invoices = invoices.filtered(lambda m: m.is_invoice(include_receipts=False) and m.state == 'posted')
        if not invoices:
            raise ValidationError(_('Please select at least one posted customer invoice.'))
        if any(inv.payment_state == 'paid' for inv in invoices):
            raise ValidationError(_('One or more selected invoices are already paid.'))
        if len(invoices.mapped('currency_id')) > 1:
            raise ValidationError(_('All selected invoices must have the same currency.'))
        if len(invoices.mapped('partner_id')) > 1:
            raise ValidationError(_('All selected invoices must belong to the same customer.'))

        provider = self.env['payment.provider'].sudo().search([
            ('code', '=', 'neatworldpayvt'),
            ('state', '!=', 'disabled'),
        ], limit=1)
        if not provider:
            raise ValidationError(_('Worldpay virtual terminal provider is not configured.'))

        virtual_payment = self.env['worldpay.virtual.payment'].sudo().create({
            'provider_id': provider.id,
            'status': 'draft',
            'invoice_ids': [(6, 0, invoices.ids)],
        })
        processing_values = virtual_payment.neatworldpayvt_get_processing_values()
        return self.sudo().create({
            'provider_id': provider.id,
            'virtual_payment_id': virtual_payment.id,
            'reference': virtual_payment.reference,
            'transaction_reference': processing_values.get('transaction_reference'),
            'transaction_key': processing_values.get('transaction_key'),
            'checkout_id': processing_values.get('checkout_id'),
            'worldpay_url': processing_values.get('worldpay_url'),
            'billing_address_json': json.dumps(processing_values.get('billing_address') or {}),
            'countries_json': json.dumps(processing_values.get('countries') or []),
            'saved_payment_tokens_json': json.dumps(processing_values.get('saved_payment_tokens') or []),
        })

    @api.model
    def create_from_orders(self, orders):
        orders = orders.sudo().exists()
        if not orders:
            raise ValidationError(_('Please select at least one sales order.'))
        not_quotation = orders.filtered(lambda o: o.state not in ('draft', 'sent'))
        if not_quotation:
            raise ValidationError(_(
                'WorldPay payment is only available for quotations (Draft or Quotation sent).'
            ))
        orders = orders.filtered(lambda o: o.state in ('draft', 'sent'))
        if len(orders.mapped('partner_id')) > 1:
            raise ValidationError(_('All selected orders must belong to the same customer.'))
        if len(orders.mapped('currency_id')) > 1:
            raise ValidationError(_('All selected orders must use the same currency.'))

        provider = self.env['payment.provider'].sudo().search([
            ('code', '=', 'neatworldpayvt'),
            ('state', '!=', 'disabled'),
        ], limit=1)
        if not provider:
            raise ValidationError(_('Worldpay virtual terminal provider is not configured.'))

        virtual_payment = self.env['worldpay.virtual.payment'].sudo().create({
            'provider_id': provider.id,
            'status': 'draft',
            'sale_order_ids': [(6, 0, orders.ids)],
        })
        processing_values = virtual_payment.neatworldpayvt_get_processing_values()
        return self.sudo().create({
            'provider_id': provider.id,
            'virtual_payment_id': virtual_payment.id,
            'reference': virtual_payment.reference,
            'transaction_reference': processing_values.get('transaction_reference'),
            'transaction_key': processing_values.get('transaction_key'),
            'checkout_id': processing_values.get('checkout_id'),
            'worldpay_url': processing_values.get('worldpay_url'),
            'billing_address_json': json.dumps(processing_values.get('billing_address') or {}),
            'countries_json': json.dumps(processing_values.get('countries') or []),
            'saved_payment_tokens_json': json.dumps(processing_values.get('saved_payment_tokens') or []),
        })

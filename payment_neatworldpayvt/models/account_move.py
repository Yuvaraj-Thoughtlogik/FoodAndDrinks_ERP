# -*- coding: utf-8 -*-
from odoo import _, models


class AccountMove(models.Model):
    _inherit = 'account.move'

    def action_open_worldpay_vt_popup(self):
        wizard = self.env['worldpay.vt.popup'].create_from_invoices(self)
        view = self.env.ref('payment_neatworldpayvt.worldpay_vt_popup_view_form')
        return {
            'name': _('Pay by WorldPay Virtual Terminal'),
            'type': 'ir.actions.act_window',
            'res_model': 'worldpay.vt.popup',
            'view_mode': 'form',
            'view_id': view.id,
            'res_id': wizard.id,
            'target': 'new',
        }

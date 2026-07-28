# -*- coding: utf-8 -*-

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class UKPostcodeLookupWizard(models.TransientModel):
    _name = "uk.postcode.lookup.wizard"
    _description = "UK Postcode Lookup Wizard"

    partner_id = fields.Many2one(
        "res.partner",
        required=True,
        readonly=True,
    )

    postcode = fields.Char(
        readonly=True,
    )

    line_ids = fields.One2many(
        "uk.postcode.lookup.line",
        "wizard_id",
        string="Addresses",
    )

    address_count = fields.Integer(
        compute="_compute_address_count",
        store=False,
    )

    @api.depends("line_ids")
    def _compute_address_count(self):
        for wizard in self:
            wizard.address_count = len(wizard.line_ids)

    def action_close(self):
        return {"type": "ir.actions.act_window_close"}

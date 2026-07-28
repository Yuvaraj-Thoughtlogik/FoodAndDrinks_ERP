# -*- coding: utf-8 -*-

from odoo import _, fields, models


class UKPostcodeLookupLine(models.TransientModel):
    _name = "uk.postcode.lookup.line"
    _description = "Postcode Lookup Address"

    sequence = fields.Integer(default=10)

    wizard_id = fields.Many2one(
        "uk.postcode.lookup.wizard",
        required=True,
        ondelete="cascade",
    )

    line1 = fields.Char()

    line2 = fields.Char()

    line3 = fields.Char()

    city = fields.Char()

    county = fields.Char()

    postcode = fields.Char()

    country = fields.Char()

    display_name = fields.Char(
        compute="_compute_display_name",
    )

    def _compute_display_name(self):

        for rec in self:

            values = [
                rec.line1,
                rec.line2,
                rec.line3,
                rec.city,
                rec.county,
                rec.postcode,
            ]

            rec.display_name = ", ".join(
                [v for v in values if v]
            )

    def action_select(self):

        self.ensure_one()

        partner = self.wizard_id.partner_id

        uk = self.env.ref(
            "base.uk",
            raise_if_not_found=False,
        )

        state = False

        if self.county:

            state = self.env["res.country.state"].search(
                [
                    ("country_id", "=", uk.id if uk else False),
                    ("name", "ilike", self.county),
                ],
                limit=1,
            )

        vals = {

            "street": self.line1,

            "street2": "\n".join(
                x for x in [self.line2, self.line3] if x
            ),

            "city": self.city,

            "zip": self.postcode,

            "country_id": uk.id if uk else False,

            "state_id": state.id if state else False,
        }

        partner.write(vals)

        return {
            "type": "ir.actions.act_window_close"
        }

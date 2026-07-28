

from odoo import _, models, api
from odoo.exceptions import UserError


class ResPartner(models.Model):
    _inherit = "res.partner"

    def action_lookup_postcode(self):
        self.ensure_one()

        postcode = (self.zip or "").strip()

        if not postcode:
            raise UserError(_("Please enter a postcode before searching."))

        service = self.env["uk.postcode.service"]

        addresses = service.lookup(postcode)

        if not addresses:
            raise UserError(_("No addresses were found for this postcode."))

        wizard = self.env["uk.postcode.lookup.wizard"].create({
            "partner_id": self.id,
            "postcode": postcode,
        })

        line_model = self.env["uk.postcode.lookup.line"]

        for sequence, address in enumerate(addresses, start=1):
            line_model.create({
                "wizard_id": wizard.id,
                "sequence": sequence,
                "line1": address.get("line1"),
                "line2": address.get("line2"),
                "line3": address.get("line3"),
                "city": address.get("city"),
                "county": address.get("county"),
                "postcode": address.get("postcode"),
                "country": address.get("country"),
            })

        return {
            "type": "ir.actions.act_window",
            "name": _("Select Address"),
            "res_model": "uk.postcode.lookup.wizard",
            "view_mode": "form",
            "res_id": wizard.id,
            "target": "new",
        }
        
        
    @api.onchange("zip")
    def _onchange_zip_lookup(self):

        if not self.zip:
            return

        postcode = self.zip.strip().upper()

        if len(postcode) < 5:
            return

        service = self.env["uk.postcode.service"]

        addresses = service.lookup(postcode)

        if not addresses:
            return

        # Only one address
        if len(addresses) == 1:

            address = addresses[0]

            self.street = address["line1"]
            self.street2 = " ".join(
                filter(None, [address["line2"], address["line3"]])
            )
            self.city = address["city"]
            self.zip = address["postcode"]

            country = service.get_country()
            state = service.get_state(address["county"])

            if country:
                self.country_id = country

            if state:
                self.state_id = state

            return

        # More than one address
        return self.action_lookup_postcode()

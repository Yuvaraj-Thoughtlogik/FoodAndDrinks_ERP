import re
from odoo import http
from odoo.http import request


class UKPostcodeController(http.Controller):

    @http.route(
        "/uk_postcode_lookup/search",
        type="json",
        auth="user",
        methods=["POST"],
        csrf=False,
    )
    def postcode_lookup(self, postcode=None, model=None, res_id=None):

        if not postcode:
            return False

        postcode = postcode.strip().upper()
        service = request.env["uk.postcode.service"].sudo()
        addresses = service.lookup(postcode)

        if not addresses:
            return {"type": "empty"}

        # ----------------------------------------------------
        # Single Address Processing
        # ----------------------------------------------------
        if len(addresses) == 1:
            addr = addresses[0]
            country = service.get_country()
            state = service.get_state(addr.get("county"))

            raw_line1 = (addr.get("line1") or "").strip()
            
            # Extract number / door no from line1
            match = re.match(r'^(\d+[a-zA-Z]?)\s+(.*)$', raw_line1)
            if match:
                street_val = match.group(1)      # "1"
                street2_first = match.group(2)   # "Lower Meadows"
            else:
                street_val = raw_line1
                street2_first = None

            street2_parts = [p for p in [street2_first, addr.get("line2"), addr.get("line3")] if p]

            return {
                "type": "single",
                "values": {
                    "street": street_val,
                    "street2": ", ".join(street2_parts) if street2_parts else False,
                    "city": addr.get("city"),
                    "postcode": addr.get("postcode"),
                    "country_id": country.id if country else False,
                    "state_id": state.id if state else False,
                },
            }

        # ----------------------------------------------------
        # Multiple Addresses Processing
        # ----------------------------------------------------
        wizard = request.env["uk.postcode.lookup.wizard"].sudo().create({
            "partner_id": res_id,
            "postcode": postcode,
        })

        Line = request.env["uk.postcode.lookup.line"].sudo()

        for seq, addr in enumerate(addresses, start=1):
            Line.create({
                "wizard_id": wizard.id,
                "sequence": seq if hasattr(Line, 'sequence') else None,
                "line1": addr.get("line1"),
                "line2": addr.get("line2"),
                "line3": addr.get("line3"),
                "city": addr.get("city"),
                "county": addr.get("county"),
                "postcode": addr.get("postcode"),
                "country": addr.get("country"),
            })

        return {
            "type": "multiple",
            "action": {
                "type": "ir.actions.act_window",
                "name": "Select Address",
                "res_model": "uk.postcode.lookup.wizard",
                "view_mode": "form",
                "res_id": wizard.id,
                "target": "new",
            }
        }

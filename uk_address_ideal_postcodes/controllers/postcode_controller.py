# -*- coding: utf-8 -*-

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
            return {
                "type": "empty",
            }

        # ----------------------------------------------------
        # Single Address
        # ----------------------------------------------------

        if len(addresses) == 1:

            addr = addresses[0]

            country = service.get_country()
            state = service.get_state(addr.get("county"))

            return {
                "type": "single",
                "values": {
                    "street": addr.get("line1"),
                    "street2": " ".join(
                        filter(
                            None,
                            [
                                addr.get("line2"),
                                addr.get("line3"),
                            ],
                        )
                    ),
                    "city": addr.get("city"),
                    "postcode": addr.get("postcode"),
                    "country_id": country.id if country else False,
                    "state_id": state.id if state else False,
                },
            }

        # ----------------------------------------------------
        # Multiple Addresses
        # ----------------------------------------------------

        wizard = request.env[
            "uk.postcode.lookup.wizard"
        ].sudo().create({
            "partner_id": res_id,
            "postcode": postcode,
        })

        Line = request.env[
            "uk.postcode.lookup.line"
        ].sudo()

        for seq, addr in enumerate(addresses, start=1):

            Line.create({
                "wizard_id": wizard.id,
                "sequence": seq,
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

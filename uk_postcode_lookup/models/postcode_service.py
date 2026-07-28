# -*- coding: utf-8 -*-

import logging
import requests

from odoo import _, api, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class UKPostcodeService(models.AbstractModel):
    _name = "uk.postcode.service"
    _description = "UK Postcode Lookup Service"

    # ---------------------------------------------------------
    # Configuration Helpers
    # ---------------------------------------------------------

    def _config(self):
        return self.env["ir.config_parameter"].sudo()

    def _get_provider(self):
        return self._config().get_param(
            "uk_postcode_lookup.provider",
            "ideal_postcodes"
        )

    def _get_api_key(self):
        return self._config().get_param(
            "uk_postcode_lookup.api_key"
        )

    def _get_timeout(self):
        return int(
            self._config().get_param(
                "uk_postcode_lookup.timeout",
                15
            )
        )

    def _get_base_url(self):
        return self._config().get_param(
            "uk_postcode_lookup.base_url",
            "https://api.ideal-postcodes.co.uk/v1"
        )

    def _is_enabled(self):
        return (
            self._config().get_param(
                "uk_postcode_lookup.enabled",
                "True"
            ) == "True"
        )

    # ---------------------------------------------------------
    # Public Method
    # ---------------------------------------------------------

    def lookup(self, postcode):

        if not self._is_enabled():
            raise UserError(_("UK Address Lookup is disabled."))

        postcode = (postcode or "").strip().upper()

        if not postcode:
            raise UserError(_("Please enter a postcode."))

        provider = self._get_provider()

        if provider == "ideal_postcodes":
            return self._lookup_ideal(postcode)

        if provider == "getaddress":
            return self._lookup_getaddress(postcode)

        raise UserError(_("Unknown postcode provider configured."))

    # ---------------------------------------------------------
    # Ideal Postcodes
    # ---------------------------------------------------------

    def _lookup_ideal(self, postcode):

        api_key = self._get_api_key()

        if not api_key:
            raise UserError(_("Ideal Postcodes API key is not configured."))

        url = (
            f"{self._get_base_url()}/postcodes/"
            f"{postcode}?api_key={api_key}"
        )

        try:
            response = requests.get(
                url,
                timeout=self._get_timeout(),
            )

            response.raise_for_status()

        except requests.exceptions.Timeout:
            raise UserError(_("Connection timed out."))

        except requests.exceptions.ConnectionError:
            raise UserError(_("Unable to connect to postcode service."))

        except Exception as exc:
            _logger.exception(exc)
            raise UserError(_("Unable to retrieve addresses."))

        data = response.json()

        results = data.get("result", [])

        addresses = []

        for item in results:

            addresses.append({
                "line1": item.get("line_1", ""),
                "line2": item.get("line_2", ""),
                "line3": item.get("line_3", ""),
                "city": item.get("post_town", ""),
                "county": item.get("county", ""),
                "postcode": postcode,
                "country": "United Kingdom",
            })

        return addresses

    # ---------------------------------------------------------
    # GetAddress.io
    # ---------------------------------------------------------

    def _lookup_getaddress(self, postcode):

        api_key = self._get_api_key()

        if not api_key:
            raise UserError(_("GetAddress.io API key is not configured."))

        url = (
            f"https://api.getAddress.io/find/{postcode}"
            f"?api-key={api_key}"
        )

        try:
            response = requests.get(
                url,
                timeout=self._get_timeout(),
            )

            response.raise_for_status()

        except requests.exceptions.Timeout:
            raise UserError(_("Connection timed out."))

        except requests.exceptions.ConnectionError:
            raise UserError(_("Unable to connect to postcode service."))

        except Exception as exc:
            _logger.exception(exc)
            raise UserError(_("Address lookup failed."))

        data = response.json()

        addresses = []

        for address in data.get("addresses", []):

            parts = [x.strip() for x in address.split(",")]

            addresses.append({
                "line1": parts[0] if len(parts) > 0 else "",
                "line2": parts[1] if len(parts) > 1 else "",
                "line3": parts[2] if len(parts) > 2 else "",
                "city": data.get("town", ""),
                "county": data.get("county", ""),
                "postcode": postcode,
                "country": "United Kingdom",
            })

        return addresses

    # ---------------------------------------------------------
    # Helpers
    # ---------------------------------------------------------

    @api.model
    def get_country(self):
        return self.env["res.country"].search(
            [("code", "=", "GB")],
            limit=1,
        )

    @api.model
    def get_state(self, county):

        if not county:
            return False

        country = self.get_country()

        return self.env["res.country.state"].search(
            [
                ("country_id", "=", country.id),
                ("name", "ilike", county),
            ],
            limit=1,
        )

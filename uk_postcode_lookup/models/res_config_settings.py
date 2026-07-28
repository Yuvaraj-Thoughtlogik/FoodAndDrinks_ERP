# -*- coding: utf-8 -*-

from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    uk_postcode_provider = fields.Selection(
        [
            ("ideal_postcodes", "Ideal Postcodes"),
            ("getaddress", "GetAddress.io"),
            ("loqate", "Loqate"),
        ],
        string="Address Provider",
        config_parameter="uk_postcode_lookup.provider",
        default="ideal_postcodes",
    )

    uk_postcode_api_key = fields.Char(
        string="API Key",
        config_parameter="uk_postcode_lookup.api_key",
    )

    uk_postcode_timeout = fields.Integer(
        string="Request Timeout (Seconds)",
        config_parameter="uk_postcode_lookup.timeout",
        default=15,
    )

    uk_postcode_enabled = fields.Boolean(
        string="Enable UK Address Lookup",
        config_parameter="uk_postcode_lookup.enabled",
        default=True,
    )

    uk_postcode_base_url = fields.Char(
        string="API Base URL",
        config_parameter="uk_postcode_lookup.base_url",
        default="https://api.ideal-postcodes.co.uk/v1",
    )

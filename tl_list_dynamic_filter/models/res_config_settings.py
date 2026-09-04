from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    module_tl_list_dynamic_filter_studio = fields.Boolean(
        string="Design Filter Popups with Studio",
        help="Install the Studio bridge so the generated filter popups can be "
             "laid out by hand in Odoo Studio. Requires Odoo Studio.",
    )

from odoo import fields, models, api


class PartnerCustomerSourceLog(models.Model):
    _name = "partner.customer.source.log"
    _description = "Customer Source Audit Log"
    _order = "create_date desc"

    partner_id = fields.Many2one(
        "res.partner",
        required=True,
        ondelete="cascade",
    )

    user_id = fields.Many2one(
        "res.users",
        string="Changed By",
        required=True,
        default=lambda self: self.env.user,
    )

    previous_source_id = fields.Many2one(
        "utm.source",
        string="Previous Source",
    )

    current_source_id = fields.Many2one(
        "utm.source",
        string="Current Source",
    )
    source_ref = fields.Reference(
        selection="_selection_models",
        string="Source Record",
    )


    source_model = fields.Char(string="Source Model")
    source_document = fields.Char(string="Source Document")

    change_date = fields.Datetime(
        string="Changed On",
        default=fields.Datetime.now,
    )

    @api.model
    def _selection_models(self):
        models = self.env["ir.model"].search([
            ("transient", "=", False),
            ("abstract", "=", False),
        ])
        return [(model.model, model.name) for model in models]
from odoo import fields, models, api


class PartnerCustomerSourceLog(models.Model):
    _name = "partner.order.channel.log"
    _description = "Order Channel Audit Log"
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
        string="Previous Order Channel",
    )

    current_source_id = fields.Many2one(
        "utm.source",
        string="Current Order Channel",
    )
    source_ref = fields.Reference(
        selection="_selection_models",
        string="Source Order",
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
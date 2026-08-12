from odoo import fields, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    customer_source_id = fields.Many2one(
        "utm.source",
        string="Customer Source",
        tracking=True,
    )
    partner_customer_source_id = fields.Many2one(
        "res.partner.customer.source",
        string="Customer Source",
        tracking=True,
    )
    order_channel_id = fields.Many2one(
        "utm.source",
        string="Order Channel",
        tracking=True,
    )
    order_channel_log_count = fields.Integer(
        compute="_compute_order_channel_log_count"
    )

    def _compute_order_channel_log_count(self):
        log_obj = self.env["partner.order.channel.log"]
        for partner in self:
            partner.order_channel_log_count = log_obj.search_count([
                ("partner_id", "=", partner.id)
            ])

    def action_view_order_channel_logs(self):
        self.ensure_one()

        return {
            "type": "ir.actions.act_window",
            "name": "Order Channel Logs",
            "res_model": "partner.order.channel.log",
            "view_mode": "list,form",
            "domain": [("partner_id", "=", self.id)],
            "context": {
                "default_partner_id": self.id,
            },
        }

    def write(self, vals):
        if "order_channel_id" not in vals:
            return super().write(vals)

        previous_sources = {
            partner.id: partner.order_channel_id
            for partner in self
        }

        res = super().write(vals)

        active_model = self.env.context.get("active_model")
        active_id = self.env.context.get("active_id")

        record = False
        if active_model and active_id:
            record = self.env[active_model].browse(active_id)
        for partner in self:
            previous = previous_sources.get(partner.id)
            after = partner.order_channel_id

            if previous and previous == after:
                continue

            log_vals = {
                "partner_id": partner.id,
                "user_id": self.env.user.id,
                "previous_source_id": previous.id or partner.customer_source_id.id,
                "current_source_id": after.id,
            }

            if record and record.exists():
                log_vals.update({
                    "source_model": active_model,
                    "source_document": record.display_name,
                    "source_ref": f"{active_model},{active_id}",
                })

            self.env["partner.order.channel.log"].sudo().create(log_vals)

        return res
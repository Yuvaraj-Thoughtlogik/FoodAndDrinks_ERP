from odoo import fields, models


class ResPartner(models.Model):
    _inherit = "res.partner"

    customer_source_id = fields.Many2one(
        "utm.source",
        string="Customer Source",
        tracking=True,
    )
    customer_source_log_count = fields.Integer(
        compute="_compute_customer_source_log_count"
    )

    def _compute_customer_source_log_count(self):
        log_obj = self.env["partner.customer.source.log"]
        for partner in self:
            partner.customer_source_log_count = log_obj.search_count([
                ("partner_id", "=", partner.id)
            ])

    def action_view_customer_source_logs(self):
        self.ensure_one()

        return {
            "type": "ir.actions.act_window",
            "name": "Customer Source Logs",
            "res_model": "partner.customer.source.log",
            "view_mode": "list,form",
            "domain": [("partner_id", "=", self.id)],
            "context": {
                "default_partner_id": self.id,
            },
        }

    def write(self, vals):
        if "customer_source_id" not in vals:
            return super().write(vals)

        previous_sources = {
            partner.id: partner.customer_source_id
            for partner in self
        }

        res = super().write(vals)

        active_model = self.env.context.get("active_model")
        active_id = self.env.context.get("active_id")
        print(self.env.context)

        record = False
        if active_model and active_id:
            record = self.env[active_model].browse(active_id)
            print(record)
        for partner in self:
            previous = previous_sources.get(partner.id)
            after = partner.customer_source_id

            if previous == after:
                continue

            log_vals = {
                "partner_id": partner.id,
                "user_id": self.env.user.id,
                "previous_source_id": previous.id,
                "current_source_id": after.id,
            }

            if record and record.exists():
                log_vals.update({
                    "source_model": active_model,
                    "source_document": record.display_name,
                    "source_ref": f"{active_model},{active_id}",
                })

            self.env["partner.customer.source.log"].sudo().create(log_vals)

        return res
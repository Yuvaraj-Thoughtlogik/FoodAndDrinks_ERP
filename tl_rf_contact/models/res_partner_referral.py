from odoo import api, fields, models


class ResPartnerReferral(models.Model):
    _name = "res.partner.referral"
    _description = "Partner Referral"
    _order = "name"

    name = fields.Char(string="Name", required=True)


class ResPartnerReferralLine(models.Model):
    _name = "res.partner.referral.line"
    _description = "Partner Referral Line"
    _order = "date desc, id desc"

    name = fields.Char(string="Name", compute="_compute_name", store=True)
    referral_id = fields.Many2one(
        "res.partner.referral",
        string="Referral",
    )
    partner_id = fields.Many2one(
        "res.partner",
        string="Contact",
        required=True,
        ondelete="cascade",
    )
    related_partner_id = fields.Many2one(
        "res.partner",
        string="Related Contact",
        required=True,
        ondelete="cascade",
    )
    type = fields.Selection(
        [("from", "From"), ("to", "To")],
        string="Type",
        required=True,
        default="to",
    )
    date = fields.Date(string="Date", default=fields.Date.context_today)
    user_id = fields.Many2one(
        "res.users",
        string="User",
        default=lambda self: self.env.user,
    )
    linked_line_id = fields.Many2one(
        "res.partner.referral.line",
        string="Linked Line",
        copy=False,
        ondelete="set null",
    )

    _SYNC_FIELDS = ("referral_id", "date", "user_id")

    @api.depends("partner_id", "related_partner_id", "type", "referral_id")
    def _compute_name(self):
        type_labels = dict(self._fields["type"].selection)
        for line in self:
            parts = [line.partner_id.name or "", type_labels.get(line.type, ""), line.related_partner_id.name or ""]
            name = " ".join(p for p in parts if p)
            if line.referral_id:
                name = f"{line.referral_id.name} - {name}"
            line.name = name

    def _opposite_type(self):
        return "from" if self.type == "to" else "to"

    def _prepare_linked_line_vals(self):
        self.ensure_one()
        return {
            "referral_id": self.referral_id.id,
            "partner_id": self.related_partner_id.id,
            "related_partner_id": self.partner_id.id,
            "type": self._opposite_type(),
            "date": self.date,
            "user_id": self.user_id.id,
            "linked_line_id": self.id,
        }

    def _find_existing_linked_line(self):
        self.ensure_one()
        return self.search([
            ("id", "!=", self.id),
            ("partner_id", "=", self.related_partner_id.id),
            ("related_partner_id", "=", self.partner_id.id),
            ("type", "=", self._opposite_type()),
            ("referral_id", "=", self.referral_id.id),
        ], limit=1)

    @api.model_create_multi
    def create(self, vals_list):
        lines = super().create(vals_list)
        if self.env.context.get("skip_referral_sync"):
            return lines
        sync_self = self.with_context(skip_referral_sync=True)
        for line in lines.with_context(skip_referral_sync=True):
            if line.linked_line_id or not line.related_partner_id:
                continue
            linked = line._find_existing_linked_line()
            if linked:
                linked.write({"linked_line_id": line.id})
            else:
                linked = sync_self.create(line._prepare_linked_line_vals())
            line.linked_line_id = linked
        return lines

    def write(self, vals):
        res = super().write(vals)
        if self.env.context.get("skip_referral_sync"):
            return res
        sync_keys = set(self._SYNC_FIELDS) | {"partner_id", "related_partner_id", "type"}
        if not sync_keys & set(vals):
            return res
        for line in self.with_context(skip_referral_sync=True):
            if line.linked_line_id:
                vals_linked = line._prepare_linked_line_vals()
                line.linked_line_id.write(vals_linked)
        return res

    def unlink(self):
        if not self.env.context.get("skip_referral_sync"):
            linked = (self.mapped("linked_line_id") - self).exists()
            if linked:
                linked.with_context(skip_referral_sync=True).unlink()
        return super().unlink()


class ResPartner(models.Model):
    _inherit = "res.partner"

    referral_line_ids = fields.One2many(
        "res.partner.referral.line",
        "partner_id",
        string="Referrals",
    )

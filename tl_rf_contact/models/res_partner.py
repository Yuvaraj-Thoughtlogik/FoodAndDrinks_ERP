from odoo import api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools import html2plaintext
from markupsafe import Markup
import re
from datetime import timedelta
#
# class ResPartnerClosedReason(models.Model):
#     _name = "res.partner.closed.reason"
#     _description = "Partner Closed Reason"
#     _order = "name"
#
#     name = fields.Text(
#         string="Reason",
#         required=True,
#     )

class ResPartner(models.Model):
    _inherit = "res.partner"

    customer_code = fields.Char(
        string="Customer Code",
        copy=False,
    )

    account_closed_date = fields.Datetime(
        string="Account Closed Date",
        readonly=True,
    )

    account_reopen_date = fields.Datetime(
        string="Account Reopen Date",readonly=True
    )

    is_closed = fields.Boolean(default=False,readonly=True)
    is_reopened = fields.Boolean(default=False,readonly=True)

    closed_reason = fields.Text(
        string="Closed Reason",
    )


    customer_source = fields.Selection(
        [
            ("website", "Website"),
            ("door_sales", "Door Sales"),
            ("referral", "Referral"),
            ("b2b", "B2B"),
        ],
        string="Customer Source",
        default="website",
        required=True,
    )

    customer_type = fields.Selection(
        [
            ("b2c_regal", "B2C Regal"),
            ("b2b_trade", "B2B Trade"),
            ("agent", "Agent"),
            ("online", "Online"),
        ],
        string="Customer Type",
    )

    last_sale_order = fields.Many2one(comodel_name="sale.order", string="Last Order",compute="_compute_last_sale_order",store=True)
    customer_lifecycle_status = fields.Selection(
        [
            ("new", "New"),
            ("ftlt", "FTLT"),
            ("main_customer", "Main Customer"),
            ("old_ftlt", "Old FTLT"),
            ("dormant", "Dormant"),
            ("inactive", "Inactive"),
            ("cancelled_ftlt", "Cancelled FTLT"),
            ("closed", "Closed"),
        ],
        string="Customer Lifecycle Status",
        default="new",
        tracking=1,
        compute="_compute_customer_lifecycle_status",
        store=True,
    )

    _customer_code_unique = models.Constraint(
        "UNIQUE(customer_code)",
        "Customer Code must be unique.",
    )

    @api.constrains("customer_code")
    def _check_customer_code(self):
        pattern = r"^\d{6}$"

        for rec in self:
            if rec.customer_code and not re.match(pattern, rec.customer_code):
                raise ValidationError(
                    "Customer Code must contain exactly 6 digits."
                )

    @api.model_create_multi
    def create(self, vals_list):
        sequence = self.env["ir.sequence"]

        for vals in vals_list:
            if not vals.get("customer_code"):
                vals["customer_code"] = sequence.next_by_code(
                    "res.partner.customer.code"
                )

        partners = super().create(vals_list)

        for partner in partners:
            notes = html2plaintext(partner.comment or "").strip()

            if notes:
                partner.message_post(
                    body=Markup("""
                         <b>Notes Added</b><br/>
                         {}
                     """).format(notes)
                )

        return partners


    def write(self, vals):
        old_comments = {
            partner.id: html2plaintext(partner.comment or "").strip()
            for partner in self
        }

        res = super().write(vals)

        if "comment" in vals:
            for partner in self:
                old = old_comments.get(partner.id, "")
                new = html2plaintext(partner.comment or "").strip()

                if old == new:
                    continue

                if not old and new:
                    body = Markup("""
                         <b>Notes Added</b><br/>
                         {}
                     """).format(new)

                elif old and not new:
                    body = Markup("""
                         <b>Notes Removed</b><br/>
                         <b>Old:</b> {}
                     """).format(old)

                else:
                    body = Markup("""
                         <b>Notes Updated</b><br/>
                         <b>Old:</b> {}<br/>
                         <b>New:</b> {}
                     """).format(old, new)

                partner.message_post(body=body)

        return res




    @api.depends('sale_order_ids.date_order')
    def _compute_last_sale_order(self):
        for rec in self:
            rec.last_sale_order = (
                max(
                    rec.sale_order_ids,
                    key=lambda so: so.date_order or so.create_date,
                    default=False,
                )
            )

    @api.depends(
        'sale_order_ids',
        'sale_order_ids.date_order',
        'sale_order_ids.picking_ids.state',
        'customer_source_id',
    )
    def _compute_customer_lifecycle_status(self):
        today = fields.Date.today()

        for rec in self:
            status = 'new'

            if not rec.sale_order_ids:
                rec.customer_lifecycle_status = status
                continue

            last_order = rec.sale_order_ids.sorted(
                key=lambda so: so.date_order or fields.Datetime.from_string('1970-01-01 00:00:00')
            )[-1]
            print(last_order,rec.name)

            days = 0
            if last_order.date_order:
                print(last_order.date_order)
                days = (today - last_order.date_order.date()).days

            deliveries = rec.sale_order_ids.mapped('picking_ids').filtered(
                lambda p: p.picking_type_code == 'outgoing'
            )
            done_deliveries = deliveries.filtered(lambda p: p.state == 'done')

            customer_source = rec.customer_source_id.name

            if days > 548:
                status = 'inactive'
            elif days > 301:
                status = 'dormant'
            elif days > 112:
                status = 'old_ftlt'
            elif days > 98:
                status = 'cancelled_ftlt'
            else:
                for delivery in deliveries:
                    if delivery.state == 'cancel':
                        status = 'cancelled_ftlt'
                        break
                    elif delivery.state == 'done':
                        if len(done_deliveries) == 1:
                            status = 'ftlt' if customer_source == 'Door Sales' else 'main_customer'
                        else:
                            status = 'main_customer'
                        break
            print(days,status,customer_source)
            rec.customer_lifecycle_status = status

    @api.model
    def cron_update_customer_lifecycle_status(self):
        partners = self.search([])
        partners._compute_customer_lifecycle_status()

    def action_close_account(self):
        return {
            'type': 'ir.actions.act_window',
            'name': 'Account Close Reason',
            'res_model': 'close.reason.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'active_model': 'res.partner',
                'active_ids': self.ids,
                'active_id': self.id if len(self) == 1 else False,
            },
        }

    def action_reopen_account(self):
        self.write({
            'is_closed': False,
            'closed_reason': "",
            'account_closed_date': False,
            'is_reopened': True,
            'account_reopen_date': fields.Datetime.now(),
        })
        self._compute_customer_lifecycle_status()

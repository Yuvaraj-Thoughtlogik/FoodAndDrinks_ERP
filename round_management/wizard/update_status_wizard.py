from odoo import models, fields, api, _
from odoo.exceptions import UserError


class UpdateStatusWizard(models.TransientModel):
    _name = 'update.status.wizard'
    _description = 'Bulk Update Batch Status'

    state = fields.Selection([
        ('pln', 'Planned'),
        ('act', 'Active'),
        ('prt', 'Printed'),
        ('com', 'Completed'),
        ('cancel', 'Cancelled'),
    ], string='Status')

    delivery_date = fields.Date(string='Delivery Date')

    iso_week_no = fields.Char(string='Week No')
    
    search_delivery_date = fields.Date(
    string="Delivery Date",
    default=fields.Date.context_today,
)

    search_reference = fields.Char(string="Reference")

    reference = fields.Char(string="New Reference")
    
    show_search_criteria = fields.Boolean(
    string="Enable Search Criteria",
    default=False
)

    @api.model
    def action_open_status_wizard(self):
        active_ids = self.env.context.get('active_ids', [])

        if not active_ids:
            raise UserError(_("Please select at least one batch."))

        return {
            'name': _('Bulk Update Status'),
            'type': 'ir.actions.act_window',
            'res_model': 'update.status.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': self.env.context,
        }

    def action_apply_status(self):
        self.ensure_one()

        active_ids = self.env.context.get('active_ids', [])
        batches = self.env['round.management.batch'].browse(active_ids)

        if not batches:
            raise UserError(_("Please select at least one batch."))

        # Apply search only if the checkbox is enabled
        if self.show_search_criteria:

            if self.search_delivery_date:
                batches = batches.filtered(
                    lambda b: b.delivery_date == self.search_delivery_date
                )

            if self.search_reference:
                batches = batches.filtered(
                    lambda b: self.search_reference.lower() in (b.reference or "").lower()
                )

            if not batches:
                raise UserError(_("No batches match the search criteria."))

        vals = {}

        if self.state:
            vals['state'] = self.state

        if self.delivery_date:
            vals['delivery_date'] = self.delivery_date

            iso_year, iso_week, weekday = self.delivery_date.isocalendar()
            vals['week_number'] = f"{iso_year}{str(iso_week).zfill(2)}"

        elif self.iso_week_no:
            vals['week_number'] = self.iso_week_no

        if self.reference:
            vals['reference'] = self.reference

        if vals:
            batches.write(vals)

        return {
            'type': 'ir.actions.client',
            'tag': 'reload',
        }

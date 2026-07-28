from odoo import models, fields, api, _
from odoo.exceptions import UserError


class RoundManagementBatch(models.Model):
    _inherit = 'round.management.batch'

    state = fields.Selection([
        ('pln', 'Planned'),
        ('act', 'Active'),
        ('prt', 'Printed'),
        ('com', 'Completed'),
        ('cancel', 'Cancelled'),
    ], string='Status', default='pln', required=True, tracking=True)

    iso_week_no = fields.Char(string='Week Nº')
    duplication_comments = fields.Text(string='Duplication Comments')
    warning = fields.Char(string='Warning')

    round_code = fields.Char(related='round_id.code', string='Round Code', readonly=True)
    round_name = fields.Char(related='round_id.name', string='Round Name', readonly=True)


class RoundBatchManager(models.TransientModel):
    _name = 'round.batch.manager'
    _description = 'Round Batch Manager Screen'

    # Search Header Criteria
    search_delivery_date = fields.Date(string='Delivery Date', default=fields.Date.context_today)
    search_reference = fields.Char(string='Reference')

    # Embedded Grid Lines
    line_ids = fields.One2many(
        'round.batch.manager.line', 
        'manager_id', 
        string='Batches'
    )

    # Bottom Update Controls
    target_status = fields.Selection([
        ('pln', 'Planned'),
        ('act', 'Active'),
        ('prt', 'Printed'),
        ('com', 'Completed'),
        ('cancel', 'Cancelled'),
    ], string='Status')
    target_delivery_date = fields.Date(string='Delivery Date')
    target_week_no = fields.Char(string='Week Nº')

    def action_search_batches(self):
        """Fetches matching records and populates grid lines."""
        self.ensure_one()
        self.line_ids.unlink()

        domain = []
        if self.search_delivery_date:
            domain.append(('delivery_date', '=', self.search_delivery_date))
        if self.search_reference:
            domain.append(('code', 'ilike', self.search_reference))

        batches = self.env['round.management.batch'].search(domain)

        lines = [(0, 0, {
            'batch_id': batch.id,
            'selected': False,
            'round_code': batch.round_code,
            'round_name': batch.round_name,
            'depot_name': batch.depot_id.name if hasattr(batch, 'depot_id') and batch.depot_id else '',
            'batch_code': batch.code,
            'iso_week_no': batch.iso_week_no,
            'delivery_date': batch.delivery_date,
            'state': batch.state,
            'duplication_comments': batch.duplication_comments,
            'warning': batch.warning,
        }) for batch in batches]

        self.write({'line_ids': lines})
        return self._reload_view()

    def action_select_all(self):
        self.ensure_one()
        self.line_ids.write({'selected': True})
        return self._reload_view()

    def action_deselect_all(self):
        self.ensure_one()
        self.line_ids.write({'selected': False})
        return self._reload_view()

    def action_validate_status_update(self):
        """Bulk updates state/delivery date/week number on selected lines."""
        self.ensure_one()
        selected_lines = self.line_ids.filtered(lambda l: l.selected)

        if not selected_lines:
            raise UserError(_("Please select at least one row from the grid to update."))

        vals = {}
        if self.target_status:
            vals['state'] = self.target_status
        if self.target_delivery_date:
            vals['delivery_date'] = self.target_delivery_date
        if self.target_week_no:
            vals['iso_week_no'] = self.target_week_no

        if vals:
            batches_to_update = selected_lines.mapped('batch_id')
            batches_to_update.write(vals)

        # Refresh grid
        return self.action_search_batches()

    def _reload_view(self):
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'round.batch.manager',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'inline',
        }


class RoundBatchManagerLine(models.TransientModel):
    _name = 'round.batch.manager.line'
    _description = 'Round Batch Manager Grid Line'

    manager_id = fields.Many2one('round.batch.manager', ondelete='cascade')
    batch_id = fields.Many2one('round.management.batch', string='Batch', required=True)

    selected = fields.Boolean(string='Selected', default=False)
    round_code = fields.Char(string='Round Code', readonly=True)
    round_name = fields.Char(string='Round Name', readonly=True)
    depot_name = fields.Char(string='Depot', readonly=True)
    batch_code = fields.Char(string='Batch Code', readonly=True)
    iso_week_no = fields.Char(string='Week Nº', readonly=True)
    delivery_date = fields.Date(string='Delivery Date', readonly=True)
    state = fields.Selection([
        ('pln', 'Planned'),
        ('act', 'Active'),
        ('prt', 'Printed'),
        ('com', 'Completed'),
        ('cancel', 'Cancelled'),
    ], string='Status', readonly=True)
    duplication_comments = fields.Text(string='Duplication Comments', readonly=True)
    warning = fields.Char(string='Warning', readonly=True)

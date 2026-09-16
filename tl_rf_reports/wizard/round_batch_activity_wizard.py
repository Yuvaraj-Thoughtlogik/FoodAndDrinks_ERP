# -*- coding: utf-8 -*-
from datetime import timedelta

from odoo import api, fields, models, _
from odoo.exceptions import UserError


class RoundBatchActivityWizard(models.TransientModel):
    _name = 'round.batch.activity.wizard'
    _description = 'Round Batch Activity Report Wizard'

    report_type = fields.Selection(
        selection=[
            ('no_batch', 'Rounds Without Batches in Last 8 Weeks'),
            ('no_planned_batch', 'Rounds Without Planned Batches in Last 8 Weeks'),
        ],
        string='Option',
    )

    def action_view_lines(self):
        """Opens the Round list view filtered to Rounds that have no matching
        Batch (any state, or only Planned ones depending on the selected
        option) with a delivery_date in the last 8 weeks."""
        self.ensure_one()
        if not self.report_type:
            raise UserError(_("Please select an option before clicking View Lines."))

        date_to = fields.Date.context_today(self)
        date_from = date_to - timedelta(weeks=8)

        batch_domain = [
            ('delivery_date', '>=', date_from),
            ('delivery_date', '<=', date_to),
        ]
        if self.report_type == 'no_planned_batch':
            batch_domain.append(('state', '=', 'pln'))

        active_round_ids = self.env['round.management.batch'].search(batch_domain).mapped('round_id').ids

        if self.report_type == 'no_planned_batch':
            name = _('Rounds Without Planned Batches in Last 8 Weeks')
        else:
            name = _('Rounds Without Batches in Last 8 Weeks')

        return {
            'name': name,
            'type': 'ir.actions.act_window',
            'res_model': 'round.management.round',
            'view_mode': 'list,form',
            'views': [
                (self.env.ref('round_management.view_round_tree').id, 'list'),
                (self.env.ref('round_management.view_round_form').id, 'form'),
            ],
            'search_view_id': [self.env.ref('round_management.view_round_management_round_search').id, 'search'],
            'domain': [('id', 'not in', active_round_ids)],
        }

# -*- coding: utf-8 -*-
from datetime import timedelta
from odoo import api, fields, models, _


class ReportActiveBatch(models.AbstractModel):
    _name = 'report.tl_rf_reports.report_active_batch'
    _description = 'Active Batch Report Generator'

    @api.model
    def _get_report_values(self, docids, data=None):
        docs = self.env['active.batch.report.wizard'].browse(docids)
        today = fields.Date.context_today(self)
        today_str = today.strftime('%d/%m/%Y')

        reports_data = []
        for wizard in docs:
            weeks = wizard.weeks if (wizard.weeks and wizard.weeks > 0) else 8
            from_date = today - timedelta(weeks=weeks)
            to_date = today + timedelta(weeks=weeks)

            from_date_str = from_date.strftime('%d/%m/%Y')
            to_date_str = to_date.strftime('%d/%m/%Y')
            before_end_date = today - timedelta(days=1)
            before_end_str = before_end_date.strftime('%d/%m/%Y')
            after_start_date = today + timedelta(days=1)
            after_start_str = after_start_date.strftime('%d/%m/%Y')

            # Determine rounds to include (selected rounds or all active rounds)
            if wizard.round_ids:
                rounds = wizard.round_ids.sorted(lambda r: (r.code or '', r.name or ''))
            else:
                rounds = self.env['round.management.round'].search([('state', '=', 'active')], order='code asc, name asc')

            round_items = []
            for round_rec in rounds:
                batch_domain = [
                    ('round_id', '=', round_rec.id),
                    ('state', '=', 'act'),
                    ('delivery_date', '>=', from_date),
                    ('delivery_date', '<=', to_date),
                ]
                batches = self.env['round.management.batch'].search(batch_domain, order='delivery_date asc, code asc')

                before_batches = []
                today_batches = []
                after_batches = []

                for batch in batches:
                    delivery_date = batch.delivery_date
                    if not delivery_date:
                        continue

                    batch_name = batch.display_name or batch.reference or batch.code or ''

                    if delivery_date < today:
                        days = (today - delivery_date).days
                        # Negative sign for before batch age
                        batch_age = f"{days} {'day' if days == 1 else 'days'}"
                        before_batches.append({
                            'code': batch.code or '',
                            'name': batch_name,
                            'delivery_date': delivery_date.strftime('%d/%m/%Y'),
                            'batch_age': batch_age,
                        })
                    elif delivery_date == today:
                        today_batches.append({
                            'code': batch.code or '',
                            'name': batch_name,
                            'delivery_date': delivery_date.strftime('%d/%m/%Y'),
                            'batch_age': "0 days",
                        })
                    else:
                        future_days = (delivery_date - today).days
                        batch_age = f"{future_days} {'day' if future_days == 1 else 'days'} (future date)"
                        after_batches.append({
                            'code': batch.code or '',
                            'name': batch_name,
                            'delivery_date': delivery_date.strftime('%d/%m/%Y'),
                            'batch_age': batch_age,
                        })

                round_name_display = f"{round_rec.code} - {round_rec.name}" if round_rec.code else round_rec.name

                round_items.append({
                    'round_id': round_rec.id,
                    'round_name': round_rec.name or '',
                    'round_code': round_rec.code or '',
                    'round_display': round_name_display,
                    'before_batches': before_batches,
                    'today_batches': today_batches,
                    'after_batches': after_batches,
                    'has_batches': bool(before_batches or today_batches or after_batches),
                })

            current_dt = fields.Datetime.context_timestamp(self, fields.Datetime.now())
            printed_at_str = current_dt.strftime('%d/%m/%Y %H:%M:%S')

            reports_data.append({
                'wizard': wizard,
                'weeks': weeks,
                'as_on_date': today_str,
                'from_date_str': from_date_str,
                'to_date_str': to_date_str,
                'before_range_str': f"{from_date_str} → {before_end_str}",
                'today_str': today_str,
                'after_range_str': f"{after_start_str} → {to_date_str}",
                'round_items': round_items,
                'printed_at': printed_at_str,
                'has_any_batches': any(r['has_batches'] for r in round_items),
            })

        return {
            'doc_ids': docids,
            'doc_model': 'active.batch.report.wizard',
            'docs': docs,
            'reports_data': reports_data,
        }

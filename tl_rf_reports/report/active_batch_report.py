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

            params = {
                'from_date': from_date,
                'to_date': to_date,
            }
            if wizard.round_ids:
                round_filter = "r.id IN %(round_ids)s"
                params['round_ids'] = tuple(wizard.round_ids.ids)
            else:
                round_filter = "r.state = 'active'"

            query = f"""
                SELECT 
                    r.id AS round_id,
                    r.name AS round_name,
                    r.code AS round_code,
                    b.id AS batch_id,
                    b.code AS batch_code,
                    b.reference AS batch_reference,
                    b.delivery_date AS batch_delivery_date
                FROM round_management_round r
                LEFT JOIN round_management_batch b ON b.round_id = r.id 
                    AND b.state = 'act' 
                    AND b.delivery_date >= %(from_date)s 
                    AND b.delivery_date <= %(to_date)s
                WHERE {round_filter}
                ORDER BY r.code ASC, r.name ASC, b.delivery_date ASC, b.code ASC
            """
            self.env.cr.execute(query, params)
            rows = self.env.cr.dictfetchall()

            rounds_map = {}
            for r in rows:
                rid = r['round_id']
                if rid not in rounds_map:
                    r_code = r['round_code'] or ''
                    r_name = r['round_name'] or ''
                    r_display = f"{r_code} - {r_name}" if r_code else r_name
                    rounds_map[rid] = {
                        'round_id': rid,
                        'round_name': r_name,
                        'round_code': r_code,
                        'round_display': r_display,
                        'before_batches': [],
                        'today_batches': [],
                        'after_batches': [],
                        'has_batches': False,
                    }

                if r['batch_id'] and r['batch_delivery_date']:
                    r_item = rounds_map[rid]
                    r_item['has_batches'] = True
                    delivery_date = r['batch_delivery_date']
                    batch_code = r['batch_code'] or ''
                    batch_ref = r['batch_reference'] or ''
                    batch_name = batch_ref or batch_code

                    if delivery_date < today:
                        days = (today - delivery_date).days
                        batch_age = f"{days} {'day' if days == 1 else 'days'}"
                        r_item['before_batches'].append({
                            'code': batch_code,
                            'name': batch_name,
                            'delivery_date': delivery_date.strftime('%d/%m/%Y'),
                            'batch_age': batch_age,
                        })
                    elif delivery_date == today:
                        r_item['today_batches'].append({
                            'code': batch_code,
                            'name': batch_name,
                            'delivery_date': delivery_date.strftime('%d/%m/%Y'),
                            'batch_age': "0 days",
                        })
                    else:
                        future_days = (delivery_date - today).days
                        batch_age = f"{future_days} {'day' if future_days == 1 else 'days'} (future date)"
                        r_item['after_batches'].append({
                            'code': batch_code,
                            'name': batch_name,
                            'delivery_date': delivery_date.strftime('%d/%m/%Y'),
                            'batch_age': batch_age,
                        })

            round_items = list(rounds_map.values())
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

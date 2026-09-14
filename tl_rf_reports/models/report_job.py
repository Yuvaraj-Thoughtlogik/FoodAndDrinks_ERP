# -*- coding: utf-8 -*-
import base64
import logging
import threading
import time as time_module

from odoo import _, api, fields, models
from odoo.tools.safe_eval import safe_eval

_logger = logging.getLogger(__name__)


class ReportGenerationJob(models.Model):
    """Tracks a PDF report that is rendered in a background thread instead of
    blocking the HTTP request that asked for it.

    Some of the reports in this module (Delivery Note Round, Packing List) can
    involve thousands of sale orders. Rendering that many wkhtmltopdf pages
    synchronously inside the request that triggered the print button can take
    well over ten minutes and eventually times out, leaving the user with
    nothing. Past a configurable record-count threshold we instead: create one
    of these job records, hand the actual rendering to a background thread
    (its own cursor/env, same pattern already used for the parallel wkhtmltopdf
    workers in ir_actions_report.py), and let the user carry on working. The
    thread attaches the finished PDF and pushes a bus notification so the
    browser can offer it for download - the same way a browser's own download
    manager works.
    """
    _name = 'tl.report.generation.job'
    _description = 'Background Report Generation Job'
    _inherit = ['bus.listener.mixin']
    _order = 'create_date desc'

    name = fields.Char(required=True)
    user_id = fields.Many2one('res.users', required=True, index=True, default=lambda self: self.env.user)
    report_xmlid = fields.Char(required=True)
    state = fields.Selection([
        ('queued', 'Queued'),
        ('processing', 'Processing'),
        ('done', 'Ready'),
        ('failed', 'Failed'),
    ], default='queued', required=True)
    record_count = fields.Integer(string='Records')
    attachment_id = fields.Many2one('ir.attachment', readonly=True)
    error_message = fields.Text(readonly=True)

    def _bus_channel(self):
        return self.user_id.partner_id

    @api.model
    def _get_async_threshold(self):
        """Record count above which a report is generated in the background
        instead of inline. Small/normal-sized prints stay instant."""
        try:
            param = self.env['ir.config_parameter'].sudo().get_param('tl_rf_reports.async_report_threshold')
            if param:
                return max(1, int(param))
        except (ValueError, TypeError):
            pass
        return 150

    @api.model
    def dispatch_report(self, wizard, report_xmlid, wizard_vals, display_name, record_count):
        """Either render `report_xmlid` for `wizard` right away (small jobs), or
        queue it as a background job and return a notification telling the
        user it is on its way. Wizards should call this instead of
        `report_action()` directly."""
        if record_count <= self._get_async_threshold():
            return self.env.ref(report_xmlid).report_action(wizard)

        self._enqueue(report_xmlid, wizard._name, wizard_vals, display_name, record_count)
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Generating "%s"') % display_name,
                'message': _(
                    'Printing %(count)s records at once takes a while, so this report is being '
                    'generated in the background. You will get a notification with a Download '
                    'button as soon as it is ready - check Reporting > My Report Jobs if you miss it.'
                ) % {'count': record_count},
                'type': 'info',
                'sticky': True,
            },
        }

    def _enqueue(self, report_xmlid, wizard_model, wizard_vals, display_name, record_count):
        job = self.sudo().create({
            'name': display_name,
            'user_id': self.env.uid,
            'report_xmlid': report_xmlid,
            'record_count': record_count,
            'state': 'queued',
        })

        registry = self.env.registry
        uid = self.env.uid
        context = dict(self.env.context)
        job_id = job.id

        def _run():
            with registry.cursor() as cr:
                env = api.Environment(cr, uid, context)
                env['tl.report.generation.job'].browse(job_id)._render(wizard_model, wizard_vals)

        threading.Thread(target=_run, daemon=True).start()
        return job

    def _render(self, wizard_model, wizard_vals):
        """Runs in the background thread as the requesting user - sudo() is used
        for the job's own bookkeeping writes so a regular user (who only has
        read/unlink access to this model, see ir.model.access.csv) can still
        have their job progress recorded; the report itself still renders
        under the requesting user's own access rights."""
        self.ensure_one()
        self.sudo().write({'state': 'processing'})
        self.env.cr.commit()
        try:
            wizard = self.env[wizard_model].create(wizard_vals)
            report = self.env.ref(self.report_xmlid)
            pdf_content, _report_type = report.with_context(
                force_report_rendering=True
            )._render_qweb_pdf(self.report_xmlid, res_ids=wizard.ids)

            attachment = self.env['ir.attachment'].sudo().create({
                'name': self._compute_filename(report, wizard),
                'type': 'binary',
                'datas': base64.b64encode(pdf_content),
                'res_model': self._name,
                'res_id': self.id,
                'mimetype': 'application/pdf',
            })
            self.sudo().write({'state': 'done', 'attachment_id': attachment.id})
            self.env.cr.commit()
        except Exception as exc:  # noqa: BLE001 - a bad job must not kill the thread silently
            self.env.cr.rollback()
            _logger.exception(
                "Background report generation failed for job %s (%s)", self.id, self.report_xmlid
            )
            self.sudo().write({'state': 'failed', 'error_message': str(exc)})
            self.env.cr.commit()
        self._notify()

    def _compute_filename(self, report, wizard):
        filename = report.name or self.name
        if report.print_report_name:
            try:
                filename = safe_eval(report.print_report_name, {'object': wizard, 'time': time_module})
            except Exception:  # noqa: BLE001 - a bad filename expression must not fail the print
                pass
        return f"{filename}.pdf"

    def _notify(self):
        self.ensure_one()
        self._bus_send('tl_rf_reports.report_job_update', {
            'job_id': self.id,
            'name': self.name,
            'state': self.state,
            'attachment_id': self.attachment_id.id if self.attachment_id else False,
            'error_message': self.error_message or False,
        })

    def action_download(self):
        self.ensure_one()
        if not self.attachment_id:
            return False
        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{self.attachment_id.id}?download=true',
            'target': 'self',
        }

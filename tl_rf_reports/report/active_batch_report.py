# -*- coding: utf-8 -*-
import io
from collections import defaultdict
from datetime import timedelta
from xml.sax.saxutils import escape as xml_escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from odoo import api, fields, models, _


# ----------------------------------------------------------------------
# ReportLab styles + layout helpers for the fast (non-QWeb) PDF path.
#
# These are deliberately plain functions operating on plain dicts (the same
# shape produced by _get_report_values()'s reports_data entries / round_items,
# not recordsets) so the layout itself can be unit-exercised with hand-built
# fake data, independent of any Odoo env/database. generate_pdf() below is
# the only piece that touches self.env - it fetches the data, then hands it
# to build_active_batch_story().
# ----------------------------------------------------------------------
_COMPANY_STYLE = ParagraphStyle(
    'ABCompany', fontName='Helvetica-Bold', fontSize=20, leading=23,
    textColor=colors.HexColor('#004080'),
)
_TITLE_STYLE = ParagraphStyle(
    'ABTitle', fontName='Helvetica-Bold', fontSize=15, leading=18,
    textColor=colors.HexColor('#222222'), spaceBefore=3,
)
_INFO_STYLE = ParagraphStyle(
    'ABInfo', fontName='Helvetica', fontSize=9, leading=13,
    textColor=colors.HexColor('#333333'), alignment=2,
)
_ROUND_LABEL_STYLE = ParagraphStyle(
    'ABRoundLabel', fontName='Helvetica-Bold', fontSize=12, leading=15,
    textColor=colors.HexColor('#004080'),
)
_ROUND_NOBATCH_STYLE = ParagraphStyle(
    'ABRoundNoBatch', fontName='Helvetica-Oblique', fontSize=9, leading=12,
    textColor=colors.HexColor('#777777'),
)
_SECTION_TITLE_STYLE = ParagraphStyle(
    'ABSectionTitle', fontName='Helvetica-Bold', fontSize=11, leading=14,
    textColor=colors.HexColor('#004080'),
)
_TH_STYLE = ParagraphStyle(
    'ABTableHeader', fontName='Helvetica-Bold', fontSize=8.5, leading=11,
    textColor=colors.HexColor('#333333'),
)
_TH_CENTER_STYLE = ParagraphStyle('ABTableHeaderCenter', parent=_TH_STYLE, alignment=1)
_TH_RIGHT_STYLE = ParagraphStyle('ABTableHeaderRight', parent=_TH_STYLE, alignment=2)
_TD_STYLE = ParagraphStyle(
    'ABTableCell', fontName='Helvetica', fontSize=8.5, leading=11,
    textColor=colors.HexColor('#111111'),
)
_TD_BOLD_STYLE = ParagraphStyle(
    'ABTableCellBold', fontName='Helvetica-Bold', fontSize=8.5, leading=11,
    textColor=colors.HexColor('#111111'),
)
_TD_CENTER_STYLE = ParagraphStyle('ABTableCellCenter', parent=_TD_STYLE, alignment=1)
_TD_AGE_STYLE = ParagraphStyle(
    'ABTableCellAge', fontName='Helvetica', fontSize=8.5, leading=11,
    textColor=colors.HexColor('#444444'), alignment=2,
)
_EMPTY_GLOBAL_STYLE = ParagraphStyle(
    'ABEmptyGlobal', fontName='Helvetica', fontSize=10.5, leading=14,
    textColor=colors.HexColor('#666666'), alignment=1,
)

_BATCH_TABLE_HEADER = ("Batch Code", "Batch Name", "Delivery Date", "Batch Age")
_BATCH_COL_WIDTHS_FRACTIONS = (0.20, 0.44, 0.18, 0.18)


def _batch_section_flowables(title, range_str, batches, printable_width):
    """One Before/Today/After section: a title line (with its date range/label
    in parentheses) followed by the 4-column batch table. Mirrors the "Before/
    Today/After" <div> blocks in active_batch_report_views.xml."""
    col_widths = [printable_width * f for f in _BATCH_COL_WIDTHS_FRACTIONS]

    rows = [[
        Paragraph(_BATCH_TABLE_HEADER[0], _TH_STYLE),
        Paragraph(_BATCH_TABLE_HEADER[1], _TH_STYLE),
        Paragraph(_BATCH_TABLE_HEADER[2], _TH_CENTER_STYLE),
        Paragraph(_BATCH_TABLE_HEADER[3], _TH_RIGHT_STYLE),
    ]]
    for b in batches:
        rows.append([
            Paragraph(xml_escape(str(b.get('code') or '')), _TD_BOLD_STYLE),
            Paragraph(xml_escape(str(b.get('name') or '')), _TD_STYLE),
            Paragraph(xml_escape(str(b.get('delivery_date') or '')), _TD_CENTER_STYLE),
            Paragraph(xml_escape(str(b.get('batch_age') or '')), _TD_AGE_STYLE),
        ])

    table = Table(rows, colWidths=col_widths, repeatRows=1)
    table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('LINEBELOW', (0, 0), (-1, 0), 0.75, colors.HexColor('#dddddd')),
    ]))

    return [
        Paragraph(
            f'{xml_escape(title)} '
            f'<font size="9" color="#555555">({xml_escape(range_str)})</font>',
            _SECTION_TITLE_STYLE,
        ),
        Spacer(1, 1.5 * mm),
        table,
        Spacer(1, 4 * mm),
    ]


def _round_item_flowables(r_item, before_range_str, today_str, after_range_str, printable_width):
    """One round's whole block: the blue round banner, then either a "No
    active batches found." notice or the Before/Today/After sections that
    actually have rows. Wrapped in KeepTogether by the caller, same as the
    QWeb template's `page-break-inside: avoid` on the round <div>."""
    round_display = r_item.get('round_display') or r_item.get('round_name') or ''

    banner = Table(
        [[Paragraph(
            f'<font color="#004080">Round: </font>'
            f'<font color="#111111">{xml_escape(round_display)}</font>',
            _ROUND_LABEL_STYLE,
        )]],
        colWidths=[printable_width],
    )
    banner.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#f0f4f8')),
        ('LINEBEFORE', (0, 0), (0, 0), 3, colors.HexColor('#004080')),
        ('LEFTPADDING', (0, 0), (-1, -1), 10),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
    ]))

    flowables = [banner, Spacer(1, 3 * mm)]

    if not r_item.get('has_batches'):
        flowables.append(Paragraph("No active batches found.", _ROUND_NOBATCH_STYLE))
        flowables.append(Spacer(1, 5 * mm))
        return flowables

    if r_item.get('before_batches'):
        flowables += _batch_section_flowables(
            "Before", before_range_str, r_item['before_batches'], printable_width)
    if r_item.get('today_batches'):
        flowables += _batch_section_flowables(
            "Today", today_str, r_item['today_batches'], printable_width)
    if r_item.get('after_batches'):
        flowables += _batch_section_flowables(
            "After", after_range_str, r_item['after_batches'], printable_width)

    return flowables


def build_active_batch_story(report_data, printable_width):
    """Pure layout function: given a dict shaped like one reports_data[i]
    entry from _get_report_values() (keys: weeks, as_on_date, from_date_str,
    to_date_str, before_range_str, today_str, after_range_str, round_items),
    returns the list of flowables for the report body. The static
    "Printed on ..." footer is drawn straight on the canvas by generate_pdf()
    instead, since (unlike the courier/van reports) this report never needs
    a "Page X of Y" - the old QWeb footer didn't show one either."""
    story = []

    header_table = Table(
        [[
            [Paragraph("Regal Fish", _COMPANY_STYLE), Paragraph("Active Batch Report", _TITLE_STYLE)],
            Paragraph(
                f"<b>As On Date:</b> {xml_escape(str(report_data.get('as_on_date') or ''))}<br/>"
                f"<b>Within Weeks:</b> {xml_escape(str(report_data.get('weeks') or ''))} Weeks<br/>"
                f"<b>Date Range:</b> {xml_escape(str(report_data.get('from_date_str') or ''))} "
                f"&#8594; {xml_escape(str(report_data.get('to_date_str') or ''))}",
                _INFO_STYLE,
            ),
        ]],
        colWidths=[printable_width * 0.5, printable_width * 0.5],
    )
    header_table.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP')]))
    story.append(header_table)
    story.append(Spacer(1, 3 * mm))

    rule = Table([['']], colWidths=[printable_width])
    rule.setStyle(TableStyle([('LINEBELOW', (0, 0), (-1, 0), 1.5, colors.HexColor('#004080'))]))
    story.append(rule)
    story.append(Spacer(1, 6 * mm))

    round_items = report_data.get('round_items') or []
    if not round_items:
        story.append(Paragraph("No active batches found for the selected period.", _EMPTY_GLOBAL_STYLE))
        return story

    before_range_str = report_data.get('before_range_str') or ''
    today_str = report_data.get('today_str') or ''
    after_range_str = report_data.get('after_range_str') or ''

    for r_item in round_items:
        story.append(KeepTogether(_round_item_flowables(
            r_item, before_range_str, today_str, after_range_str, printable_width,
        )))

    return story


class ReportActiveBatch(models.AbstractModel):
    _name = 'report.tl_rf_reports.report_active_batch'
    _description = 'Active Batch Report Generator'

    # ------------------------------------------------------------------
    # QWeb / wkhtmltopdf path - kept registered (see active_batch_report_
    # views.xml) but no longer used by the Print button. Left in place only
    # in case anything still calls the report action directly. See
    # generate_pdf() below for the ReportLab fast path used by
    # active.batch.report.wizard.action_print_report().
    # ------------------------------------------------------------------
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

    # ------------------------------------------------------------------
    # Fast path: builds the PDF directly with ReportLab, in one pass, in
    # memory. No wkhtmltopdf subprocess, no per-page HTML rendering. This
    # report is small and bounded (a handful of rounds x a handful of weeks
    # either side of today), so unlike the courier/van reports it doesn't
    # need a two-pass canvas or any pagination trickery - a single flowing
    # SimpleDocTemplate document is enough, and the one piece of per-page
    # chrome the old QWeb template had (a static "Printed on ..." footer,
    # no page numbers) is drawn directly via onFirstPage/onLaterPages.
    # ------------------------------------------------------------------
    def generate_pdf(self, wizard):
        """Returns the finished PDF (bytes) for one Active Batch Report
        wizard. Unlike the courier/van reports this one always has at least
        a header and a body (even an empty result set still renders a "No
        active batches found for the selected period." page, same as the
        QWeb template did), so this never returns None."""
        today = fields.Date.context_today(self)
        today_str = today.strftime('%d/%m/%Y')

        weeks = wizard.weeks if (wizard.weeks and wizard.weeks > 0) else 8
        from_date = today - timedelta(weeks=weeks)
        to_date = today + timedelta(weeks=weeks)

        from_date_str = from_date.strftime('%d/%m/%Y')
        to_date_str = to_date.strftime('%d/%m/%Y')
        before_end_date = today - timedelta(days=1)
        before_end_str = before_end_date.strftime('%d/%m/%Y')
        after_start_date = today + timedelta(days=1)
        after_start_str = after_start_date.strftime('%d/%m/%Y')

        if wizard.round_ids:
            round_domain = [('id', 'in', wizard.round_ids.ids)]
        else:
            round_domain = [('state', '=', 'active')]

        # Plain ORM search()+loop instead of raw SQL - the ORM already knows
        # how each field (round/batch name, code, etc.) is actually stored,
        # so there's no risk of the "assumed jsonb, column is actually
        # varchar" class of bug a hand-written query can hit.
        rounds = self.env['round.management.round'].search(round_domain, order='code asc, name asc')

        # Batch pre-fetch all matching batches for all rounds in one query
        # (instead of one query per round) to avoid N+1 SQL queries. Already
        # ordered delivery_date asc, code asc so grouping below preserves
        # that relative order within each round/bucket.
        all_batches = self.env['round.management.batch'].search([
            ('round_id', 'in', rounds.ids),
            ('state', '=', 'act'),
            ('delivery_date', '>=', from_date),
            ('delivery_date', '<=', to_date),
        ], order='delivery_date asc, code asc')

        batches_by_round = defaultdict(list)
        for batch in all_batches:
            batches_by_round[batch.round_id.id].append(batch)

        rounds_map = {}
        for round_rec in rounds:
            r_code = round_rec.code or ''
            r_name = round_rec.name or ''
            r_display = f"{r_code} - {r_name}" if r_code else r_name
            r_item = {
                'round_id': round_rec.id,
                'round_name': r_name,
                'round_code': r_code,
                'round_display': r_display,
                'before_batches': [],
                'today_batches': [],
                'after_batches': [],
                'has_batches': False,
            }
            rounds_map[round_rec.id] = r_item

            for batch in batches_by_round.get(round_rec.id, []):
                r_item['has_batches'] = True
                delivery_date = batch.delivery_date
                batch_code = batch.code or ''
                batch_ref = batch.reference or ''
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
        printed_at_local = fields.Datetime.context_timestamp(self, fields.Datetime.now())
        printed_at_str = printed_at_local.strftime('%d/%m/%Y %H:%M:%S')

        report_data = {
            'weeks': weeks,
            'as_on_date': today_str,
            'from_date_str': from_date_str,
            'to_date_str': to_date_str,
            'before_range_str': f"{from_date_str} → {before_end_str}",
            'today_str': today_str,
            'after_range_str': f"{after_start_str} → {to_date_str}",
            'round_items': round_items,
        }

        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer, pagesize=A4,
            leftMargin=12 * mm, rightMargin=12 * mm, topMargin=12 * mm, bottomMargin=15 * mm,
        )
        printable_width = A4[0] - (24 * mm)
        story = build_active_batch_story(report_data, printable_width)

        def _draw_footer(canv, _doc):
            canv.saveState()
            canv.setFont('Helvetica', 8)
            canv.setFillColor(colors.HexColor('#666666'))
            canv.drawString(12 * mm, 8 * mm, f"Printed on {printed_at_str}")
            canv.restoreState()

        doc.build(story, onFirstPage=_draw_footer, onLaterPages=_draw_footer)
        pdf_value = buffer.getvalue()
        buffer.close()
        return pdf_value

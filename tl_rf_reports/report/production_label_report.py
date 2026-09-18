# -*- coding: utf-8 -*-
import base64
import io
from xml.sax.saxutils import escape as xml_escape

from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.graphics.barcode import code128
from reportlab.graphics.shapes import Circle, Drawing, String
from reportlab.platypus import (
    Image, Paragraph, PageBreak, SimpleDocTemplate, Spacer, Table, TableStyle,
)

from odoo import models


from odoo.tools.image import image_data_uri

# Fixed physical label size - see paperformat_production_label in
# production_label_report_views.xml (100mm x 130mm, zero margins on the
# QWeb paperformat; the QWeb template itself then applies its own 2mm/3mm
# inner padding, which LABEL_MARGIN below approximates).
PAGE_WIDTH = 100 * mm
PAGE_HEIGHT = 130 * mm
LABEL_MARGIN = 3 * mm
PRINTABLE_WIDTH = PAGE_WIDTH - (2 * LABEL_MARGIN)
LOGO_MAX_WIDTH = 32 * mm
LOGO_MAX_HEIGHT = 20 * mm


class ProductionLabelReport(models.AbstractModel):
    _name = 'report.tl_rf_reports.report_production_label_document_courier'
    _description = 'Production Label Report Data - Courier'

    # ------------------------------------------------------------------
    # QWeb / wkhtmltopdf path - kept registered (see production_label_
    # report_views.xml) but no longer used by the Print Label button. See
    # generate_pdf() below, used instead by production.report.wizard.
    # action_print_label().
    # ------------------------------------------------------------------
    def _get_report_values(self, docids, data=None):
        wizard_model = self.env['production.report.wizard']
        docs = wizard_model.browse(docids)

        label_lines = []
        if docs:
            label_lines = docs[0]._get_label_data()

        company = self.env.company
        company_logo_uri = image_data_uri(company.logo) if company.logo else False

        return {
            'doc_ids': docids,
            'doc_model': 'production.report.wizard',
            'docs': docs,
            'label_lines': label_lines,
            'total_labels': len(label_lines),
            'company': company,
            'company_logo_uri': company_logo_uri,
        }

    # ------------------------------------------------------------------
    # Fast path: builds the PDF directly with ReportLab, in one pass, in
    # memory. No wkhtmltopdf subprocess, no per-page HTML rendering - just
    # native PDF drawing. One physical label per page at the fixed 100mm x
    # 130mm size. Shared by both the Courier and Regal Van variants: the
    # Regal Van AbstractModel below inherits this method unchanged and it
    # branches on self._name to reproduce each QWeb template's own field
    # order/layout (see _label_flowables()).
    # ------------------------------------------------------------------
    def _label_logo_flowable(self, company):
        if not company.logo:
            return None
        try:
            img = Image(io.BytesIO(base64.b64decode(company.logo)))
            aspect = img.imageWidth / float(img.imageHeight)
            if LOGO_MAX_WIDTH / aspect <= LOGO_MAX_HEIGHT:
                img.drawWidth = LOGO_MAX_WIDTH
                img.drawHeight = LOGO_MAX_WIDTH / aspect
            else:
                img.drawHeight = LOGO_MAX_HEIGHT
                img.drawWidth = LOGO_MAX_HEIGHT * aspect
            return img
        except Exception:  # noqa: BLE001 - a bad logo must not break the print
            return None

    def _label_circle_flowable(self):
        """Approximates the QWeb bottom-left round "GB / GG476" health mark stamp
        (border-radius:50% circle with two centered text lines)."""
        size = 16 * mm
        d = Drawing(size, 12 * mm)
        d.add(Circle(size / 2, 6 * mm, 6 * mm, strokeWidth=1.1, strokeColor=colors.black, fillColor=None))
        d.add(String(size / 2, 7.4 * mm, "GB", fontName='Helvetica-Bold', fontSize=7, textAnchor='middle'))
        d.add(String(size / 2, 4.2 * mm, "GG476", fontName='Helvetica-Bold', fontSize=7, textAnchor='middle'))
        return d

    def _label_barcode_flowable(self, barcode_value):
        if not barcode_value:
            return None
        try:
            bc = code128.Code128(
                str(barcode_value), barHeight=11 * mm, barWidth=0.32 * mm, humanReadable=True,
            )
            # NOTE: In the installed ReportLab version, Code128 is already a
            # Platypus Flowable (not a graphics Shape/Widget), so it can be
            # placed directly into the story. Wrapping it in a
            # graphics.shapes.Drawing via Drawing.add(bc, x, y) - as this used
            # to do - raises "Group.add() takes from 2 to 3 positional
            # arguments but 4 were given" (Drawing.add() only accepts a node
            # and an optional name, not x/y coordinates), and since that call
            # was inside this method's try/except, the error was silently
            # swallowed and the barcode was always dropped. Returning the
            # Code128 flowable directly avoids that broken wrapping and
            # renders the barcode again.
            bc.hAlign = 'CENTER'
            return bc
        except Exception:  # noqa: BLE001 - a bad/invalid barcode value must not break the print
            return None

    def _label_styles(self):
        base, bold = 'Helvetica', 'Helvetica-Bold'
        return {
            'header_c': ParagraphStyle('LabelHeaderC', fontName=bold, fontSize=10.5, leading=13, alignment=1),
            'header_l': ParagraphStyle('LabelHeaderL', fontName=bold, fontSize=10.5, leading=13, alignment=0),
            'small_r': ParagraphStyle('LabelSmallR', fontName=base, fontSize=8, leading=10, alignment=2),
            'product': ParagraphStyle('LabelProduct', fontName=bold, fontSize=15, leading=17, alignment=1),
            'info_c': ParagraphStyle('LabelInfoC', fontName=base, fontSize=8, leading=10, alignment=1),
            'info_l': ParagraphStyle('LabelInfoL', fontName=base, fontSize=11, leading=13, alignment=0),
            'useby': ParagraphStyle('LabelUseBy', fontName=bold, fontSize=9.5, leading=12, alignment=1),
            'section_title': ParagraphStyle('LabelSectionTitle', fontName=bold, fontSize=9.5, leading=12, alignment=1),
            'section_body': ParagraphStyle('LabelSectionBody', fontName=base, fontSize=8.5, leading=10.5, alignment=4),
            'pagecount': ParagraphStyle('LabelPageCount', fontName=bold, fontSize=8, leading=10, alignment=2),
        }

    def _label_flowables(self, label, index, total_labels, logo_flowable, is_van, styles):
        """Builds the flowables for one label page. Mirrors the field order/
        layout of report_production_label_document_courier vs. ..._regal_van
        in production_label_report_views.xml - the two QWeb templates differ
        in more than just data: header alignment (centered vs left), which
        fields appear in the header block and in what order, and the
        traceability line appears once for courier (near the top) but twice
        for van (a "Delivery on" line near the top, plus a separate
        "Traceability" line lower down, in a different size/alignment)."""
        customer_name = xml_escape(label.get('customer_name') or '')
        customer_code = xml_escape(label.get('customer_code') or '')
        round_name = xml_escape(label.get('round_name') or '')
        batch_code = xml_escape(label.get('batch_code') or '')
        category_name = xml_escape((label.get('category_name') or '').upper())
        warehouse_name = xml_escape(label.get('warehouse_name') or '')
        product_name = xml_escape(label.get('product_name') or '')
        origin_country = xml_escape(label.get('origin_country') or '')
        delivery_date_display = xml_escape(label.get('delivery_date_display') or '')
        delivery_day_display = xml_escape(label.get('delivery_day_display') or '')
        use_by_display = xml_escape(label.get('use_by_display') or '')

        if is_van:
            header_lines = [
                f"<font size=14>({batch_code})</font>",
                f"<font size=10.5>{customer_name}</font>",
                f"<font size=10.5>{round_name}</font>",
                f"<font size=10.5>{category_name}</font>",
            ]
        else:
            header_lines = [
                f"<font size=10.5>{customer_name} ({customer_code})</font>",
                f"<font size=10.5>{delivery_date_display}</font>",
                f"<font size=14>({batch_code})</font>",
                f"<font size=10.5>{category_name}</font>",
            ]
        header_para = Paragraph("<br/>".join(header_lines), styles['header_l'] if is_van else styles['header_c'])

        header_table = Table(
            [[header_para, logo_flowable or '']],
            colWidths=[PRINTABLE_WIDTH - LOGO_MAX_WIDTH, LOGO_MAX_WIDTH],
        )
        header_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
            ('LEFTPADDING', (0, 0), (-1, -1), 0),
            ('RIGHTPADDING', (0, 0), (-1, -1), 0),
            ('TOPPADDING', (0, 0), (-1, -1), 0),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
        ]))

        story = [header_table, Spacer(1, 1 * mm)]

        secondary = f"{delivery_day_display} ({warehouse_name})" if is_van else warehouse_name
        story.append(Paragraph(secondary, styles['small_r']))
        story.append(Spacer(1, 2 * mm))

        story.append(Paragraph(product_name, styles['product']))
        story.append(Spacer(1, 1.5 * mm))

        if is_van:
            story.append(Paragraph(f"Delivery on: {delivery_date_display}", styles['info_c']))
        else:
            story.append(Paragraph(f"Traceability: {origin_country}", styles['info_c']))
        story.append(Spacer(1, 1.5 * mm))

        story.append(Paragraph(f"Fresh Use By: {use_by_display}", styles['useby']))
        story.append(Spacer(1, 2 * mm))

        story.append(Paragraph("Preparation and Storage Information", styles['section_title']))
        if is_van:
            prep_text = (
                "Upon opening, remove the film lid and allow any natural odours to disperse. "
                "Keep refrigerated below 5°C. If freezing, individually wrap the fish prior to placing "
                "in the freezer, this will prevent the fish from freezing together. Use within 3 months "
                "when stored in a domestic freezer."
            )
        else:
            prep_text = (
                "Keep refrigerated below 5°C. If freezing, individually wrap the fish prior to placing "
                "in the freezer, this will prevent the fish from freezing together. Use within 3 months "
                "when stored in a domestic freezer."
            )
        story.append(Paragraph(prep_text, styles['section_body']))
        story.append(Spacer(1, 1.5 * mm))

        story.append(Paragraph("Advisory Information", styles['section_title']))
        story.append(Paragraph(
            "Please take care when eating as some bones may remain. Contains <b>FISH</b>.",
            styles['section_body'],
        ))
        story.append(Spacer(1, 1.5 * mm))

        if is_van:
            story.append(Paragraph(f"Traceability: {origin_country}", styles['info_l']))
            story.append(Spacer(1, 1.5 * mm))

        barcode_flowable = self._label_barcode_flowable(label.get('product_barcode'))
        if barcode_flowable:
            story.append(barcode_flowable)
            story.append(Spacer(1, 1 * mm))

        footer_table = Table(
            [[self._label_circle_flowable(), Paragraph(f"{index + 1} Of {total_labels}", styles['pagecount'])]],
            colWidths=[PRINTABLE_WIDTH * 0.35, PRINTABLE_WIDTH * 0.65],
        )
        footer_table.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'BOTTOM'),
            ('LEFTPADDING', (0, 0), (-1, -1), 0),
            ('RIGHTPADDING', (0, 0), (-1, -1), 0),
            ('TOPPADDING', (0, 0), (-1, -1), 0),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
        ]))
        story.append(footer_table)

        return story

    def generate_pdf(self, wizard):
        """Returns the finished PDF (bytes) for the Production Label report
        (courier or regal van - the two visual variants of the QWeb
        templates in production_label_report_views.xml), or None if there
        is nothing to print. One physical label per page, at the fixed
        100mm x 130mm page size."""
        label_lines = wizard._get_label_data()
        if not label_lines:
            return None

        is_van = self._name == 'report.tl_rf_reports.report_production_label_document_regal_van'
        logo_flowable = self._label_logo_flowable(self.env.company)
        styles = self._label_styles()
        total_labels = len(label_lines)

        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer, pagesize=(PAGE_WIDTH, PAGE_HEIGHT),
            leftMargin=LABEL_MARGIN, rightMargin=LABEL_MARGIN,
            topMargin=LABEL_MARGIN, bottomMargin=LABEL_MARGIN,
        )

        story = []
        for index, label in enumerate(label_lines):
            if index:
                story.append(PageBreak())
            story.extend(self._label_flowables(label, index, total_labels, logo_flowable, is_van, styles))

        doc.build(story)
        pdf_value = buffer.getvalue()
        buffer.close()
        return pdf_value


class ProductionLabelReportRegalVan(models.AbstractModel):
    _name = 'report.tl_rf_reports.report_production_label_document_regal_van'
    _description = 'Production Label Report Data - Regal Van'
    _inherit = 'report.tl_rf_reports.report_production_label_document_courier'
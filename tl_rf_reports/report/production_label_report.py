# -*- coding: utf-8 -*-
from odoo import models


from odoo.tools.image import image_data_uri


class ProductionLabelReport(models.AbstractModel):
    _name = 'report.tl_rf_reports.report_production_label_document_courier'
    _description = 'Production Label Report Data - Courier'

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


class ProductionLabelReportRegalVan(models.AbstractModel):
    _name = 'report.tl_rf_reports.report_production_label_document_regal_van'
    _description = 'Production Label Report Data - Regal Van'
    _inherit = 'report.tl_rf_reports.report_production_label_document_courier'
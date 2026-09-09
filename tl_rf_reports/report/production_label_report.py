# -*- coding: utf-8 -*-
from odoo import models


class ProductionLabelReport(models.AbstractModel):
    _name = 'report.tl_rf_reports.report_production_label_document'
    _description = 'Production Label Report Data'

    def _get_report_values(self, docids, data=None):
        wizard_model = self.env['production.report.wizard']
        docs = wizard_model.browse(docids)

        label_lines = []
        if docs:
            label_lines = docs[0]._get_label_data()

        return {
            'doc_ids': docids,
            'doc_model': 'production.report.wizard',
            'docs': docs,
            'label_lines': label_lines,
            'total_labels': len(label_lines),
            'company': self.env.company,
        }
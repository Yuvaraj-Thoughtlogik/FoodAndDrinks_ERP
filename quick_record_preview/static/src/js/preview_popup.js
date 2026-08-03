/** @odoo-module **/

import { Component } from "@odoo/owl";
import { _t } from "@web/core/l10n/translation";

export class PreviewPopup extends Component {
    static template = "quick_record_preview.PreviewPopup";
    static props = ["record", "fields", "onClose", "onOpen", "*"];

    setup() {
        this.state = {
            loading: true,
            data: null,
        };
    }

    async onWillStart() {
        await this.loadRecordData();
    }

    async loadRecordData() {
        if (!this.props.record || !this.props.record.resId) {
            return;
        }

        try {
            const orm = this.env.services.orm;
            const resModel = this.props.record.model || this.props.record.resModel;
            const resId = this.props.record.resId;

            // Get key fields to display (first 5-8 fields)
            const fieldsToRead = this.props.fields || this.getDefaultFields();
            
            // Read record data
            const records = await orm.read(resModel, [resId], fieldsToRead);
            
            if (records && records.length > 0) {
                this.state.data = records[0];
            }
        } catch (error) {
            console.error("Error loading preview data:", error);
        } finally {
            this.state.loading = false;
        }
    }

    getDefaultFields() {
        // Get first few fields from activeFields
        const record = this.props.record;
        const fields = record.fields || {};
        const activeFields = record.list?.activeFields || {};
        
        // Prioritize common fields
        const priorityFields = ['name', 'display_name', 'state', 'date', 'partner_id', 'user_id', 'amount_total'];
        const fieldNames = new Set();
        
        // Add priority fields first
        for (const fieldName of priorityFields) {
            if (activeFields[fieldName] || fields[fieldName]) {
                fieldNames.add(fieldName);
            }
        }
        
        // Add other active fields up to 8 total
        for (const fieldName in activeFields) {
            if (fieldNames.size >= 8) break;
            fieldNames.add(fieldName);
        }
        
        return Array.from(fieldNames);
    }

    formatFieldValue(fieldName, value) {
        if (value === null || value === undefined || value === false) {
            return _t("N/A");
        }
        
        const field = this.props.record.fields[fieldName];
        if (!field) {
            return String(value);
        }

        // Handle many2one fields
        if (field.type === "many2one" && Array.isArray(value)) {
            return value[1] || value[0] || String(value);
        }
        
        // Handle many2many/one2many
        if ((field.type === "many2many" || field.type === "one2many") && Array.isArray(value)) {
            return `${value.length} ${_t("items")}`;
        }
        
        // Handle boolean
        if (field.type === "boolean") {
            return value ? _t("Yes") : _t("No");
        }
        
        // Handle date/datetime
        if ((field.type === "date" || field.type === "datetime") && typeof value === "string") {
            return value.split(" ")[0]; // Just show date part
        }
        
        return String(value);
    }

    getFieldLabel(fieldName) {
        const field = this.props.record.fields[fieldName];
        return field ? (field.string || fieldName) : fieldName;
    }

    onOpenClick() {
        if (this.props.onOpen) {
            this.props.onOpen(this.props.record);
        }
    }

    onCloseClick() {
        if (this.props.onClose) {
            this.props.onClose();
        }
    }
}


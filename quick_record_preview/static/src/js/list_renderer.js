/** @odoo-module **/

import { ListRenderer } from "@web/views/list/list_renderer";
import { PreviewPopup } from "./preview_popup";
import { parseXML } from "@web/core/utils/xml";
import { patch } from "@web/core/utils/patch";
import { useService } from "@web/core/utils/hooks";
import { url } from "@web/core/utils/urls";
import { onMounted, onWillUnmount, onPatched, useRef } from "@odoo/owl";

patch(ListRenderer.prototype, {
    setup() {
        super.setup(...arguments);
        this.dialog = useService("dialog");
        this.action = useService("action");
        this.previewPopup = null;
        
        // Clean up duplicates after render (safety measure)
        onMounted(async () => {
            await Promise.resolve();
            requestAnimationFrame(() => this._cleanupDuplicatePreviewCells());
        });
        onPatched(async () => {
            await Promise.resolve();
            requestAnimationFrame(() => this._cleanupDuplicatePreviewCells());
        });
    },

    get hasPreviewColumn() {
        // Always show preview column for now
        // Can be controlled via props or config in the future
        return true;
    },

    _cleanupDuplicatePreviewCells() {
        // Safety measure: remove duplicate preview cells and ensure header exists
        const table = this.tableRef?.el;
        if (!table) return;
        
        // Ensure header exists
        const thead = table.querySelector("thead");
        if (thead) {
            const headerRow = thead.querySelector("tr");
            if (headerRow) {
                const previewHeaders = headerRow.querySelectorAll("th.o_list_preview_header");
                if (previewHeaders.length === 0) {
                    // No preview header found, create one
                    const selectorHeader = headerRow.querySelector("th.o_list_record_selector");
                    const previewHeader = document.createElement("th");
                    previewHeader.className = "o_list_preview_header text-center";
                    previewHeader.style.cssText = "width: 70px; min-width: 70px; max-width: 70px; padding: 4px 2px;";
                    previewHeader.innerHTML = '<span style="font-size: 12px; line-height: 1.2; font-weight: bold;">Quick View</span>';
                    
                    if (selectorHeader) {
                        selectorHeader.insertAdjacentElement("afterend", previewHeader);
                    } else {
                        // Insert before first column
                        const firstColumn = headerRow.querySelector("th[data-name], th:not(.o_list_record_selector):not(.o_list_open_form_view):not(.o_list_actions_header)");
                        if (firstColumn) {
                            firstColumn.insertAdjacentElement("beforebegin", previewHeader);
                        } else {
                            headerRow.insertBefore(previewHeader, headerRow.firstChild);
                        }
                    }
                } else if (previewHeaders.length > 1) {
                    // Remove duplicates, keep first
                    for (let i = 1; i < previewHeaders.length; i++) {
                        previewHeaders[i].remove();
                    }
                }
            }
        }
        
        // Clean up duplicate cells
        const rows = table.querySelectorAll("tbody tr.o_data_row");
        rows.forEach(row => {
            const previewCells = row.querySelectorAll("td.o_list_preview_cell");
            if (previewCells.length === 0) {
                // No preview cell found, create one
                const selectorCell = row.querySelector("td.o_list_record_selector");
                const previewCell = document.createElement("td");
                previewCell.className = "o_list_preview_cell text-center";
                previewCell.tabIndex = -1;
                previewCell.style.cssText = "width: 70px; min-width: 70px; max-width: 70px; padding: 2px;";
                
                const button = document.createElement("button");
                button.type = "button";
                button.className = "btn btn-sm btn-link o_preview_btn p-0";
                button.title = "Quick View";
                button.setAttribute("aria-label", "Quick View");
                button.tabIndex = -1;
                button.innerHTML = '<i class="fa fa-eye"></i>';
                
                button.addEventListener("click", (ev) => {
                    ev.stopPropagation();
                    ev.preventDefault();
                    const recordId = row.dataset.id;
                    if (recordId && this.props.list) {
                        const record = this.props.list.records.find(r => r.id === recordId);
                        if (record) {
                            this.onPreviewClick(record, ev);
                        }
                    }
                });
                
                previewCell.appendChild(button);
                
                if (selectorCell) {
                    selectorCell.insertAdjacentElement("afterend", previewCell);
                } else {
                    // Insert before first data cell
                    const firstDataCell = row.querySelector("td.o_data_cell");
                    if (firstDataCell) {
                        firstDataCell.insertAdjacentElement("beforebegin", previewCell);
                    } else {
                        row.insertBefore(previewCell, row.firstChild);
                    }
                }
            } else if (previewCells.length > 1) {
                // Remove duplicates, keep first
                for (let i = 1; i < previewCells.length; i++) {
                    previewCells[i].remove();
                }
            }
        });
    },

    sortStart(params) {
        // Fix header/cell alignment for drag operations
        // Our preview column adds an extra header and cell, so we need to account for it
        const { element } = params;
        const table = this.tableRef.el;
        if (!table || !element) {
            return super.sortStart(...arguments);
        }
        
        const headers = [...table.querySelectorAll("thead th")];
        const cells = [...element.querySelectorAll("td")];
        
        // Find preview column indices
        const previewHeaderIndex = headers.findIndex(th => th.classList.contains('o_list_preview_header'));
        const previewCellIndex = cells.findIndex(td => td.classList.contains('o_list_preview_cell'));
        
        // Filter out preview column from headers and cells for matching
        const dataHeaders = headers.filter((h, i) => i !== previewHeaderIndex);
        const dataCells = cells.filter((c, i) => i !== previewCellIndex);
        
        // Match headers to cells (excluding preview column)
        let headerIndex = 0;
        for (const cell of dataCells) {
            if (!cell || !cell.colSpan) {
                continue;
            }
            let width = 0;
            for (let i = 0; i < cell.colSpan; i++) {
                if (headerIndex + i < dataHeaders.length) {
                    const header = dataHeaders[headerIndex + i];
                    if (header && typeof getComputedStyle !== 'undefined') {
                        try {
                            const style = getComputedStyle(header);
                            width += parseFloat(style.width) || 0;
                        } catch (e) {
                            // Ignore errors
                        }
                    }
                }
            }
            if (width > 0) {
                cell.style.width = `${width}px`;
            }
            headerIndex += cell.colSpan;
        }
    },

    onPreviewClick(record, ev) {
        ev.stopPropagation();
        ev.preventDefault();
        
        // Ensure we have a valid record with resId
        if (!record) {
            console.warn("Preview: No record provided");
            return;
        }
        
        // Get resId - try multiple sources
        const resId = record.resId || record.data?.id || (typeof record.id === 'number' ? record.id : null);
        
        if (!resId) {
            console.warn("Preview: No resId found in record", { record });
            return;
        }
        
        // Verify the record belongs to the current list's model
        const listModel = this.props.list.resModel;
        if (record.model && typeof record.model === 'string' && record.model !== listModel) {
            console.warn("Preview: Record model mismatch", {
                recordModel: record.model,
                listModel: listModel,
                resId: resId
            });
            // Still proceed, but log the warning
        }
        
        // Get the button element for positioning
        const button = ev.currentTarget.closest("td") || ev.target.closest("td") || ev.target;
        this._showPreview(record, button);
    },


    _getAllRecords() {
        // Get all records including grouped ones
        const list = this.props.list;
        const records = [];
        
        // If grouped, flatten groups
        if (list.isGrouped && list.groups) {
            const flattenGroup = (group) => {
                if (group.records) {
                    records.push(...group.records);
                }
                if (group.groups) {
                    group.groups.forEach(g => flattenGroup(g));
                }
            };
            list.groups.forEach(g => flattenGroup(g));
        } else {
            // Not grouped, use records directly
            records.push(...(list.records || []));
        }
        
        return records;
    },

    _findRecordById(recordId) {
        // Try to find record by id (not resId)
        const allRecords = this._getAllRecords();
        
        // First try by id (the record's internal id)
        let record = allRecords.find(r => {
            const id = r.id;
            return id && id.toString() === recordId.toString();
        });
        
        // If not found, try by resId
        if (!record) {
            record = allRecords.find(r => {
                const id = r.resId;
                return id && id.toString() === recordId.toString();
            });
        }
        
        // If still not found and recordId is numeric, try by index
        if (!record && !isNaN(recordId)) {
            const index = parseInt(recordId);
            if (index >= 0 && index < allRecords.length) {
                record = allRecords[index];
            }
        }
        
        return record;
    },

    _showPreview(record, targetElement) {
        // Don't show if already showing for this record
        if (this.previewPopup && this.previewPopup.record && 
            this.previewPopup.record.resId === record.resId) {
            return;
        }

        // Close any existing preview
        this._closePreview();

        // Load record data and show popup
        this._loadAndShowPreview(record, targetElement);
    },

    async _loadAndShowPreview(record, targetElement) {
        try {
            // Load record data
            const orm = this.env.services.orm;
            const viewService = this.env.services.view;
            const rpc = this.env.services.rpc;
            
            // Get model name from list - ensure we're using the correct model
            const resModel = this.props.list.resModel;
            
            // Load configuration for this model
            let config = null;
            try {
                config = await rpc("/preview_config/get_config", {
                    model_name: resModel,
                });
            } catch (error) {
                console.warn("Could not load preview config:", error);
                // Use default config
                config = {
                    field_names: [],
                    show_image: true,
                    show_display_name: true,
                };
            }
            
            // Ensure we have the correct resId from the record
            let resId = record.resId;
            if (!resId && record.data && record.data.id) {
                resId = record.data.id;
            }
            if (!resId && record.id && typeof record.id === 'number') {
                resId = record.id;
            }
            
            if (!resModel || !resId) {
                console.warn("Cannot load preview: missing resModel or resId", { 
                    resModel, 
                    resId,
                    record: record,
                    recordId: record.id,
                    recordResId: record.resId,
                    recordDataId: record.data?.id
                });
                return;
            }
            
            // Load form view to get fields that exist in the form
            let formFields = null;
            let allFields = this.props.list.fields || {};
            
            try {
                const views = await viewService.loadViews({
                    resModel: resModel,
                    views: [[false, "form"]],
                });
                if (views && views.views && views.views.form && views.fields) {
                    // Extract field names from form view architecture (excluding x2many fields)
                    const formFieldNames = this._extractFieldsFromFormArch(views.views.form.arch, views.fields);
                    console.log("Form fields extracted:", formFieldNames.length, formFieldNames.slice(0, 20));
                    
                    // If extraction found very few fields, use all fields from views.fields instead
                    if (formFieldNames.length < 5) {
                        console.warn("Very few fields extracted from form view, using all fields from view definition");
                        // Use all fields from views.fields that are not x2many
                        formFields = {};
                        for (const fieldName in views.fields) {
                            const field = views.fields[fieldName];
                            if (field && !field.compute && field.type !== "one2many" && field.type !== "many2many") {
                                formFields[fieldName] = field;
                            }
                        }
                    } else {
                        formFields = {};
                        // Use form view fields definition (more complete)
                        for (const fieldName of formFieldNames) {
                            if (views.fields[fieldName]) {
                                formFields[fieldName] = views.fields[fieldName];
                            }
                        }
                    }
                    // Use form view fields if available, otherwise use all fields
                    allFields = views.fields;
                }
            } catch (error) {
                console.warn("Could not load form view, using all fields:", error);
            }
            
            // Get fields to read - prioritize form view fields if available
            // Also ensure image fields are included
            const imageFieldNames = ['image_1920', 'image_128', 'image', 'avatar_1920', 'avatar_128', 'avatar'];
            const fieldsToReadSet = new Set();
            
            // Add image fields first to ensure they're included (even if computed)
            for (const imageField of imageFieldNames) {
                if (allFields[imageField]) {
                    const field = allFields[imageField];
                    // Include binary image fields, and computed avatar fields
                    if (field.type === 'binary' || (field.type === 'binary' && field.compute)) {
                        fieldsToReadSet.add(imageField);
                    }
                }
            }
            
            // Add form view fields or all fields
            const sourceFields = formFields && Object.keys(formFields).length > 0 ? formFields : allFields;
            for (const fieldName in sourceFields) {
                const field = sourceFields[fieldName];
                // Skip computed fields and x2many fields, but allow image/avatar fields
                const isImageField = imageFieldNames.includes(fieldName);
                if (field && field.type !== "one2many" && field.type !== "many2many") {
                    // Include image fields even if computed, exclude other computed fields
                    if (isImageField || !field.compute) {
                        fieldsToReadSet.add(fieldName);
                    }
                }
            }
            
            // Apply configuration: filter fields based on config
            let fieldsToRead = Array.from(fieldsToReadSet);
            
            // If configuration exists and specifies fields, use ALL configured fields
            if (config && config.field_names && config.field_names.length > 0) {
                // Start with configured fields
                fieldsToRead = [...config.field_names];
                
                // Add display_name if enabled
                if (config.show_display_name && !fieldsToRead.includes('display_name')) {
                    fieldsToRead.push('display_name');
                }
                
                // Add image fields if enabled
                if (config.show_image) {
                    imageFieldNames.forEach(f => {
                        if (allFields[f] && !fieldsToRead.includes(f)) {
                            fieldsToRead.push(f);
                        }
                    });
                }
            } else {
                // No config: use default behavior (all fields, but limit if no form view)
                if (!formFields || Object.keys(formFields).length === 0) {
                    // Keep image fields and limit others
                    const nonImageFields = fieldsToRead.filter(f => !imageFieldNames.includes(f));
                    const limitedNonImageFields = nonImageFields.slice(0, 50);
                    fieldsToRead = [...imageFieldNames.filter(f => fieldsToReadSet.has(f)), ...limitedNonImageFields];
                }
            }
            
            console.log("Fields to read:", fieldsToRead.length, fieldsToRead.slice(0, 20));
            
            // Load record data
            const records = await orm.read(resModel, [resId], fieldsToRead);
            if (!records || records.length === 0) {
                console.warn("No records returned from read");
                return;
            }
            const recordData = records[0];
            
            console.log("Record data keys:", Object.keys(recordData).length, Object.keys(recordData).slice(0, 20));
            
            // Create popup with custom simple view - use allFields to have access to all field definitions
            // Pass config to _createCustomPopup so it can use it
            this._createCustomPopup(record, recordData, allFields, targetElement, config);
        } catch (error) {
            console.error("Error loading preview:", error);
        }
    },

    _createCustomPopup(record, recordData, fields, targetElement, config = null) {
        // Create popup element
        const popup = document.createElement("div");
        popup.className = "o_record_preview_popup o_record_preview_custom";
        
        // Position popup relative to the button/row
        const buttonRect = targetElement.getBoundingClientRect();
        const row = targetElement.closest("tr.o_data_row");
        const rowRect = row ? row.getBoundingClientRect() : buttonRect;
        
        const popupRect = {
            top: rowRect.bottom + 10,
            left: rowRect.right + 10, // Position to the right of the row
        };

        const viewportWidth = window.innerWidth;
        const viewportHeight = window.innerHeight;
        const popupWidth = 500;
        const popupHeight = 500;

        // Adjust if popup would go off screen
        if (popupRect.left + popupWidth > viewportWidth) {
            popupRect.left = rowRect.left - popupWidth - 10; // Show to the left instead
        }
        if (popupRect.left < 10) {
            popupRect.left = 10; // Ensure it's visible
        }
        if (popupRect.top + popupHeight > viewportHeight) {
            popupRect.top = Math.max(10, rowRect.top - popupHeight - 10); // Show above if needed
        }
        if (popupRect.top < 10) {
            popupRect.top = 10; // Ensure it's visible
        }

        popup.style.position = "fixed";
        popup.style.top = `${popupRect.top}px`;
        popup.style.left = `${popupRect.left}px`;
        popup.style.zIndex = "9999";
        popup.style.width = `${popupWidth}px`;
        popup.style.maxHeight = `${popupHeight}px`;
        popup.style.display = "flex";
        popup.style.flexDirection = "column";

        const displayName = record.display_name || recordData.display_name || recordData.name || `Record #${record.resId}`;
        
        // Get image URL if available
        // First check record.data (already loaded in list view), then recordData (from read)
        const resModel = this.props.list.resModel;
        const resId = record.resId || recordData.id;
        const combinedRecordData = { ...record.data, ...recordData };
        const imageUrl = this._getImageUrl(combinedRecordData, fields, resModel, resId);
        
        // Build fields HTML - show fields in a clean list
        const fieldsHtml = this._buildCustomFieldsHtml(recordData, fields);
        
        // Build image HTML if available
        const imageHtml = imageUrl ? `
            <div class="o_preview_popup_image">
                <img src="${this._escapeHtml(imageUrl)}" alt="${this._escapeHtml(displayName)}" />
            </div>
        ` : '';
        
        popup.innerHTML = `
            <div class="o_preview_popup_content">
                <div class="o_preview_popup_header">
                    <h5 class="o_preview_popup_title">${this._escapeHtml(displayName)}</h5>
                    <button type="button" class="btn-close" aria-label="Close"></button>
                </div>
                ${imageHtml}
                <div class="o_preview_popup_body o_preview_custom_body">
                    <div class="o_preview_custom_fields">
                        ${fieldsHtml}
                    </div>
                </div>
                <div class="o_preview_popup_footer">
                    <button type="button" class="btn btn-primary btn-sm o_preview_open_btn">
                        <i class="fa fa-external-link"></i> Open
                    </button>
                </div>
            </div>
        `;

        document.body.appendChild(popup);
        this.previewPopup = { element: popup, record: record };

        // Add event handlers
        const closeBtn = popup.querySelector(".btn-close");
        const openBtn = popup.querySelector(".o_preview_open_btn");
        
        closeBtn.addEventListener("click", () => this._closePreview());
        openBtn.addEventListener("click", () => {
            this._openRecord(record);
            this._closePreview();
        });

        popup.addEventListener("mouseleave", () => {
            setTimeout(() => {
                if (!popup.matches(":hover")) {
                    this._closePreview();
                }
            }, 100);
        });

        // Handle Escape key
        const escapeHandler = (ev) => {
            if (ev.key === "Escape") {
                this._closePreview();
                document.removeEventListener("keydown", escapeHandler);
            }
        };
        document.addEventListener("keydown", escapeHandler);
    },

    _getImageUrl(recordData, fields, resModel, resId) {
        // Common image field names to check (in priority order)
        // Note: avatar fields are computed, so we check if they exist in recordData
        const imageFieldNames = ['image_1920', 'image_128', 'image', 'avatar_1920', 'avatar_128', 'avatar'];
        
        console.log("Checking for image:", {
            resModel,
            resId,
            recordDataKeys: Object.keys(recordData).slice(0, 20),
            imageFieldsInData: imageFieldNames.filter(f => recordData.hasOwnProperty(f)),
            fieldsAvailable: imageFieldNames.filter(f => fields[f])
        });
        
        for (const fieldName of imageFieldNames) {
            const field = fields[fieldName];
            const value = recordData[fieldName];
            
            // Check if value exists in recordData (even if field is computed)
            if (value) {
                // Check if it's a binary size string (like "123.45 KB")
                if (typeof value === 'string' && /^\d+(\.\d*)? [^0-9]+$/.test(value)) {
                    continue; // Skip binary size strings
                }
                
                // For binary fields or computed avatar fields, build image URL
                // Also try avatar fields even if field definition not found (computed fields)
                if (field && (field.type === 'binary' || fieldName.startsWith('avatar_'))) {
                    try {
                        const imageUrl = url("/web/image", {
                            model: resModel,
                            id: resId,
                            field: fieldName,
                        });
                        console.log(`Found image URL for ${fieldName}:`, imageUrl);
                        return imageUrl;
                    } catch (e) {
                        console.warn(`Error building image URL for ${fieldName}:`, e);
                    }
                } else if (!field && fieldName.startsWith('avatar_')) {
                    // Try avatar fields even if field definition not found (computed fields)
                    try {
                        const imageUrl = url("/web/image", {
                            model: resModel,
                            id: resId,
                            field: fieldName,
                        });
                        console.log(`Found image URL for ${fieldName} (no field def):`, imageUrl);
                        return imageUrl;
                    } catch (e) {
                        console.warn(`Error building image URL for ${fieldName}:`, e);
                    }
                }
            }
        }
        
        // If no image found in recordData, try building URL anyway for common image fields
        // (in case the field exists but value wasn't loaded)
        for (const fieldName of ['image_1920', 'image_128', 'avatar_128']) {
            if (fields[fieldName] && fields[fieldName].type === 'binary') {
                try {
                    const imageUrl = url("/web/image", {
                        model: resModel,
                        id: resId,
                        field: fieldName,
                    });
                    console.log(`Trying image URL for ${fieldName} (value not loaded):`, imageUrl);
                    return imageUrl;
                } catch (e) {
                    // Ignore errors, try next field
                }
            }
        }
        
        console.log("No image found");
        return null;
    },

    _isMixinField(fieldName) {
        // Exclude fields from mail.thread, mail.activity.mixin, and other common mixins
        const mixinFieldPatterns = [
            // Mail thread fields
            'message_follower_ids',
            'message_partner_ids',
            'message_channel_ids',
            'message_ids',
            'message_main_attachment_id',
            'message_has_error',
            'message_has_error_counter',
            'message_has_suggestion_counter',
            'message_is_follower',
            'message_needaction',
            'message_needaction_counter',
            'message_unread',
            'message_unread_counter',
            'message_attachment_count',
            'message_is_archived',
            'message_author_id',
            'message_author_avatar',
            'message_has_error_counter',
            'message_has_suggestion',
            'message_has_suggestion_counter',
            'message_content_preview',
            'message_preview',
            // Activity fields
            'activity_ids',
            'activity_date_deadline',
            'activity_summary',
            'activity_type_id',
            'activity_user_id',
            'activity_state',
            'activity_type',
            'activity_date',
            'activity_user',
            'my_activity_date_deadline',
            // Other common mixin fields
            'website_message_ids',
            'website_published',
            'website_url',
            'website_meta_title',
            'website_meta_description',
            'website_meta_keywords',
            'website_meta_og_img',
        ];
        
        // Check exact matches
        if (mixinFieldPatterns.includes(fieldName)) {
            return true;
        }
        
        // Check patterns
        const lowerFieldName = fieldName.toLowerCase();
        if (lowerFieldName.startsWith('message_') || 
            lowerFieldName.startsWith('activity_') ||
            lowerFieldName.startsWith('website_') ||
            lowerFieldName.endsWith('_message_ids') ||
            lowerFieldName.endsWith('_activity_ids')) {
            return true;
        }
        
        return false;
    },

    _buildCustomFieldsHtml(recordData, fields, config = null) {
        // Apply configuration: filter fields if config specifies field_names
        let fieldsToShow = Object.keys(recordData);
        if (config && config.field_names && config.field_names.length > 0) {
            // Use configured fields + display_name if enabled
            fieldsToShow = [...config.field_names];
            if (config.show_display_name && !fieldsToShow.includes('display_name')) {
                fieldsToShow.push('display_name');
            }
        }
        
        // Build a clean list of fields - show ALL fields that exist in form view
        const priorityFields = ['name', 'display_name', 'state', 'date', 'date_order', 'partner_id', 'user_id', 'amount_total', 'price_total'];
        const fieldNames = new Set();
        
        console.log("Building fields HTML:", {
            fieldsCount: Object.keys(fields).length,
            recordDataKeys: Object.keys(recordData).length,
            fieldsKeys: Object.keys(fields).slice(0, 10),
            recordDataKeysSample: Object.keys(recordData).slice(0, 10)
        });
        
        // Add priority fields first (if they exist in fields and recordData)
        for (const fieldName of priorityFields) {
            if (fields[fieldName] && recordData.hasOwnProperty(fieldName)) {
                fieldNames.add(fieldName);
            }
        }
        
        // Add ALL other fields from fields object that exist in recordData
        for (const fieldName in fields) {
            if (!fieldNames.has(fieldName) && recordData.hasOwnProperty(fieldName)) {
                const field = fields[fieldName];
                // Skip x2many fields, JSON fields, image fields, and mixin fields
                if (field && (
                    field.type === "one2many" || 
                    field.type === "many2many" || 
                    field.type === "json" ||
                    (field.type === "binary" && fieldName.toLowerCase().includes('image')) ||
                    this._isMixinField(fieldName)
                )) {
                    continue;
                }
                fieldNames.add(fieldName);
            }
        }
        
        console.log("Fields collected:", fieldNames.size, Array.from(fieldNames).slice(0, 15));
        
        // Build HTML for each field - only show fields with values, then limit to 100
        const fieldsWithValues = Array.from(fieldNames).map(fieldName => {
            const value = recordData[fieldName];
            const field = fields[fieldName];
            
            if (!field) {
                console.warn("Field not found in fields object:", fieldName);
                return null;
            }
            
            // Skip JSON fields
            if (field.type === "json") {
                return null;
            }
            
            // Skip empty fields (except boolean false which is a valid value)
            const isEmpty = (value === null || value === undefined || value === false) && field.type !== "boolean";
            if (isEmpty) {
                return null;
            }
            
            // Skip empty strings
            if (typeof value === "string" && value.trim() === "") {
                return null;
            }
            
            // Skip empty arrays
            if (Array.isArray(value) && value.length === 0) {
                return null;
            }
            
            const label = field.string || fieldName;
            const formattedValue = this._formatFieldValue(field, value);
            
            // Skip if formatted value is empty
            if (!formattedValue || (typeof formattedValue === "string" && formattedValue.trim() === "")) {
                return null;
            }
            
            return {
                html: `
                    <div class="o_preview_custom_field">
                        <div class="o_preview_custom_field_label">${this._escapeHtml(label)}</div>
                        <div class="o_preview_custom_field_value">${this._escapeHtml(formattedValue)}</div>
                    </div>
                `,
                fieldName: fieldName
            };
        }).filter(item => item !== null && item !== undefined && item.html && typeof item.html === 'string' && item.html.trim());
        
        // Limit to 100 fields after filtering empty ones
        const limitedFields = fieldsWithValues.slice(0, 100);
        const fieldsHtml = limitedFields.map(item => item.html).join("");
        
        console.log("Fields with values:", fieldsWithValues.length, "Limited to:", limitedFields.length);
        
        return fieldsHtml;
    },

    _createPopup(record, recordData, targetElement) {
        // Create popup element
        const popup = document.createElement("div");
        popup.className = "o_record_preview_popup";
        
        // Position popup near the target element
        const rect = targetElement.getBoundingClientRect();
        const popupRect = {
            top: rect.bottom + 10,
            left: rect.left,
        };

        // Adjust if popup would go off screen
        const viewportWidth = window.innerWidth;
        const viewportHeight = window.innerHeight;
        const popupWidth = 350;
        const popupHeight = 400;

        if (popupRect.left + popupWidth > viewportWidth) {
            popupRect.left = viewportWidth - popupWidth - 10;
        }
        if (popupRect.top + popupHeight > viewportHeight) {
            popupRect.top = rect.top - popupHeight - 10;
        }

        popup.style.position = "fixed";
        popup.style.top = `${popupRect.top}px`;
        popup.style.left = `${popupRect.left}px`;
        popup.style.zIndex = "9999";

        // Build popup content
        const fields = this._getPreviewFields(record);
        const listFields = this.props.list.fields || {};
        const fieldsHtml = fields.map(fieldName => {
            const value = recordData[fieldName];
            const field = listFields[fieldName] || record.fields?.[fieldName];
            const label = field ? (field.string || fieldName) : fieldName;
            const formattedValue = this._formatFieldValue(field, value);
            
            // Skip if value is empty/null and not a boolean
            if ((value === null || value === undefined || value === false) && field && field.type !== "boolean") {
                return "";
            }
            
            return `
                <div class="o_preview_field">
                    <span class="o_preview_field_label">${this._escapeHtml(label)}:</span>
                    <span class="o_preview_field_value">${this._escapeHtml(formattedValue)}</span>
                </div>
            `;
        }).filter(html => html.trim()).join("");

        const displayName = record.display_name || record.data?.display_name || record.data?.name || record.name || `Record #${record.resId}`;
        
        popup.innerHTML = `
            <div class="o_preview_popup_content">
                <div class="o_preview_popup_header">
                    <h5 class="o_preview_popup_title">${this._escapeHtml(displayName)}</h5>
                    <button type="button" class="btn-close" aria-label="Close"></button>
                </div>
                <div class="o_preview_popup_body">
                    ${fieldsHtml ? `
                        <div class="o_preview_fields">
                            ${fieldsHtml}
                        </div>
                    ` : `
                        <div class="text-center p-3 text-muted">
                            No fields available
                        </div>
                    `}
                </div>
                <div class="o_preview_popup_footer">
                    <button type="button" class="btn btn-primary btn-sm o_preview_open_btn">
                        <i class="fa fa-external-link"></i> Open
                    </button>
                </div>
            </div>
        `;

        document.body.appendChild(popup);
        this.previewPopup = { element: popup, record: record };

        // Add event handlers
        const closeBtn = popup.querySelector(".btn-close");
        const openBtn = popup.querySelector(".o_preview_open_btn");
        
        closeBtn.addEventListener("click", () => this._closePreview());
        openBtn.addEventListener("click", () => {
            this._openRecord(record);
            this._closePreview();
        });

        popup.addEventListener("mouseleave", () => {
            setTimeout(() => {
                if (!popup.matches(":hover")) {
                    this._closePreview();
                }
            }, 100);
        });

        // Handle Escape key
        const escapeHandler = (ev) => {
            if (ev.key === "Escape") {
                this._closePreview();
                document.removeEventListener("keydown", escapeHandler);
            }
        };
        document.addEventListener("keydown", escapeHandler);
    },

    _formatFieldValue(field, value) {
        if (value === null || value === undefined) {
            return "";
        }
        
        if (value === false && field && field.type === "boolean") {
            return "No";
        }
        
        if (value === false && (!field || field.type !== "boolean")) {
            return "";
        }
        
        if (!field) {
            return String(value || "");
        }

        // Handle many2one fields (can be array [id, name] or object {id, display_name, name})
        if (field.type === "many2one") {
            if (Array.isArray(value)) {
                return value[1] || value[0] || "";
            } else if (value && typeof value === "object") {
                // Try multiple possible property names
                if (value.display_name) return value.display_name;
                if (value.name) return value.name;
                if (value[1]) return value[1]; // Sometimes it's array-like object
                if (value.id) return String(value.id);
                // If it's an object but we can't find a name, try JSON stringify to see what's inside
                try {
                    const keys = Object.keys(value);
                    if (keys.length > 0) {
                        // Try to get a readable value
                        return value[keys[0]] || "";
                    }
                } catch (e) {
                    // Ignore
                }
                return "[Object]";
            }
            return String(value || "");
        }
        
        // Handle many2many/one2many
        if ((field.type === "many2many" || field.type === "one2many") && Array.isArray(value)) {
            return `${value.length} items`;
        }
        
        // Handle boolean
        if (field.type === "boolean") {
            return value ? "Yes" : "No";
        }
        
        // Handle date/datetime
        if ((field.type === "date" || field.type === "datetime") && typeof value === "string") {
            return value.split(" ")[0]; // Just show date part
        }
        
        return String(value || "");
    },

    _escapeHtml(text) {
        const div = document.createElement("div");
        div.textContent = text;
        return div.innerHTML;
    },

    async _createFormViewPopup(record, recordData, formViewInfo, targetElement) {
        // Create popup element
        const popup = document.createElement("div");
        popup.className = "o_record_preview_popup o_record_preview_form";
        
        // Position popup relative to the button/row
        const buttonRect = targetElement.getBoundingClientRect();
        const row = targetElement.closest("tr.o_data_row");
        const rowRect = row ? row.getBoundingClientRect() : buttonRect;
        
        const popupRect = {
            top: rowRect.bottom + 10,
            left: rowRect.right + 10, // Position to the right of the row
        };

        const viewportWidth = window.innerWidth;
        const viewportHeight = window.innerHeight;
        const popupWidth = 600;
        const popupHeight = 500;

        // Adjust if popup would go off screen
        if (popupRect.left + popupWidth > viewportWidth) {
            popupRect.left = rowRect.left - popupWidth - 10; // Show to the left instead
        }
        if (popupRect.left < 10) {
            popupRect.left = 10; // Ensure it's visible
        }
        if (popupRect.top + popupHeight > viewportHeight) {
            popupRect.top = Math.max(10, rowRect.top - popupHeight - 10); // Show above if needed
        }
        if (popupRect.top < 10) {
            popupRect.top = 10; // Ensure it's visible
        }

        popup.style.position = "fixed";
        popup.style.top = `${popupRect.top}px`;
        popup.style.left = `${popupRect.left}px`;
        popup.style.zIndex = "9999";
        popup.style.width = `${popupWidth}px`;
        popup.style.maxHeight = `${popupHeight}px`;

        const displayName = record.display_name || record.data?.display_name || record.data?.name || record.name || `Record #${record.resId}`;
        
        popup.innerHTML = `
            <div class="o_preview_popup_content">
                <div class="o_preview_popup_header">
                    <h5 class="o_preview_popup_title">${this._escapeHtml(displayName)}</h5>
                    <button type="button" class="btn-close" aria-label="Close"></button>
                </div>
                <div class="o_preview_popup_body o_preview_form_body">
                    <div class="o_preview_loading">
                        <i class="fa fa-spinner fa-spin"></i> Loading form view...
                    </div>
                </div>
                <div class="o_preview_popup_footer">
                    <button type="button" class="btn btn-primary btn-sm o_preview_open_btn">
                        <i class="fa fa-external-link"></i> Open
                    </button>
                </div>
            </div>
        `;

        document.body.appendChild(popup);
        this.previewPopup = { element: popup, record: record };

        // Add event handlers
        const closeBtn = popup.querySelector(".btn-close");
        const openBtn = popup.querySelector(".o_preview_open_btn");
        const formBody = popup.querySelector(".o_preview_form_body");
        
        closeBtn.addEventListener("click", () => this._closePreview());
        openBtn.addEventListener("click", () => {
            this._openRecord(record);
            this._closePreview();
        });

        popup.addEventListener("mouseleave", () => {
            setTimeout(() => {
                if (!popup.matches(":hover")) {
                    this._closePreview();
                }
            }, 100);
        });

        // Handle Escape key
        const escapeHandler = (ev) => {
            if (ev.key === "Escape") {
                this._closePreview();
                document.removeEventListener("keydown", escapeHandler);
            }
        };
        document.addEventListener("keydown", escapeHandler);

        // Parse and render form view manually (to avoid portal issues)
        try {
            const resModel = this.props.list.resModel;
            
            // Parse form view arch XML
            const xmlDoc = parseXML(formViewInfo.arch);
            
            // Build form-like HTML structure based on arch (no need to parse with FormArchParser)
            const fieldsHtml = this._buildFormViewHtml(record, recordData, formViewInfo.fields, xmlDoc);
            
            // Remove loading indicator
            const loadingEl = formBody.querySelector(".o_preview_loading");
            if (loadingEl) {
                loadingEl.remove();
            }
            
            // Render the form view HTML
            formBody.innerHTML = `
                <div class="o_preview_form_view">
                    ${fieldsHtml}
                </div>
            `;
        } catch (error) {
            console.error("Error parsing form view:", error);
            // Fallback to field list
            const loadingEl = formBody.querySelector(".o_preview_loading");
            if (loadingEl) {
                loadingEl.remove();
            }
            formBody.innerHTML = `
                <div class="text-center p-3 text-muted">
                    Error loading form view. Showing field list instead.
                </div>
                <div class="o_preview_form_fields">
                    ${this._buildFieldsHtml(record, recordData)}
                </div>
            `;
        }
    },

    _closePreview() {
        if (this.previewPopup && this.previewPopup.element) {
            const element = this.previewPopup.element;
            if (element.parentNode) {
                element.parentNode.removeChild(element);
            }
            this.previewPopup = null;
        }
    },

    _getPreviewFields(record) {
        // Get first 8 fields from activeFields or list fields
        const list = this.props.list;
        const activeFields = list?.activeFields || {};
        const allFields = list?.fields || {};
        
        // Prioritize common fields
        const priorityFields = ['name', 'display_name', 'state', 'date', 'date_order', 'partner_id', 'user_id', 'amount_total', 'price_total'];
        const fieldNames = new Set();
        
        // Add priority fields first if they exist
        for (const fieldName of priorityFields) {
            if (activeFields[fieldName] || allFields[fieldName]) {
                fieldNames.add(fieldName);
            }
        }
        
        // Add other active fields up to 8 total
        for (const fieldName in activeFields) {
            if (fieldNames.size >= 8) break;
            if (!fieldNames.has(fieldName)) {
                fieldNames.add(fieldName);
            }
        }
        
        // If still not enough, add from all fields
        if (fieldNames.size < 5) {
            for (const fieldName in allFields) {
                if (fieldNames.size >= 8) break;
                if (!fieldNames.has(fieldName) && fieldName !== 'id') {
                    fieldNames.add(fieldName);
                }
            }
        }
        
        return Array.from(fieldNames);
    },

    _extractFieldsFromFormArch(arch, fields) {
        // Extract all field names from form view architecture
        // Skip fields that are inside one2many/many2many contexts and notebooks
        const fieldNames = new Set();
        const xmlDoc = typeof arch === 'string' ? parseXML(arch) : arch;
        
        const visitFields = (node, insideX2Many = false) => {
            if (!node) return;
            
            const tagName = node.tagName?.toLowerCase();
            
            // Skip notebooks entirely
            if (tagName === "notebook") {
                return;
            }
            
            // Check if this is a one2many or many2many field
            if (tagName === "field") {
                const fieldName = node.getAttribute("name");
                if (fieldName && fields[fieldName]) {
                    const field = fields[fieldName];
                    // If we're inside an x2many context, skip fields
                    if (insideX2Many) {
                        // Still traverse children in case there are nested fields
                        Array.from(node.children || []).forEach(child => visitFields(child, true));
                        return;
                    }
                    // If this field is itself an x2many, mark context and skip its children
                    if (field.type === "one2many" || field.type === "many2many") {
                        // Don't add x2many fields themselves, and skip their children
                        Array.from(node.children || []).forEach(child => visitFields(child, true));
                        return;
                    }
                    // Check invisible attribute - but still add the field (we'll filter later if needed)
                    // Don't skip invisible fields here, let them be included
                    fieldNames.add(fieldName);
                }
            }
            
            // Continue traversing ALL children (groups, sheets, etc.)
            // Use childNodes to get all nodes including text nodes, then filter
            const children = Array.from(node.childNodes || []).filter(child => child.nodeType === 1); // Element nodes only
            children.forEach(child => visitFields(child, insideX2Many));
        };
        
        const formElement = xmlDoc.querySelector("form") || xmlDoc.documentElement;
        if (formElement) {
            visitFields(formElement, false);
        }
        
        console.log("Extracted fields from arch:", Array.from(fieldNames));
        
        return Array.from(fieldNames);
    },

    _extractFieldsFromArch(arch, fields) {
        // Extract all field names from form view architecture
        // Skip fields that are inside one2many/many2many contexts
        const fieldNames = new Set();
        const xmlDoc = typeof arch === 'string' ? parseXML(arch) : arch;
        
        const visitFields = (node, insideX2Many = false) => {
            const tagName = node.tagName?.toLowerCase();
            
            // Check if this is a one2many or many2many field
            if (tagName === "field") {
                const fieldName = node.getAttribute("name");
                if (fieldName && fields[fieldName]) {
                    const field = fields[fieldName];
                    // If we're inside an x2many context, skip fields
                    if (insideX2Many) {
                        return;
                    }
                    // If this field is itself an x2many, mark context and skip its children
                    if (field.type === "one2many" || field.type === "many2many") {
                        // Don't add x2many fields themselves, and skip their children
                        Array.from(node.children || []).forEach(child => visitFields(child, true));
                        return;
                    }
                    fieldNames.add(fieldName);
                }
            }
            
            // Continue traversing, passing the x2many context flag
            Array.from(node.children || []).forEach(child => visitFields(child, insideX2Many));
        };
        
        const formElement = xmlDoc.querySelector("form") || xmlDoc.documentElement;
        if (formElement) {
            visitFields(formElement, false);
        }
        
        return Array.from(fieldNames);
    },

    _buildFormViewHtml(record, recordData, fields, xmlDoc) {
        // Build HTML structure matching form view layout exactly
        // Skip fields inside one2many/many2many contexts
        let html = "";
        let fieldCount = 0;
        const maxFields = 100; // Increased limit
        
        const visitAndRender = (node, depth = 0, insideX2Many = false) => {
            if (!node || fieldCount >= maxFields) return;
            
            const tagName = node.tagName?.toLowerCase();
            
            if (tagName === "form") {
                // Start form container
                html += `<div class="o_form_view o_form_readonly">`;
                Array.from(node.children || []).forEach(child => visitAndRender(child, depth + 1, insideX2Many));
                html += `</div>`;
            } else if (tagName === "sheet") {
                // Sheet container (main content area)
                const sheetClasses = ["o_form_sheet", "bg-white", "o_form_sheet_bg"];
                html += `<div class="${sheetClasses.join(' ')}">`;
                Array.from(node.children || []).forEach(child => visitAndRender(child, depth + 1, insideX2Many));
                html += `</div>`;
            } else if (tagName === "group") {
                // Group container - check for col/colspan attributes
                const col = node.getAttribute("col") || "";
                const colspan = node.getAttribute("colspan") || "";
                const string = node.getAttribute("string") || "";
                let groupClasses = ["o_group"];
                
                if (col) {
                    groupClasses.push(`col-${col}`);
                }
                if (colspan) {
                    groupClasses.push(`col-${colspan}`);
                }
                
                // Check if it's a two-column group
                const children = Array.from(node.children || []);
                const hasTwoColumns = children.some(child => child.getAttribute && child.getAttribute("col"));
                
                if (string) {
                    html += `<div class="o_group o_label_nowrap"><label class="o_form_label">${this._escapeHtml(string)}</label></div>`;
                }
                
                html += `<div class="${groupClasses.join(' ')} ${hasTwoColumns ? 'row' : ''}">`;
                Array.from(node.children || []).forEach(child => visitAndRender(child, depth + 1, insideX2Many));
                html += `</div>`;
            } else if (tagName === "field") {
                const fieldName = node.getAttribute("name");
                if (!fieldName) {
                    Array.from(node.children || []).forEach(child => visitAndRender(child, depth + 1, insideX2Many));
                    return;
                }
                
                const field = fields[fieldName];
                
                if (!field) {
                    Array.from(node.children || []).forEach(child => visitAndRender(child, depth + 1, insideX2Many));
                    return;
                }
                
                // Skip fields inside x2many contexts (like invoice lines)
                if (insideX2Many) {
                    // If this is an x2many field itself, mark context for children
                    if (field.type === "one2many" || field.type === "many2many") {
                        Array.from(node.children || []).forEach(child => visitAndRender(child, depth + 1, true));
                    }
                    return;
                }
                
                // If this field is itself an x2many, skip it and mark context for children
                if (field.type === "one2many" || field.type === "many2many") {
                    // Don't render x2many fields, just skip them
                    Array.from(node.children || []).forEach(child => visitAndRender(child, depth + 1, true));
                    return;
                }
                
                const value = recordData[fieldName];
                
                // Check invisible attribute
                const invisible = node.getAttribute("invisible");
                if (invisible === "1" || invisible === "True") {
                    Array.from(node.children || []).forEach(child => visitAndRender(child, depth + 1, insideX2Many));
                    return;
                }
                
                const label = field.string || fieldName;
                const formattedValue = this._formatFieldValue(field, value);
                const isEmpty = (value === null || value === undefined || value === false) && field.type !== "boolean";
                
                // Get widget and field type
                const widget = node.getAttribute("widget") || "";
                const col = node.getAttribute("col") || "";
                const colspan = node.getAttribute("colspan") || "";
                
                // Build field wrapper classes
                let fieldClasses = ["o_field_wrapper"];
                if (col) {
                    fieldClasses.push(`col-${col}`);
                }
                if (colspan) {
                    fieldClasses.push(`col-${colspan}`);
                }
                
                // Field type specific classes
                const fieldTypeClass = `o_field_${field.type}`;
                const widgetClass = widget ? `o_field_widget_${widget}` : "";
                
                // Build field HTML matching Odoo's structure
                html += `
                    <div class="${fieldClasses.join(' ')}" data-name="${this._escapeHtml(fieldName)}">
                        <label class="o_form_label">
                            <span>${this._escapeHtml(label)}</span>
                        </label>
                        <div class="${fieldTypeClass} ${widgetClass} o_readonly_modifier">
                            ${isEmpty ? '<span class="text-muted">-</span>' : this._escapeHtml(formattedValue)}
                        </div>
                    </div>
                `;
                fieldCount++;
                return;
            } else if (tagName === "notebook") {
                // Skip notebooks - don't render them in preview
                return;
            } else if (tagName === "separator") {
                // Separator - skip if inside x2many
                if (insideX2Many) {
                    return;
                }
                const string = node.getAttribute("string") || "";
                html += `<div class="o_form_separator">`;
                if (string) {
                    html += `<span class="o_form_label">${this._escapeHtml(string)}</span>`;
                }
                html += `</div>`;
            } else if (tagName === "label") {
                // Label element - skip if inside x2many
                if (insideX2Many) {
                    return;
                }
                const string = node.getAttribute("string") || "";
                const forAttr = node.getAttribute("for") || "";
                html += `<label class="o_form_label"${forAttr ? ` for="${this._escapeHtml(forAttr)}"` : ''}>${this._escapeHtml(string)}</label>`;
            } else {
                // Continue traversing other nodes
                Array.from(node.children || []).forEach(child => visitAndRender(child, depth + 1, insideX2Many));
            }
        };
        
        // Start from root form element
        const formElement = xmlDoc.querySelector("form") || xmlDoc.documentElement;
        if (formElement) {
            visitAndRender(formElement);
        }
        
        // If no HTML generated, fallback to field list
        if (!html.trim() || fieldCount === 0) {
            return this._buildFieldsHtml(record, recordData);
        }
        
        return html;
    },

    _buildFieldsHtml(record, recordData) {
        const fields = this._getPreviewFields(record);
        const listFields = this.props.list.fields || {};
        
        return fields.map(fieldName => {
            const value = recordData[fieldName];
            const field = listFields[fieldName] || record.fields?.[fieldName];
            
            if (!field || (value === null && value === undefined && value !== false && field.type !== "boolean")) {
                return "";
            }
            
            const label = field.string || fieldName;
            const formattedValue = this._formatFieldValue(field, value);
            
            return `
                <div class="o_preview_field o_preview_form_field">
                    <label class="o_preview_field_label">${this._escapeHtml(label)}:</label>
                    <div class="o_preview_field_value">${this._escapeHtml(formattedValue)}</div>
                </div>
            `;
        }).filter(html => html.trim()).join("");
    },

    _openRecord(record) {
        // Open record in form view
        this.action.doAction({
            type: "ir.actions.act_window",
            res_model: this.props.list.resModel,
            res_id: record.resId,
            views: [[false, "form"]],
            target: "current",
        });
    },
});

// Make PreviewPopup available on ListRenderer
ListRenderer.PreviewPopup = PreviewPopup;


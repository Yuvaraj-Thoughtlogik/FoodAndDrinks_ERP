/** @odoo-module **/

import { KanbanRecord } from "@web/views/kanban/kanban_record";
import { patch } from "@web/core/utils/patch";
import { url } from "@web/core/utils/urls";
import { parseXML } from "@web/core/utils/xml";

patch(KanbanRecord.prototype, {
    setup() {
        super.setup(...arguments);
        this.previewPopup = null;
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
        
        // Get the button element for positioning
        const button = ev.currentTarget || ev.target;
        this._showPreview(record, button);
    },

    async _showPreview(record, targetElement) {
        try {
            console.log("Loading preview:", {
                resModel: this.props.list.resModel,
                resId: record.resId || record.data?.id,
                recordDisplayName: record.display_name || record.data?.display_name || record.data?.name,
                recordData: record.data
            });

            const resModel = this.props.list.resModel;
            const resId = record.resId || record.data?.id;
            
            if (!resModel || !resId) {
                console.warn("Preview: Missing resModel or resId", { resModel, resId });
                return;
            }

            // Load configuration for this model
            let config = null;
            try {
                const rpc = this.env.services.rpc;
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

            // Load form view to get fields that exist in the form
            const viewService = this.env.services.view;
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
            
            // Read record data
            const orm = this.env.services.orm;
            const recordData = await orm.read(resModel, [resId], fieldsToRead);
            
            if (!recordData || recordData.length === 0) {
                console.warn("Preview: No data returned for record", { resModel, resId });
                return;
            }

            const data = recordData[0];
            
            console.log("Record data keys:", Object.keys(data).length, Object.keys(data).slice(0, 20));
            
            // Create custom popup - use allFields to have access to all field definitions
            // Pass config to _createCustomPopup so it can use it
            this._createCustomPopup(record, data, allFields, targetElement, config);
        } catch (error) {
            console.error("Error loading preview:", error);
        }
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

    _createCustomPopup(record, recordData, fields, targetElement, config = null) {
        // Close existing popup if any
        this._closePreview();

        // Create popup container
        const popup = document.createElement("div");
        popup.className = "o_record_preview_popup";
        popup.style.position = "absolute";
        popup.style.zIndex = "9999";
        
        // Position popup near the button
        const rect = targetElement.getBoundingClientRect();
        const scrollTop = window.pageYOffset || document.documentElement.scrollTop;
        const scrollLeft = window.pageXOffset || document.documentElement.scrollLeft;
        
        // Position to the right of the button, or adjust if near screen edge
        let left = rect.right + scrollLeft + 10;
        let top = rect.top + scrollTop;
        
        // Adjust if too close to right edge
        if (left + 400 > window.innerWidth + scrollLeft) {
            left = rect.left + scrollLeft - 410; // Position to the left instead
        }
        
        // Adjust if too close to bottom edge
        if (top + 500 > window.innerHeight + scrollTop) {
            top = window.innerHeight + scrollTop - 520;
        }
        
        popup.style.left = `${left}px`;
        popup.style.top = `${top}px`;
        popup.style.display = "flex";
        popup.style.flexDirection = "column";

        // Build popup content
        const recordDisplayName = record.display_name || recordData.display_name || recordData.name || "Record";
        
        // Get image URL if available (only if config allows)
        const resModel = this.props.list.resModel;
        const resId = record.resId || recordData.id;
        const combinedRecordData = { ...(record.data || {}), ...recordData };
        const imageUrl = (config && config.show_image !== false) 
            ? this._getImageUrl(combinedRecordData, fields, resModel, resId)
            : null;
        
        // Build fields HTML with configuration
        const fieldsHtml = this._buildCustomFieldsHtml(recordData, fields, config);
        
        // Build image HTML if available
        const imageHtml = imageUrl ? `
            <div class="o_preview_popup_image">
                <img src="${this._escapeHtml(imageUrl)}" alt="${this._escapeHtml(recordDisplayName)}" />
            </div>
        ` : '';
        
        popup.innerHTML = `
            <div class="o_preview_popup_content">
                <div class="o_preview_popup_header">
                    <div class="o_preview_popup_title">${this._escapeHtml(recordDisplayName)}</div>
                    <button type="button" class="btn-close" aria-label="Close" title="Close (Esc)"></button>
                </div>
                ${imageHtml}
                <div class="o_preview_popup_body o_preview_custom_body">
                    <div class="o_preview_custom_fields">
                        ${fieldsHtml}
                    </div>
                </div>
                <div class="o_preview_popup_footer">
                    <button type="button" class="btn btn-primary btn-sm o_preview_open_btn">Open</button>
                </div>
            </div>
        `;

        // Add event listeners
        const closeBtn = popup.querySelector(".btn-close");
        const openBtn = popup.querySelector(".o_preview_open_btn");
        
        closeBtn.addEventListener("click", () => this._closePreview());
        openBtn.addEventListener("click", () => this._openRecord(record));
        
        // Close on Escape key
        const escapeHandler = (ev) => {
            if (ev.key === "Escape") {
                this._closePreview();
                document.removeEventListener("keydown", escapeHandler);
            }
        };
        document.addEventListener("keydown", escapeHandler);

        // Add to DOM
        document.body.appendChild(popup);
        this.previewPopup = popup;

        // Focus management
        popup.focus();
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
        let fieldsToShow = [];
        
        if (config && config.field_names && config.field_names.length > 0) {
            // Use configured fields + display_name if enabled
            fieldsToShow = [...config.field_names];
            if (config.show_display_name && !fieldsToShow.includes('display_name')) {
                fieldsToShow.push('display_name');
            }
        } else {
            // No config: use default behavior
            const priorityFields = ['name', 'display_name', 'state', 'date', 'date_order', 'partner_id', 'user_id', 'amount_total', 'price_total'];
            const fieldNames = new Set();
            
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
            fieldsToShow = Array.from(fieldNames);
        }
        
        // Build HTML for each field
        // If config specifies fields, show all configured fields (even if empty)
        // Otherwise, only show fields with values, then limit to 100
        const fieldsWithValues = fieldsToShow.map(fieldName => {
            const value = recordData[fieldName];
            const field = fields[fieldName];
            
            if (!field) {
                console.warn("Field not found in fields object:", fieldName);
                return null;
            }
            
            // Skip x2many fields
            if (field.type === "one2many" || field.type === "many2many") {
                return null;
            }
            
            // Skip JSON fields
            if (field.type === "json") {
                return null;
            }
            
            // Skip image fields (they're shown separately)
            if (fieldName.toLowerCase().includes('image')) {
                return null;
            }
            
            // Skip mixin fields
            if (this._isMixinField(fieldName)) {
                return null;
            }
            
            // If config specifies fields, show all configured fields (even if empty)
            // Otherwise, skip empty values
            if (!config || !config.field_names || config.field_names.length === 0) {
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
            }
            
            const label = field.string || fieldName;
            const formattedValue = this._formatFieldValue(field, value);
            
            // If config specifies fields, show "-" for empty values
            // Otherwise, skip empty formatted values
            if (!config || !config.field_names || config.field_names.length === 0) {
                if (!formattedValue || (typeof formattedValue === "string" && formattedValue.trim() === "")) {
                    return null;
                }
            }
            
            return {
                html: `
                    <div class="o_preview_custom_field">
                        <div class="o_preview_custom_field_label">${this._escapeHtml(label)}</div>
                        <div class="o_preview_custom_field_value">${formattedValue ? this._escapeHtml(formattedValue) : "-"}</div>
                    </div>
                `,
                fieldName: fieldName
            };
        }).filter(item => item !== null && item.html && typeof item.html === 'string' && item.html.trim());
        
        // Limit to 100 fields after filtering empty ones
        const limitedFields = fieldsWithValues.slice(0, 100);
        const fieldsHtml = limitedFields.map(item => item.html).join("");
        
        return fieldsHtml;
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

        // Handle many2one fields (can be array [id, name] or object {id, display_name})
        if (field.type === "many2one") {
            if (Array.isArray(value)) {
                return value[1] || value[0] || "";
            } else if (value && typeof value === "object") {
                return value.display_name || value.name || value.id || "";
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
        if (text === null || text === undefined) {
            return "";
        }
        const div = document.createElement("div");
        div.textContent = String(text);
        return div.innerHTML;
    },

    _closePreview() {
        if (this.previewPopup) {
            this.previewPopup.remove();
            this.previewPopup = null;
        }
    },

    _openRecord(record) {
        this._closePreview();
        if (this.props.openRecord) {
            this.props.openRecord(record);
        }
    },
});


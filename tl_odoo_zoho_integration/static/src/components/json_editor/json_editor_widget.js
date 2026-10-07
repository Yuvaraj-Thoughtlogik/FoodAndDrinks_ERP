/** @odoo-module **/
import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { Component, onMounted, onWillUnmount, useRef } from "@odoo/owl";


export class JsonEditorField extends Component {
    static template = "tl_odoo_zoho_integration.JsonEditorField";
    static props = {
        ...standardFieldProps,
    };
    setup() {
        this.containerRef = useRef("editorContainer");

        onMounted(() => {
            const container = this.containerRef.el;
            console.log(window.JSONEditor,'True')
            const options = {
                mode: 'form',
                modes: ['code', 'tree','form'],
                onEditable: () => false
            };
            let jsonText = this.props.record.data[this.props.name];
            let initialJson;

            try {
                initialJson = jsonText ? JSON.parse(jsonText) : {};
            } catch (err) {
                console.warn("Invalid JSON:", jsonText);
                initialJson = {};
            }
            this.initEditor(container, options,initialJson);
        });
    }

    initEditor(container, options, initialJson) {
        this.editor = new JSONEditor(container, options);
        this.editor.set(initialJson);
    }
}

export const jsonEditorField = {
    component: JsonEditorField,
    displayName: "JSON Editor",
    supportedTypes: ["text"],
    extractProps: ({ attrs }) => ({}),
};
registry.category("fields").add("json_editor_widget", jsonEditorField);

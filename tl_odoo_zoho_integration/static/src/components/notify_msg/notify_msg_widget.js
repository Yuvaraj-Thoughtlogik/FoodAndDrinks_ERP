/** @odoo-module **/

import { registry } from "@web/core/registry"
import { standardFieldsProps } from "@web/views/fields/standard_field_props"
import { Component, onMounted, onWillUnmount, useRef } from "@odoo/owl";


export class NotifyMessageField extends Component{
    static template = "tl_odoo_zoho_integration.NotifyMessage"
    static props ={
        ...standardFieldsProps,
    }
    setup(){
        let value = this.props.record.data[this.props.name];
        console.log(value)
    }
    get value() {
        return this.props.record.data[this.props.name];
    }
}


export const notifyMessageField ={
    component:NotifyMessageField,
    displayName:'Notify message',
    supportedTypes: ["text"],
    extractProps: ({ attrs }) => ({}),
}
registry.category("fields").add("notify_msg_widget", notifyMessageField);

/** @odoo-module **/

import { registry } from "@web/core/registry";

registry.category("actions").add("print_and_open_lines", async (env, action) => {
    const { report_action, lines_action } = action.params || {};
    if (report_action) {
        await env.services.action.doAction(report_action);
    }
    if (lines_action) {
        await env.services.action.doAction(lines_action);
    }
});

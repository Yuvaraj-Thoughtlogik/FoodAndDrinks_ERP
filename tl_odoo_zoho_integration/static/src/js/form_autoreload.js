/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { FormController } from "@web/views/form/form_controller";

patch(FormController.prototype, {
    async onRecordSaved(record) {
        const res = await super.onRecordSaved(...arguments);
        try {
            const root = this.model.root;
            if (root.resModel === "zoho.config.module") {
                console.log("📌 Reloading zoho.config.module form...");

                let url = window.location.href;
                let resId = root.resId;
                let newUrl = url.replace("/new", "/" + resId);

                console.log("✅ Form reloaded");
                window.location.href = newUrl;
            }
        } catch (err) {
            console.error("❌ Error in auto-reload patch:", err);
        }
        return res;
    },
});

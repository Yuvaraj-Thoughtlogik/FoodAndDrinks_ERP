/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { actionService } from "@web/webclient/actions/action_service";
import { ListArchParser } from "@web/views/list/list_arch_parser";

const QUICK_VIEW_NAMES = [
    "quick_view",
    "quick_preview",
    "action_quick_view",
    "action_quick_preview",
];

// Patch actionService to open the modal form view on quick_view button click
patch(actionService, {
    start(env) {
        const actionManager = super.start(...arguments);
        const originalDoActionButton = actionManager.doActionButton;

        actionManager.doActionButton = async function (params, options) {
            const isQuickView =
                QUICK_VIEW_NAMES.includes(params.name) ||
                QUICK_VIEW_NAMES.includes(params.special) ||
                params.special === "quick_view" ||
                params.special === "quick_preview" ||
                params.type === "quick_view";

            if (isQuickView) {
                if (params.resModel && params.resId) {
                    return await actionManager.doAction({
                        name: params.string || "Quick Preview",
                        res_model: params.resModel,
                        res_id: params.resId,
                        type: "ir.actions.act_window",
                        views: [[false, "form"]],
                        target: "new",
                        context: params.context || {},
                    });
                }
            }
            return originalDoActionButton.call(this, params, options);
        };

        return actionManager;
    },
});

// Patch ListArchParser so button columns can display their string/label in the table header
patch(ListArchParser.prototype, {
    parse() {
        const archInfo = super.parse(...arguments);
        for (const col of archInfo.columns) {
            if (col.type === "button_group" && col.buttons && col.buttons.length) {
                const btnWithLabel = col.buttons.find(
                    (b) => b.string || b.title || b.attrs?.string || b.attrs?.title
                );
                if (btnWithLabel) {
                    col.label =
                        btnWithLabel.string ||
                        btnWithLabel.title ||
                        btnWithLabel.attrs?.string ||
                        btnWithLabel.attrs?.title;
                    col.hasLabel = true;
                }
            }
        }
        return archInfo;
    },
});

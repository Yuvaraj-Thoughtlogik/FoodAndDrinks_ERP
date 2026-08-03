import { patch } from "@web/core/utils/patch";
import { ListRenderer } from "@web/views/list/list_renderer";

patch(ListRenderer.prototype, {
    async onEyeCellClicked(record, column, ev) {
        this.env.services.action.doAction({
            res_model: record.resModel,
            res_id: record.resId,
            type: "ir.actions.act_window",
            views: [[false, "form"]],
            target: 'new'
        });
    },
});

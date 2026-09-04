/** @odoo-module **/

import { Component } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { browser } from "@web/core/browser/browser";
import { useService } from "@web/core/utils/hooks";
import { standardWidgetProps } from "@web/views/widgets/standard_widget_props";

/**
 * "Design with Studio" button.
 *
 * The point of doing this in javascript rather than with a plain
 * ``type="object"`` button is the breadcrumb: the studio URL is *appended* to
 * the path the user is currently on, e.g.
 *
 *     /odoo/action-714/7
 *  -> /odoo/action-714/7/action-735/new/studio?debug=1&mode=editor&...
 *
 * so the configuration record stays behind Studio and closing Studio comes
 * back to it instead of dumping the user on the popup action alone.
 */
export class StudioDesignButton extends Component {
    static template = "tl_list_dynamic_filter_studio.StudioDesignButton";
    static props = { ...standardWidgetProps };

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");
    }

    get record() {
        return this.props.record;
    }

    async onClick() {
        const root = this.record.model.root;

        // Full page navigation follows, so nothing unsaved may be left behind.
        if (root.isDirty || !root.resId) {
            const saved = await root.save();
            if (!saved) {
                return;
            }
        }

        // Server side: make sure the page action exists, flag the config as
        // Studio designed, and hand back the relative URL piece.
        const suffix = await this.orm.call(
            this.record.resModel,
            "prepare_studio_url",
            [[root.resId]]
        );
        if (!suffix) {
            return;
        }

        const path = browser.location.pathname.replace(/\/+$/, "");
        browser.location.href = `${path}/${suffix}`;
    }
}

export const studioDesignButton = {
    component: StudioDesignButton,
};

registry.category("view_widgets").add("tl_studio_design_button", studioDesignButton);

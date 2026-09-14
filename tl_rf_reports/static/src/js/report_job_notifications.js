/** @odoo-module **/

import { registry } from "@web/core/registry";
import { _t } from "@web/core/l10n/translation";

/**
 * Listens for `tl_rf_reports.report_job_update` bus notifications sent by
 * tl.report.generation.job (see models/report_job.py) and shows a toast, the
 * same way a browser's own download manager tells you a download finished:
 * - done: a sticky success toast with a "Download" button that opens the PDF.
 * - failed: a sticky error toast with the failure reason.
 * Queued/processing updates are ignored here; they are only meaningful in the
 * "My Report Jobs" list (Reporting > My Report Jobs).
 */
export const reportJobNotificationsService = {
    dependencies: ["bus_service", "notification"],
    start(env, { bus_service, notification: notificationService }) {
        bus_service.subscribe("tl_rf_reports.report_job_update", (payload) => {
            const { name, state, attachment_id, error_message } = payload || {};
            if (state === "done") {
                notificationService.add(
                    _t('"%s" is ready.', name),
                    {
                        title: _t("Report ready to download"),
                        type: "success",
                        sticky: true,
                        buttons: [
                            {
                                name: _t("Download"),
                                primary: true,
                                onClick: () => {
                                    window.location = `/web/content/${attachment_id}?download=true`;
                                },
                            },
                        ],
                    }
                );
            } else if (state === "failed") {
                notificationService.add(
                    error_message || _t("An unexpected error occurred."),
                    {
                        title: _t('"%s" failed to generate', name),
                        type: "danger",
                        sticky: true,
                    }
                );
            }
        });
        bus_service.start();
    },
};

registry.category("services").add("tl_rf_reports.report_job_notifications", reportJobNotificationsService);

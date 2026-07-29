/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { CharField } from "@web/views/fields/char/char_field";
import { rpc } from "@web/core/network/rpc";

patch(CharField.prototype, {

    async onChange(ev) {
        await super.onChange(...arguments);

        // Only for Partner ZIP field
        if (
            this.props.name !== "zip" ||
            this.props.record.resModel !== "res.partner"
        ) {
            return;
        }

        const postcode = this.props.record.data.zip;

        if (!postcode || postcode.length < 5) {
            return;
        }

        try {

            const result = await rpc(
                "/uk_postcode_lookup/search",
                {
                    postcode: postcode,
                    model: "res.partner",
                    res_id: this.props.record.resId || false,
                }
            );

            if (!result) {
                return;
            }

            //-----------------------------------------
            // Single Address
            //-----------------------------------------

            if (result.type === "single") {

                await this.props.record.update({

                    street: result.values.street,
                    street2: result.values.street2,
                    city: result.values.city,
                    zip: result.values.postcode,
                    country_id: result.values.country_id,
                    state_id: result.values.state_id,

                });

                return;
            }

            //-----------------------------------------
            // Multiple Addresses
            //-----------------------------------------

            if (result.type === "multiple") {

                this.env.services.action.doAction(
                    result.action
                );

            }

        }
        catch (error) {
            console.error("Postcode lookup failed", error);
        }

    },

});

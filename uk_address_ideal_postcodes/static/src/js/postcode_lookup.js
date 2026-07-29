/** @odoo-module **/

import { registry } from "@web/core/registry";
import { rpc } from "@web/core/network/rpc";
import { patch } from "@web/core/utils/patch";
import { FormController } from "@web/views/form/form_controller";

patch(FormController.prototype, {

    async onRecordSaved(record) {
        await super.onRecordSaved(...arguments);
    },

    async postcodeLookup(postcode) {

        if (!postcode){
            return;
        }

        postcode = postcode.trim().toUpperCase();

        const result = await rpc(
            "/uk_postcode_lookup/search",
            {
                postcode: postcode,
                model: this.props.resModel,
                res_id: this.model.root.resId,
            }
        );

        if (!result){
            return;
        }

        

        if(result.type==="single"){

            const values=result.values;

            await this.model.root.update({

                street: values.street,
                street2: values.street2,
                city: values.city,
                zip: values.postcode,
                state_id: values.state_id,
                country_id: values.country_id,

            });

            return;
        }

        

        this.actionService.doAction(result.action);

    },

});

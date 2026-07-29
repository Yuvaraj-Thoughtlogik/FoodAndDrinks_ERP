/** @odoo-module **/

import { registry } from "@web/core/registry";
import { CharField } from "@web/views/fields/char/char_field";
import { useService } from "@web/core/utils/hooks";
import { onMounted } from "@odoo/owl";


export class PostcodeLookupField extends CharField {

    setup() {

        super.setup();

        this.rpc = useService("rpc");
        this.action = useService("action");

        onMounted(() => {
            console.log(
                "UK Postcode Lookup Widget Loaded"
            );
        });
    }


    async onInput(ev) {

        await super.onInput(ev);


        const postcode =
            this.props.record.data[this.props.name];


        if (!postcode) {
            return;
        }


        postcode = postcode.trim().toUpperCase();


        // UK postcode minimum length

        if (postcode.length < 5) {
            return;
        }


        console.log(
            "Searching postcode:",
            postcode
        );


        try {

            const result =
                await this.rpc(
                    "/uk_postcode_lookup/search",
                    {
                        postcode: postcode,
                        model: "res.partner",
                        res_id:
                            this.props.record.resId,
                    }
                );


            console.log(
                "Lookup result:",
                result
            );


            if (!result) {
                return;
            }


            // ----------------------------
            // Single Address
            // ----------------------------

            if (result.type === "single") {


                await this.props.record.update({

                    street:
                        result.values.street,

                    street2:
                        result.values.street2,

                    city:
                        result.values.city,

                    zip:
                        result.values.postcode,

                    country_id:
                        result.values.country_id,

                    state_id:
                        result.values.state_id,

                });


            }


            // ----------------------------
            // Multiple Address
            // ----------------------------

            if (result.type === "multiple") {


                this.action.doAction(
                    result.action
                );

            }


        }
        catch(error){

            console.error(
                "UK Postcode Error",
                error
            );

        }

    }

}


// Register widget

registry.category("fields").add(
    "postcode_lookup",
    {
        component:
            PostcodeLookupField,

        supportedTypes:
            ["char"],
    }
);

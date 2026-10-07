import logging
from odoo import models, fields, api, _

_logger = logging.getLogger(__name__)

class BigCommerceCustomerBinding(models.Model):
    """Maps Odoo partners to BigCommerce customer records."""

    _name = "bigcommerce.customer.binding"
    _description = "BigCommerce Customer Binding"
    _rec_name = "email"
    _order = "id desc"

    instance_id = fields.Many2one(
        "bigcommerce.connector",
        string="BigCommerce Store",
        required=True,
        ondelete="cascade",
        index=True,
    )
    partner_id = fields.Many2one(
        "res.partner",
        string="Odoo Customer",
        index=True,
        ondelete="set null",
    )
    bigcommerce_customer_id = fields.Char(
        string="BigCommerce Customer ID",
        copy=False,
        index=True,
    )
    email = fields.Char(
        related="partner_id.email",
        store=True,
        readonly=False,
        index=True,
    )
    phone = fields.Char(
        related="partner_id.phone",
        store=True,
        readonly=True,
    )
    sync_to_bigcommerce = fields.Boolean(
        string="Sync to BigCommerce",
        default=True,
    )
    sync_state = fields.Selection(
        [
            ("draft", "Draft"),
            ("synced", "Synced"),
            ("error", "Error"),
        ],
        default="draft",
        required=True,
        index=True,
    )
    last_synced_at = fields.Datetime(index=True)
    last_error = fields.Text()

    _sql_constraints = [
        (
            "bigcommerce_customer_binding_customer_uniq",
            "unique(instance_id, bigcommerce_customer_id)",
            "BigCommerce customer id must be unique per instance.",
        )
    ]

    def _export_single_partner_to_bigcommerce(self):
        """Export single partner record to BigCommerce v3 Customer API."""
        self.ensure_one()
        partner = self.partner_id
        instance = self.instance_id

        if not partner or not instance or not partner.email:
            _logger.warning(
                "Skipping BigCommerce sync for binding %s: "
                "Partner, instance, or email missing.",
                self.id,
            )
            return False

        name_parts = (partner.name or '').strip().split(' ', 1)
        first_name = name_parts[0] if name_parts else 'Customer'
        last_name = name_parts[1] if len(name_parts) > 1 else first_name

        payload = [{
            "email": partner.email,
            "first_name": first_name,
            "last_name": last_name,
            "company": partner.company_name or partner.parent_id.name or "",
            "phone": partner.phone or partner.mobile or "",
        }]

        if self.bigcommerce_customer_id:
            # Update Existing Customer in BigCommerce
            payload[0]["id"] = int(self.bigcommerce_customer_id)
            res = instance.api_request("customers", method='PUT', payload=payload)
            # Sync primary address if address info is available
            self._export_partner_address_to_bigcommerce(instance, self.bigcommerce_customer_id)
        else:
            # Create New Customer in BigCommerce
            res = instance.api_request("customers", method='POST', payload=payload)
            if res and isinstance(res, dict) and res.get('data'):
                bc_id = str(res['data'][0]['id'])
                self.with_context(skip_bc_sync=True).write({
                    'bigcommerce_customer_id': bc_id,
                    'bigcommerce_instance_id': instance.id,
                })
                # Sync primary address after customer creation
                self._export_partner_address_to_bigcommerce(instance, bc_id)

    def _export_partner_address_to_bigcommerce(self, instance, bc_customer_id):
        """Creates or updates primary address record for BigCommerce Customer safely."""
        partner = self.partner_id

        # BigCommerce requires street, city, and country_code for addresses.
        if not partner or not partner.street or not partner.city or not partner.country_id:
            _logger.info(
                "Skipping address creation for customer %s: "
                "Missing street, city, or country.",
                bc_customer_id,
            )
            return

        name_parts = (partner.name or "").strip().split(" ", 1)

        address_payload = [{
            "address1": partner.street or "",
            "address2": partner.street2 or "",
            "city": partner.city,
            "country_code": partner.country_id.code or "",
            "state_or_province": partner.state_id.name if partner.state_id else "",
            "postal_code": partner.zip or "",
            "first_name": name_parts[0] if name_parts else "Customer",
            "last_name": name_parts[1] if len(name_parts) > 1 else (name_parts[0] if name_parts else "Customer"),
            "phone": partner.phone or partner.mobile or "",
            "customer_id": int(bc_customer_id),
        }]

        try:
            instance.api_request("customers/addresses", method='POST', payload=address_payload)
        except Exception as e:
            _logger.error("Failed to sync customer address to BigCommerce for BC ID %s: %s", bc_customer_id, str(e))


    # -------------------------------------------------------------------------
    # MANUAL SYNC
    # -------------------------------------------------------------------------

    def action_sync_to_bigcommerce(self):
        success_count = 0
        failed_count = 0

        for binding in self:
            try:
                binding._export_single_partner_to_bigcommerce()
                success_count += 1
            except Exception:
                failed_count += 1

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("BigCommerce Customer Sync"),
                "message": _(
                    "Synced: %s | Failed: %s"
                ) % (success_count, failed_count),
                "sticky": False,
                "type": "warning" if failed_count else "success",
            },
        }

    # -------------------------------------------------------------------------
    # BULK EXPORT: ODOO -> BIGCOMMERCE
    # -------------------------------------------------------------------------
    def action_bulk_export_customers_to_bigcommerce(self):
        """Action for selected partners in ListView to push to BigCommerce."""
        success_count = 0
        skipped_count = 0

        for binding in self:
            partner = binding.partner_id

            if partner and partner.email:
                try:
                    binding._export_single_partner_to_bigcommerce()
                    success_count += 1
                except Exception as error:
                    _logger.error(
                        "Bulk export failed for binding ID %s: %s",
                        binding.id,
                        str(error),
                    )
                    binding.with_context(skip_bc_sync=True).write({
                        "sync_state": "error",
                        "last_error": str(error),
                    })
            else:
                skipped_count += 1

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _("BigCommerce Customer Sync"),
                'message': _("Successfully synced %s customers (%s skipped due to missing email or vendor status).") % (success_count, skipped_count),
                'sticky': False,
            }
        }

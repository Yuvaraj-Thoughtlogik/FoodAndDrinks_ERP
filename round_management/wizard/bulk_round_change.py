from odoo import models, fields, api


class WizardBulkRoundChange(models.TransientModel):
    _name = 'wizard.bulk.round.change'
    _description = 'Bulk Move Customers to New Round'

    old_round_id = fields.Many2one('round.management.round', string='Old Round')
    new_round_id = fields.Many2one('round.management.round', string='New Round')
    include_inactive = fields.Boolean(
        string='Include Inactive & Closed Customers', 
        default=False
    )

    partner_ids = fields.Many2many(
        'res.partner',
        string='Customers',
        domain="[('id', 'in', available_partner_ids)]"
    )

    available_partner_ids = fields.Many2many(
        'res.partner',
        string='Available Customers',
        compute='_compute_available_partners'
    )

    @api.depends('include_inactive')
    def _compute_available_partners(self):
        """Filters available customers based on the checkbox selection."""
        for wizard in self:
            if wizard.include_inactive:
                # Search for inactive customers OR customers with flag 'I' or 'X'
                # Adjust 'customer_flag' to match your actual custom field name on res.partner
                domain = ['|', '|', 
                    ('active', '=', False), 
                    ('customer_flag', 'in', ['I', 'X']),
                    ('active', '=', True)
                ]
            else:
                # Default: Show active customers excluding 'I' and 'X' flags
                domain = [
                    ('active', '=', True), 
                    ('customer_flag', 'not in', ['I', 'X'])
                ]

            # Use active_test=False to allow Odoo ORM to search unactive/archived records
            partners = self.env['res.partner'].with_context(active_test=False).search(domain)
            wizard.available_partner_ids = partners

    line_ids = fields.One2many(
        'wizard.bulk.round.change.line',
        'wizard_id',
        string='Customers to Move'
    )

    @api.onchange('old_round_id', 'include_inactive')
    def _onchange_old_round_id(self):
        """
        UNCHECKED: Excludes Inactive (I) and Closed (X) customers. Shows normal active list only.
        CHECKED:   Includes ALL customers, adding Inactive (I) and Closed (X) to the list.
        """
        
        self.line_ids = [(5, 0, 0)]
 
        if not self.old_round_id:
            return
 
        base_domain = [('round_id', '=', self.old_round_id.id)]
 
        if self.include_inactive:
           
            Partner = self.env['res.partner'].with_context(active_test=False)
            domain = base_domain
        else:
            
            Partner = self.env['res.partner']
            domain = base_domain + [
                ('customer_lifecycle_status', 'not in', ['inactive', 'closed'])
            ]
 
        partners = Partner.search(domain)
 
        lines = [(0, 0, {
            'selected': False,
            'partner_id': partner.id,
        }) for partner in partners]
 
        self.line_ids = lines

    def action_select_all(self):
        """Selects all target lines and keeps the wizard open with populated data."""
        self.ensure_one()
        for line in self.line_ids:
            line.selected = True
        
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def action_deselect_all(self):
        """Deselects all target lines and keeps the wizard open with populated data."""
        self.ensure_one()
        for line in self.line_ids:
            line.selected = False

        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def process_round_change(self):
        """Transfers selected customers and opens a summary popup dialog."""
        self.ensure_one()
        selected_partners = self.line_ids.filtered(lambda l: l.selected).mapped('partner_id')
        count = len(selected_partners)

        if count > 0 and self.new_round_id:
            old_name = self.old_round_id.display_name or 'Old Round'
            new_name = self.new_round_id.display_name or 'New Round'

            # Update round on selected customers
            selected_partners.write({'round_id': self.new_round_id.id})

            # Create summary dialog record using .sudo() to avoid Access Error
            summary = self.env['wizard.bulk.round.summary'].sudo().create({
                'transferred_count': count,
                'old_round_name': old_name,
                'new_round_name': new_name,
                'message': f"Successfully transferred {count} customer(s) from '{old_name}' to '{new_name}'."
            })

            # Open Summary Popup
            return {
                'name': 'Transfer Summary',
                'type': 'ir.actions.act_window',
                'res_model': 'wizard.bulk.round.summary',
                'res_id': summary.id,
                'view_mode': 'form',
                'target': 'new',
            }

        # Warning notification if no customers selected
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'No Customers Selected',
                'message': 'Please select at least one customer to transfer.',
                'type': 'warning',
                'sticky': False,
            }
        }


class WizardBulkRoundChangeLine(models.TransientModel):
    _name = 'wizard.bulk.round.change.line'
    _description = 'Wizard Bulk Round Change Line'

    wizard_id = fields.Many2one('wizard.bulk.round.change', ondelete='cascade')
    partner_id = fields.Many2one('res.partner', string='Customer', required=True)

    selected = fields.Boolean(string='Selected', default=False)
    
    # Safe computed field instead of related
    customer_code = fields.Char(string='Customer Code', compute='_compute_partner_details', store=True)
    
    phone = fields.Char(related='partner_id.phone', string='Phone', store=True, readonly=True)
    city = fields.Char(related='partner_id.city', string='City', store=True, readonly=True)
    
    # Address Details
    house_no = fields.Char(related='partner_id.street2', string='House No', store=True, readonly=True)
    street = fields.Char(related='partner_id.street', string='Street', store=True, readonly=True)
    zip = fields.Char(related='partner_id.zip', string='Postcode', store=True, readonly=True)

    # Full Customer Status Description
    customer_lifecycle_status = fields.Selection([
        ("new", "New"),
        ("ftlt", "FTLT"),
        ("main_customer", "Main Customer"),
        ("old_ftlt", "Old FTLT"),
        ("dormant", "Dormant"),
        ("inactive", "Inactive"),
        ("cancelled_ftlt", "Cancelled FTLT"),
        ("closed", "Closed"),
    ], string="Customer Status", compute="_compute_partner_details", store=True)

    # Single-letter code string
    status_code = fields.Char(string='Status', compute='_compute_partner_details', store=True)
    
    
    @api.onchange('partner_id')
    def _onchange_partner_id(self):
        """Fetch customer code automatically when partner is selected."""
        for line in self:
            if line.partner_id:
                # 1. First check custom 'customer_code' field on partner
                # 2. Fall back to native 'ref' field if 'customer_code' is empty
                line.customer_code = getattr(line.partner_id, 'customer_code', False) or line.partner_id.ref or ''
            else:
                line.customer_code = ''

    @api.depends('partner_id')
    def _compute_partner_details(self):
        mapping = {
            'new': 'N',
            'ftlt': 'F',
            'cancelled_ftlt': 'C',
            'dormant': 'D',
            'inactive': 'I',
            'main_customer': 'M',
            'old_ftlt': 'O',
            'closed': 'X',
        }
        for line in self:
            if line.partner_id:
                # Force context to read archived/inactive partner fields
                partner = line.partner_id.with_context(active_test=False)
                line.customer_code = getattr(partner, 'customer_code', partner.ref or '')
                status = getattr(partner, 'customer_lifecycle_status', False)

                if status == 'closed':
                    line.customer_lifecycle_status = 'closed'
                    line.status_code = 'X'
                elif not partner.active or status == 'inactive':
                    line.customer_lifecycle_status = 'inactive'
                    line.status_code = 'I'
                else:
                    line.customer_lifecycle_status = status
                    line.status_code = mapping.get(status, '')
            else:
                line.customer_code = ''
                line.customer_lifecycle_status = False
                line.status_code = ''



class WizardBulkRoundSummary(models.TransientModel):
    _name = 'wizard.bulk.round.summary'
    _description = 'Customer Transfer Summary Popup'

    transferred_count = fields.Integer(string='Transferred Customers Count', readonly=True)
    old_round_name = fields.Char(string='Old Round', readonly=True)
    new_round_name = fields.Char(string='New Round', readonly=True)
    message = fields.Text(string='Details', readonly=True)


class BulkRoundChangeWizard(models.TransientModel):
    _name = 'bulk.round.change.wizard'
    _description = 'Bulk Change Round Wizard for Sale Orders'

    round_id = fields.Many2one('round.management.round', string='New Round', required=True)

    def action_apply_round_change(self):
        active_ids = self.env.context.get('active_ids', [])
        if active_ids:
            orders = self.env['sale.order'].browse(active_ids)
            orders.write({'round_id': self.round_id.id})
        return {'type': 'ir.actions.act_window_close'}

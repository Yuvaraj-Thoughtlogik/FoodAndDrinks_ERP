from odoo import api, fields, models


class ListFilterConfiguration(models.Model):
    _name = 'list.filter.configuration'
    _description = 'List Date Filter Configuration'

    name = fields.Char(required=True)

    model_id = fields.Many2one(
        comodel_name='ir.model',
        string="Model",
        required=True,
        domain="[('transient','=',False)]",
        ondelete='cascade',
    )

    create_button = fields.Boolean(default=True)
    model_name = fields.Char(
        related='model_id.model',
        store=False,
    )
    view_id = fields.Many2one(
        'ir.ui.view',
        string="List View",
        domain="[('model', '=', model_name), ('type', '=', 'list'),('inherit_id', '=', False)]",
    )

    created_view_id = fields.Many2one(
        'ir.ui.view',
        string="Created View",
        readonly=True,
        ondelete='cascade',
    )

    date_field_id = fields.Many2one(
        'ir.model.fields',
        string="Date Field",
        domain="[('model_id','=',model_id),('ttype','in',['date','datetime'])]",
        required=True,
        ondelete='cascade',
    )

    server_action_id = fields.Many2one(
        'ir.actions.server',
        string="Server Action",
        readonly=True,
        ondelete='cascade',
    )


    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)

        for rec in records:

            # Create Server Action
            action = self.env['ir.actions.server'].create({
                'name': f'{rec.name}.{rec.model_id.model}.actions.server',
                'model_id': rec.model_id.id,
                'binding_model_id': rec.model_id.id,
                'binding_view_types': 'list',
                'state': 'code',
                'code': f"""
action = env['list.filter.configuration'].browse({rec.id}).open_filter_wizard()
                """,
            })

            rec.server_action_id = action.id
            action = self.env.ref(
                'tl_list_date_filter.action_list_date_filter_wizard'
            )
            if rec.create_button:
                if "<header" in rec.view_id.arch_db:
                    arch = f"""
<xpath expr="//list/header" position="inside">
    <button
        string="{rec.name}"
        type="action"
        name="{action.id}"
        display='always'
        class="btn btn-primary"
        context="{{'default_config_id': {rec.id}}}"/>
</xpath>
                    """
                else:
                    arch = f"""
<xpath expr="//list" position="inside">
    <header>
            <button
        string="{rec.name}"
        type="action"
        name="{action.id}"
        display='always'
        class="btn btn-primary"
        context="{{'default_config_id': {rec.id}}}"/>
    </header>
</xpath>
                    """

                view = self.env['ir.ui.view'].create({
                    'name': f'{rec.model_id.model}.date.filter',
                    'type': 'list',
                    'model': rec.model_id.model,
                    'mode': 'extension',
                    'inherit_id': rec.view_id.id,
                    'arch': arch,
                })

                rec.created_view_id = view.id

        return records

    def write(self, vals):
        res = super().write(vals)

        for rec in self:
            if rec.created_view_id and 'name' in vals:
                action = self.env.ref(
                    'tl_list_date_filter.action_list_date_filter_wizard'
                )

                if "<header" in rec.view_id.arch_db:
                    arch = f"""
    <xpath expr="//list/header" position="inside">
        <button
            string="{rec.name}"
            type="action"
            name="{action.id}"
            display="always"
            class="btn btn-primary"
            context="{{'default_config_id': {rec.id}}}"/>
    </xpath>
    """
                else:
                    arch = f"""
    <xpath expr="//list" position="inside">
        <header>
            <button
                string="{rec.name}"
                type="action"
                name="{action.id}"
                display="always"
                class="btn btn-primary"
                context="{{'default_config_id': {rec.id}}}"/>
        </header>
    </xpath>
    """

                rec.created_view_id.write({
                    'arch': arch,
                })

        return res
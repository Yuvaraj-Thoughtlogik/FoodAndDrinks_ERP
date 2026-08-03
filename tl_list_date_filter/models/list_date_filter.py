from odoo import api, fields, models


class ListFilterConfiguration(models.Model):
    _name = 'list.filter.configuration'
    _description = 'List Date Filter Configuration'

    name = fields.Char(required=True,string="Button Name")

    model_id = fields.Many2one(
        comodel_name='ir.model',
        string="Model",
        required=True,
        domain="[('transient','=',False)]",
        ondelete='cascade',
    )

    model_name = fields.Char(
        related='model_id.model',
        store=False,
        string="Model Name"
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
        copy =False,
    )

    date_field_id = fields.Many2one(
        'ir.model.fields',
        string="Date Field",
        domain="[('model_id','=',model_id),('ttype','in',['date','datetime'])]",
        required=True,
        ondelete='cascade',
    )




    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._create_or_update_view()
        return records

    def write(self, vals):
        res = super().write(vals)

        self._create_or_update_view()

        return res

    def unlink(self):
        self.mapped('created_view_id').unlink()
        return super().unlink()

    def _create_or_update_view(self):
        action = self.env.ref(
            'tl_list_date_filter.action_list_date_filter_wizard'
        )

        for rec in self:
            view_data = self.env[rec.model_id.model].get_view(
                view_id=rec.view_id.id,
                view_type='list'
            )
            combined_arch = view_data['arch']

            if "<header" in combined_arch:
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
            values = {
                'name': f'{rec.model_id.model}.date.filter',
                'type': 'list',
                'model': rec.model_id.model,
                'mode': 'extension',
                'inherit_id': rec.view_id.id,
                'arch': arch,
            }

            if rec.created_view_id:
               rec.created_view_id.write(values)
            else:
                rec.created_view_id = self.env['ir.ui.view'].create([values])
from odoo import api, fields, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    first_name = fields.Char('First Name')
    last_name = fields.Char('Last Name')

    @api.onchange('first_name', 'last_name')
    def _onchange_full_name(self):
        for rec in self:
            full = ' '.join(filter(None, [rec.first_name, rec.last_name]))
            if full:
                rec.name = full

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            fn = vals.get('first_name') or ''
            ln = vals.get('last_name') or ''
            full = ' '.join(filter(None, [fn, ln]))
            if full:
                vals['name'] = full
        return super().create(vals_list)

    def write(self, vals):
        result = super().write(vals)
        if 'first_name' in vals or 'last_name' in vals:
            for rec in self:
                fn = rec.first_name or ''
                ln = rec.last_name or ''
                full = ' '.join(filter(None, [fn, ln]))
                if full:
                    super(ResPartner, rec).write({'name': full})
        return result

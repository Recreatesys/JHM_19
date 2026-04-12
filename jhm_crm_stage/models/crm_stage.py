from odoo import fields, models


class CrmStage(models.Model):
    _inherit = 'crm.stage'

    company_id = fields.Many2one(
        'res.company',
        string='Company',
        index=True,
        help='If set, this stage is only available for leads/opportunities in this company.',
    )

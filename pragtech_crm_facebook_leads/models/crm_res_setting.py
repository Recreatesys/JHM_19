from odoo import models, fields

class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    fb_lead_create_as_opportunity = fields.Boolean(
        string="Create Leads as Opportunities for Facebook",
        config_parameter='crm.fb_lead_create_as_opportunity'
    )

from odoo import fields, models, _


class SocailDashboard(models.Model):
    _name = "facebook.socail.dashboard"
    _description = "Social Dashboard"

    name = fields.Char()


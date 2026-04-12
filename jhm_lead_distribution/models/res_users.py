from odoo import fields, models


class ResUsers(models.Model):
    _inherit = 'res.users'

    skip_auto_assignment = fields.Boolean(
        'Skip Auto Assignment',
        default=False,
        help='If ticked, this user will be excluded from automatic lead assignment.',
    )

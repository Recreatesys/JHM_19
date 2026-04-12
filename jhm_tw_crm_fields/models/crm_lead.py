from odoo import api, fields, models


class CrmLead(models.Model):
    _inherit = 'crm.lead'

    # Visibility helper — True when the lead belongs to JHM Taiwan
    is_tw_company = fields.Boolean(
        compute='_compute_is_tw_company',
        string='Is JHM Taiwan',
    )

    # Follow-up notes (long text)
    tw_followup_1 = fields.Text('1st Follow-up Date')
    tw_followup_2 = fields.Text('2nd Follow-up Date')
    tw_followup_3 = fields.Text('3rd Follow-up Date')
    tw_followup_4 = fields.Text('4th Follow-up Date')

    # Checkboxes
    tw_call_connected = fields.Boolean('Call Connected')
    tw_added_on_line = fields.Boolean('Added on LINE')
    tw_email_sent = fields.Boolean('Email Sent')
    tw_group_created = fields.Boolean('Group Created')

    # Contact preference
    tw_preferred_contact_time = fields.Char('Preferred Contact Time')

    @api.depends('company_id')
    def _compute_is_tw_company(self):
        tw = self.env['res.company'].search(
            [('name', '=', 'JHM Taiwan')], limit=1
        )
        for rec in self:
            rec.is_tw_company = rec.company_id == tw

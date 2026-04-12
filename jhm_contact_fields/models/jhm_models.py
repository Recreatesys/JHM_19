from odoo import fields, models, api


class JhmBackground(models.Model):
    _name = 'jhm.background'
    _description = 'JHM Background'
    _order = 'name'

    name = fields.Char('Name', required=True)


class JhmVisaProgram(models.Model):
    _name = 'jhm.visa.program'
    _description = 'JHM Visa Program'
    _order = 'name'

    name = fields.Char('Name', required=True)


class JhmNationality(models.Model):
    _name = 'jhm.nationality'
    _description = "JHM Client Nationality"
    _order = 'name'

    name = fields.Char('Name', required=True)


class JhmCommunicationChannel(models.Model):
    _name = 'jhm.communication.channel'
    _description = 'JHM Communication Channel'
    _order = 'name'

    name = fields.Char('Name', required=True)


class JhmLeadSource(models.Model):
    _name = 'jhm.lead.source'
    _description = 'JHM Lead Source'
    _order = 'name'

    name = fields.Char('Name', required=True)


class JhmCoOwnerLog(models.Model):
    """Audit log for co-owner additions — used by the Daily Sales Report
    to count '#Support (Manager/Consultant)' per salesperson per day."""
    _name = 'jhm.co.owner.log'
    _description = 'JHM Co-Owner Change Log'
    _order = 'log_date desc'

    lead_id = fields.Many2one('crm.lead', string='Opportunity', ondelete='cascade', index=True)
    lead_user_id = fields.Many2one('res.users', string='Salesperson', ondelete='set null', index=True)
    added_count = fields.Integer('Co-owners Added', default=1)
    log_date = fields.Date('Date', default=fields.Date.today, index=True)

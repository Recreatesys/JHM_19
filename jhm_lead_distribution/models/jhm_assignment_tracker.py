from odoo import fields, models, api


class JhmAssignmentTracker(models.Model):
    """Singleton that tracks round-robin state for lead auto-assignment.
    One record per company."""
    _name = 'jhm.assignment.tracker'
    _description = 'Lead Assignment Round-Robin Tracker'

    company_id = fields.Many2one('res.company', string='Company', required=True)
    last_assigned_user_id = fields.Many2one(
        'res.users', string='Last Assigned Salesperson', ondelete='set null')

    _sql_constraints = [
        ('unique_company', 'unique(company_id)', 'Only one tracker per company.'),
    ]

    @api.model
    def _get_for_company(self, company_id):
        tracker = self.search([('company_id', '=', company_id)], limit=1)
        if not tracker:
            tracker = self.create({'company_id': company_id})
        return tracker

    def get_next_user(self, eligible_users):
        """Return the next user in round-robin order after last_assigned_user_id.
        eligible_users: res.users recordset, ordered stably (by id)."""
        self.ensure_one()
        if not eligible_users:
            return self.env['res.users']

        # Sort by id for stable ordering
        ordered = eligible_users.sorted('id')
        last = self.last_assigned_user_id

        if not last or last not in ordered:
            next_user = ordered[0]
        else:
            idx = list(ordered.ids).index(last.id)
            next_idx = (idx + 1) % len(ordered)
            next_user = ordered[next_idx]

        self.last_assigned_user_id = next_user
        return next_user

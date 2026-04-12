from odoo import fields, models


class CrmLead(models.Model):
    _inherit = 'crm.lead'

    # Override stage_id domain: filter by company instead of team
    stage_id = fields.Many2one(
        domain="['|', ('company_id', '=', False), ('company_id', '=', company_id)]",
    )

    def _read_group_stage_ids(self, stages, domain):
        """Override to show kanban columns filtered by current company
        instead of by sales team."""
        company_id = self.env.company.id
        search_domain = [
            '|',
            # Always include stages already in use (avoids orphaned records)
            ('id', 'in', stages.ids),
            # Show all non-folded stages belonging to the current company
            '&', ('company_id', '=', company_id), ('fold', '=', False),
        ]
        stage_ids = stages.sudo()._search(search_domain, order=stages._order)
        return stages.browse(stage_ids)

from odoo import models, _
import logging

_logger = logging.getLogger(__name__)


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    def _action_confirm(self):
        result = super()._action_confirm()

        # Link project to the CRM lead's document folder
        for order in self.sudo():
            if not order.opportunity_id:
                continue
            lead = order.opportunity_id
            # Find the document folder linked to this lead
            folder = self.env['documents.document'].sudo().search([
                ('type', '=', 'folder'),
                ('res_model', '=', 'crm.lead'),
                ('res_id', '=', lead.id),
            ], limit=1)
            if not folder:
                continue
            # Link all projects from this order to the folder
            for project in order.project_ids:
                if not project.documents_folder_id:
                    project.sudo().write({'documents_folder_id': folder.id})
                    _logger.info(
                        'JHM: Linked project "%s" (id=%d) to document folder "%s" (id=%d)',
                        project.name, project.id, folder.name, folder.id,
                    )

        return result

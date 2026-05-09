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
            # Link all projects from this order to the folder + set company
            for project in order.project_ids:
                update = {}
                if not project.documents_folder_id:
                    update['documents_folder_id'] = folder.id
                if not project.company_id and order.company_id:
                    update['company_id'] = order.company_id.id
                if update:
                    project.sudo().write(update)
                    _logger.info(
                        'JHM: Updated project "%s" (id=%d) folder=%s company=%s',
                        project.name, project.id,
                        update.get('documents_folder_id'), update.get('company_id'),
                    )

        # Also set company on projects even without a document folder
        for order in self.sudo():
            for project in order.project_ids:
                if not project.company_id and order.company_id:
                    project.sudo().write({'company_id': order.company_id.id})

        return result

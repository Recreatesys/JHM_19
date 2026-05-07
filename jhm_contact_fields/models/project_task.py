from odoo import api, fields, models, _
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)


class ProjectTask(models.Model):
    _inherit = 'project.task'

    def action_schedule_payment(self):
        """Open wizard to schedule payment — creates invoice and activity."""
        self.ensure_one()
        # Find linked sale order
        sale_order = self.sale_order_id or (self.project_id and self.project_id.sale_order_id)
        if not sale_order:
            # Try via sale_line_id
            sale_order = self.sale_line_id.order_id if self.sale_line_id else False
        if not sale_order:
            raise UserError(_('No sale order linked to this task or project.'))

        return {
            'type': 'ir.actions.act_window',
            'name': _('Schedule Payment'),
            'res_model': 'jhm.schedule.payment.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_task_id': self.id,
                'default_sale_order_id': sale_order.id,
            },
        }


class JhmSchedulePaymentWizard(models.TransientModel):
    _name = 'jhm.schedule.payment.wizard'
    _description = 'Schedule Payment Wizard'

    task_id = fields.Many2one('project.task', required=True)
    sale_order_id = fields.Many2one('sale.order', required=True, string='Sale Order')
    invoice_type = fields.Selection([
        ('percentage', 'Percentage'),
        ('fixed', 'Fixed Amount'),
    ], string='Invoice Type', default='percentage', required=True)
    percentage = fields.Float(string='Percentage (%)', default=100.0)
    fixed_amount = fields.Float(string='Amount', digits=(16, 2))

    def action_confirm(self):
        self.ensure_one()
        task = self.task_id
        sale_order = self.sale_order_id

        # 1. Mark milestone as reached (create one if needed)
        project = task.project_id
        milestone = task.milestone_id
        if not milestone:
            milestone = self.env['project.milestone'].create({
                'name': task.name,
                'project_id': project.id,
                'is_reached': True,
                'reached_date': fields.Date.today(),
            })
            task.milestone_id = milestone.id
        else:
            milestone.write({'is_reached': True, 'reached_date': fields.Date.today()})

        # 2. Create draft invoice
        if self.invoice_type == 'percentage':
            # Use Odoo's advance payment wizard with percentage
            wizard = self.env['sale.advance.payment.inv'].create({
                'sale_order_ids': [(6, 0, [sale_order.id])],
                'advance_payment_method': 'percentage',
                'amount': self.percentage,
            })
            wizard.create_invoices()
        else:
            # Fixed amount - use down payment
            wizard = self.env['sale.advance.payment.inv'].create({
                'sale_order_ids': [(6, 0, [sale_order.id])],
                'advance_payment_method': 'fixed',
                'fixed_amount': self.fixed_amount,
            })
            wizard.create_invoices()

        # 3. Create activity for Angela
        angela = self.env['res.users'].search([('login', '=', 'angela.ho@johnhu.com.hk')], limit=1)
        if not angela:
            angela = self.env.user

        contact_name = sale_order.partner_id.name or ''
        so_name = sale_order.name or ''
        summary = 'Payment: %s — %s' % (so_name, contact_name)

        task.activity_schedule(
            'mail.mail_activity_data_todo',
            date_deadline=fields.Date.today(),
            summary=summary,
            note='A payment has been scheduled for %s (%s). Please process the invoice.' % (
                contact_name, so_name),
            user_id=angela.id,
        )

        return {'type': 'ir.actions.act_window_close'}

from odoo import api, fields, models, _
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)

_PAYMENT_LABELS = ['First Payment', 'Second Payment', 'Third Payment', 'Fourth Payment']


class ProjectTask(models.Model):
    _inherit = 'project.task'

    def action_schedule_payment(self):
        """Open wizard to schedule payment — creates invoices and activity."""
        self.ensure_one()
        sale_order = self.sale_order_id or (self.project_id and self.project_id.sale_order_id)
        if not sale_order:
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


class ProjectProject(models.Model):
    _inherit = 'project.project'

    payment_status = fields.Char(
        string='Payment Status', compute='_compute_payment_status', store=False)

    def action_view_all_invoices(self):
        """Navigate to invoices linked to this project's sale order."""
        self.ensure_one()
        so = self.sale_order_id
        if not so:
            return
        invoices = so.invoice_ids.filtered(lambda m: m.move_type == 'out_invoice')
        action = self.env['ir.actions.actions']._for_xml_id('account.action_move_out_invoice_type')
        action['domain'] = [('id', 'in', invoices.ids)]
        return action

    def _compute_payment_status(self):
        for proj in self:
            so = proj.sale_order_id
            if not so:
                proj.payment_status = ''
                continue
            invoices = so.invoice_ids.filtered(
                lambda m: m.move_type == 'out_invoice' and m.state == 'posted'
            )
            if not invoices:
                proj.payment_status = 'Not Paid'
            elif all(inv.payment_state in ('paid', 'in_payment') for inv in invoices):
                proj.payment_status = 'Paid'
            else:
                proj.payment_status = 'Partially Paid'


class JhmSchedulePaymentWizard(models.TransientModel):
    _name = 'jhm.schedule.payment.wizard'
    _description = 'Schedule Payment Wizard'

    task_id = fields.Many2one('project.task', required=True)
    sale_order_id = fields.Many2one('sale.order', required=True, string='Sale Order')
    num_invoices = fields.Selection([
        ('1', '1 Invoice'),
        ('2', '2 Invoices'),
        ('3', '3 Invoices'),
        ('4', '4 Invoices'),
    ], string='Number of Invoices', default='1', required=True)
    amount_1 = fields.Float(string='First Payment', digits=(16, 2))
    amount_2 = fields.Float(string='Second Payment', digits=(16, 2))
    amount_3 = fields.Float(string='Third Payment', digits=(16, 2))
    amount_4 = fields.Float(string='Fourth Payment', digits=(16, 2))

    def action_confirm(self):
        self.ensure_one()
        task = self.task_id
        sale_order = self.sale_order_id
        num = int(self.num_invoices)

        amounts = [self.amount_1, self.amount_2, self.amount_3, self.amount_4][:num]
        if any(a <= 0 for a in amounts):
            raise UserError(_('All payment amounts must be greater than zero.'))

        # Get visa program name from the opportunity or SO line product
        visa_name = ''
        if sale_order.opportunity_id and sale_order.opportunity_id.partner_visa_program_id:
            visa_name = sale_order.opportunity_id.partner_visa_program_id.name
        if not visa_name:
            # Fallback to first SO line product name
            first_line = sale_order.order_line[:1]
            if first_line:
                visa_name = first_line.product_id.name or ''

        # Get the product from first SO line (or a fallback)
        product = False
        if sale_order.order_line:
            product = sale_order.order_line[0].product_id

        # 1. Mark milestone as reached
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

        # 2. Create draft invoices
        invoices_created = []
        for i, amount in enumerate(amounts):
            label = _PAYMENT_LABELS[i]
            line_name = '%s - %s' % (visa_name, label) if visa_name else label

            invoice_vals = {
                'move_type': 'out_invoice',
                'partner_id': sale_order.partner_id.id,
                'company_id': sale_order.company_id.id,
                'invoice_line_ids': [(0, 0, {
                    'name': line_name,
                    'product_id': product.id if product else False,
                    'quantity': 1,
                    'price_unit': amount,
                })],
            }

            # Link to SO
            invoice = self.env['account.move'].sudo().with_context(
                default_move_type='out_invoice',
            ).create(invoice_vals)

            # Link invoice to sale order
            sale_order.sudo().write({
                'invoice_ids': [(4, invoice.id)],
            })

            invoices_created.append(invoice)

        # 3. Create activity for Angela
        angela = self.env['res.users'].search(
            [('login', '=', 'angela.ho@johnhu.com.hk')], limit=1)
        if not angela:
            angela = self.env.user

        contact_name = sale_order.partner_id.name or ''
        so_name = sale_order.name or ''
        summary = 'Payment: %s — %s (%d invoices)' % (so_name, contact_name, num)

        task.activity_schedule(
            'mail.mail_activity_data_todo',
            date_deadline=fields.Date.today(),
            summary=summary,
            note='%d draft invoice(s) created for %s (%s). Please review and confirm.' % (
                num, contact_name, so_name),
            user_id=angela.id,
        )

        return {'type': 'ir.actions.act_window_close'}

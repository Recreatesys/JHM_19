from odoo import api, fields, models, _
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)

_PAYMENT_LABELS = ['First Payment', 'Second Payment', 'Third Payment', 'Fourth Payment']


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    draft_invoice_count = fields.Integer(
        string='Draft Invoices', compute='_compute_draft_invoice_count')

    def _compute_draft_invoice_count(self):
        for so in self:
            so.draft_invoice_count = len(so.invoice_ids.filtered(
                lambda m: m.move_type == 'out_invoice' and m.state == 'draft'))

    def action_view_draft_invoices(self):
        """Navigate to draft invoices linked to this SO."""
        self.ensure_one()
        drafts = self.invoice_ids.filtered(
            lambda m: m.move_type == 'out_invoice' and m.state == 'draft')
        action = self.env['ir.actions.actions']._for_xml_id('account.action_move_out_invoice_type')
        action['domain'] = [('id', 'in', drafts.ids)]
        if len(drafts) == 1:
            action['views'] = [(self.env.ref('account.view_move_form').id, 'form')]
            action['res_id'] = drafts.id
        return action

    def action_schedule_payment(self):
        """Open wizard to schedule payment — creates draft invoices."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Schedule Payment'),
            'res_model': 'jhm.schedule.payment.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_sale_order_id': self.id,
            },
        }


class ProjectTask(models.Model):
    _inherit = 'project.task'

    def action_schedule_payment(self):
        """Open wizard to schedule payment from task — finds linked SO."""
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


# ═══════════════════════════════════════════════════════════════════════
# Schedule Payment Wizard
# ═══════════════════════════════════════════════════════════════════════

class JhmSchedulePaymentWizard(models.TransientModel):
    _name = 'jhm.schedule.payment.wizard'
    _description = 'Schedule Payment Wizard'

    sale_order_id = fields.Many2one('sale.order', required=True, string='Sale Order')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('done', 'Done'),
    ], default='draft')
    total_amount = fields.Monetary(
        string='Total Amount', compute='_compute_amounts',
        currency_field='currency_id')
    invoiced_amount = fields.Monetary(
        string='Invoiced Amount', compute='_compute_amounts',
        currency_field='currency_id')
    balance = fields.Monetary(
        string='Balance', compute='_compute_amounts',
        currency_field='currency_id')
    currency_id = fields.Many2one(
        'res.currency', related='sale_order_id.currency_id')
    line_ids = fields.One2many(
        'jhm.schedule.payment.line', 'wizard_id', string='Payments')
    existing_invoice_ids = fields.One2many(
        'jhm.schedule.payment.existing', 'wizard_id', string='Existing Invoices')

    @api.depends('sale_order_id', 'line_ids.amount')
    def _compute_amounts(self):
        for wiz in self:
            so = wiz.sale_order_id
            wiz.total_amount = so.amount_untaxed if so else 0
            existing_inv = 0
            if so:
                for inv in so.invoice_ids.filtered(
                    lambda m: m.move_type == 'out_invoice' and m.state != 'cancel'
                ):
                    existing_inv += inv.amount_untaxed
            new_inv = sum(l.amount for l in wiz.line_ids)
            wiz.invoiced_amount = existing_inv + new_inv
            wiz.balance = wiz.total_amount - wiz.invoiced_amount

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        so_id = res.get('sale_order_id') or self.env.context.get('default_sale_order_id')
        if so_id:
            so = self.env['sale.order'].browse(so_id)
            existing = []
            for i, inv in enumerate(so.invoice_ids.filtered(
                lambda m: m.move_type == 'out_invoice' and m.state != 'cancel'
            )):
                label = _PAYMENT_LABELS[i] if i < 4 else 'Payment %d' % (i + 1)
                existing.append((0, 0, {
                    'label': label,
                    'amount': inv.amount_untaxed,
                    'invoice_date': inv.invoice_date,
                    'due_date': inv.invoice_date_due,
                    'payment_state': inv.payment_state or 'not_paid',
                    'invoice_id': inv.id,
                }))
            if existing:
                res['existing_invoice_ids'] = existing
        return res

    def action_confirm(self):
        self.ensure_one()
        sale_order = self.sale_order_id

        if not self.line_ids:
            raise UserError(_('Please add at least one payment line.'))

        for line in self.line_ids:
            if line.amount <= 0:
                raise UserError(_('All payment amounts must be greater than zero.'))

        # Get visa program name
        visa_name = ''
        if sale_order.opportunity_id and sale_order.opportunity_id.partner_visa_program_id:
            visa_name = sale_order.opportunity_id.partner_visa_program_id.name
        if not visa_name:
            first_line = sale_order.order_line[:1]
            if first_line:
                visa_name = first_line.product_id.name or ''

        product = sale_order.order_line[0].product_id if sale_order.order_line else False

        # Create draft invoices
        invoices_created = []
        for i, line in enumerate(self.line_ids):
            label = _PAYMENT_LABELS[i] if i < 4 else 'Payment %d' % (i + 1)
            line_name = '%s - %s' % (visa_name, label) if visa_name else label

            # Link invoice line to the first SO line so the invoice
            # appears in the SO's invoice_ids (computed field)
            so_line = sale_order.order_line[:1]

            invoice = self.env['account.move'].sudo().with_context(
                default_move_type='out_invoice',
            ).create({
                'move_type': 'out_invoice',
                'partner_id': sale_order.partner_id.id,
                'company_id': sale_order.company_id.id,
                'invoice_date': line.invoice_date or False,
                'invoice_date_due': line.due_date or False,
                'invoice_line_ids': [(0, 0, {
                    'name': line_name,
                    'product_id': product.id if product else False,
                    'quantity': 1,
                    'price_unit': line.amount,
                    'sale_line_ids': [(4, so_line.id)] if so_line else [],
                })],
            })
            invoices_created.append(invoice)

        # Move created invoices to existing list and mark lines
        existing_lines = []
        for i, line in enumerate(self.line_ids):
            inv = invoices_created[i] if i < len(invoices_created) else None
            if inv:
                existing_lines.append((0, 0, {
                    'label': _PAYMENT_LABELS[i] if i < 4 else 'Payment %d' % (i + 1),
                    'amount': line.amount,
                    'invoice_date': line.invoice_date,
                    'due_date': line.due_date,
                    'payment_state': 'not_paid',
                    'invoice_id': inv.id,
                }))

        # Create activity for Angela
        angela = self.env['res.users'].search(
            [('login', '=', 'angela.ho@johnhu.com.hk')], limit=1)
        if not angela:
            angela = self.env.user

        num = len(invoices_created)
        contact_name = sale_order.partner_id.name or ''
        so_name = sale_order.name or ''

        sale_order.activity_schedule(
            'mail.mail_activity_data_todo',
            date_deadline=fields.Date.today(),
            summary='Payment: %s — %s (%d invoices)' % (so_name, contact_name, num),
            note='%d draft invoice(s) created for %s (%s). Please review and confirm.' % (
                num, contact_name, so_name),
            user_id=angela.id,
        )

        # Clear new lines, add to existing, stay open
        self.write({
            'state': 'done',
            'line_ids': [(5, 0, 0)],
            'existing_invoice_ids': existing_lines,
        })

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'jhm.schedule.payment.wizard',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }


class JhmSchedulePaymentLine(models.TransientModel):
    _name = 'jhm.schedule.payment.line'
    _description = 'Schedule Payment Line'
    _order = 'sequence'

    wizard_id = fields.Many2one('jhm.schedule.payment.wizard', ondelete='cascade')
    sequence = fields.Integer(default=10)
    label = fields.Char(string='Payment', compute='_compute_label', store=False)
    amount = fields.Float(string='Amount', digits=(16, 2), required=True)
    invoice_date = fields.Date(string='Invoice Date')
    due_date = fields.Date(string='Due Date')

    @api.depends('wizard_id.line_ids', 'wizard_id.existing_invoice_ids')
    def _compute_label(self):
        for line in self:
            # Count existing invoices to offset the numbering
            existing_count = len(line.wizard_id.existing_invoice_ids) if line.wizard_id else 0
            idx = existing_count
            if line.wizard_id and line.wizard_id.line_ids:
                for i, l in enumerate(line.wizard_id.line_ids):
                    if l == line:
                        idx = existing_count + i
                        break
            line.label = _PAYMENT_LABELS[idx] if idx < 4 else 'Payment %d' % (idx + 1)


class JhmSchedulePaymentExisting(models.TransientModel):
    _name = 'jhm.schedule.payment.existing'
    _description = 'Existing Invoice Line (read-only)'
    _order = 'id'

    wizard_id = fields.Many2one('jhm.schedule.payment.wizard', ondelete='cascade')
    label = fields.Char(string='Payment')
    amount = fields.Float(string='Amount', digits=(16, 2))
    invoice_date = fields.Date(string='Invoice Date')
    due_date = fields.Date(string='Due Date')
    payment_state = fields.Selection([
        ('not_paid', 'Not Paid'),
        ('in_payment', 'In Payment'),
        ('paid', 'Paid'),
        ('partial', 'Partial'),
        ('reversed', 'Reversed'),
    ], string='Status')
    invoice_id = fields.Many2one('account.move', string='Invoice')

    def action_open_invoice(self):
        """Open the linked invoice."""
        self.ensure_one()
        if not self.invoice_id:
            return
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'account.move',
            'res_id': self.invoice_id.id,
            'view_mode': 'form',
            'target': 'current',
        }

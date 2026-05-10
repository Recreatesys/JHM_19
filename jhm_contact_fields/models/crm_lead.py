import logging
from odoo import api, fields, models

_logger = logging.getLogger(__name__)

_CASE_STATUS = [
    ('not_required', 'Not Required'),
    ('not_started',  'Not Started'),
    ('waiting',      'Waiting'),
    ('in_progress',  'In Progress'),
    ('lodged',       'Lodged'),
    ('appealed',     'Appealed'),
    ('re_applied',   'Re-applied'),
    ('completed',    'Completed'),
    ('rejected',     'Rejected'),
    ('invited',      'Invited'),
    ('re_sit',       'Re-sit'),
    ('failed',       'Failed'),
]

PROBABILITY_SELECTION = [
    ('10', '10%'),
    ('30', '30%'),
    ('50', '50%'),
    ('70', '70%'),
    ('90', '90%'),
    ('100', '100%'),
]

# Stage name (case-insensitive substring) → probability string
# Looked up by name at runtime so IDs don't need to match across databases
_STAGE_NAME_PROBABILITY = [
    ('new lead',              '10'),
    ('contacting',            '50'),
    ('valid whatsapp',        '50'),
    ('appointment',           '50'),
    ('met & follow up',       '70'),
    ('service agreement',     '90'),
    ('ready to close',        '90'),
    ('no response',           '10'),
    ('not interested',        '10'),
    ('signed w/ other agency','10'),
    ('unqualified',           '10'),
]

# Maps each standalone crm.lead field → the matching res.partner field name
_CRM_TO_PARTNER = {
    'partner_gender': 'gender',
    'partner_client_nationality_id': 'client_nationality_id',
    'partner_jhm_line_id': 'jhm_line_id',
    'partner_wechat': 'wechat',
    'partner_b2b_engagement': 'b2b_engagement',
    'partner_background_id': 'background_id',
    'partner_immigration_country': 'immigration_country',
    'partner_communication_channel_id': 'communication_channel_id',
    'partner_visa_program_id': 'visa_program_id',
    'partner_previous_visa_program_id': 'previous_visa_program_id',
    'partner_jhm_lead_source_id': 'jhm_lead_source_id',
    'partner_source_details': 'source_details',
    'partner_commission': 'commission',
    'partner_migration_budget': 'migration_budget',
    'partner_facing_problems': 'facing_problems',
    'partner_consultation_fee_paid': 'consultation_fee_paid',
    'partner_sf_creation_date': 'sf_creation_date',
    'partner_appointment_date': 'appointment_date',
    'partner_appointment_date_2': 'appointment_date_2',
    'partner_appointment_notes': 'appointment_notes',
    'partner_last_call_date': 'last_call_date',
    'partner_sf_followup_date': 'sf_followup_date',
    'partner_chat_log': 'chat_log',
    'partner_jhm_description': 'jhm_description',
    'partner_spouse_name': 'spouse_name',
    'partner_spouse_phone': 'spouse_phone',
    'partner_spouse_email': 'spouse_email',
    # Case tracking fields
    'partner_occupation': 'occupation',
    'partner_birthday': 'birthday',
    'partner_admin': 'admin',
    'partner_nomination': 'nomination',
    'partner_nomination_due_date': 'nomination_due_date',
    'partner_aus_skill_status': 'aus_skill_status',
    'partner_assessment_due_date': 'assessment_due_date',
    'partner_assessment': 'assessment',
    'partner_spouse_occupation': 'spouse_occupation',
    'partner_child_1': 'child_1',
    'partner_child_2': 'child_2',
    'partner_child_3': 'child_3',
    'partner_child_4': 'child_4',
    'partner_spouse_highest_qualification': 'spouse_highest_qualification',
    'partner_eoi': 'eoi',
    'partner_eoi_date': 'eoi_date',
    'partner_los_date': 'los_date',
    'partner_lodgment_date': 'lodgment_date',
    'partner_ielts': 'ielts',
    'partner_ielts_due_date': 'ielts_due_date',
    'partner_health': 'health',
    'partner_health_due_date': 'health_due_date',
    'partner_police': 'police',
    'partner_police_due_date': 'police_due_date',
}


class CrmLead(models.Model):
    _inherit = 'crm.lead'

    # ── Probability as selection ──────────────────────────────────────────
    jhm_probability = fields.Selection(
        PROBABILITY_SELECTION,
        string='Probability',
    )

    @api.onchange('jhm_probability')
    def _onchange_jhm_probability(self):
        if self.jhm_probability:
            self.probability = float(self.jhm_probability)

    # Rename core fields
    email_from = fields.Char(string='Main Applicant Email')
    phone = fields.Char(string='Main Applicant Phone')

    # ── Assignment fields ─────────────────────────────────────────────────
    co_owner_ids = fields.Many2many(
        'res.users', 'crm_lead_co_owner_rel', 'lead_id', 'user_id',
        string='Co-owner',
        domain=[('share', '=', False)],
    )
    process_team_ids = fields.Many2many(
        'res.users', 'crm_lead_process_team_rel', 'lead_id', 'user_id',
        string='Process Team in Charge',
        domain=[('share', '=', False)],
    )
    process_2_ids = fields.Many2many(
        'res.users', 'crm_lead_process_2_rel', 'lead_id', 'user_id',
        string='Process 2',
        domain=[('share', '=', False)],
    )

    def _sync_assignment_followers(self):
        """Add salesperson, co-owners, process team and process 2 as followers
        of the opportunity and its linked contact."""
        for rec in self:
            users = rec.user_id | rec.co_owner_ids | rec.process_team_ids | rec.process_2_ids
            partners = users.mapped('partner_id')
            if partners:
                rec.message_subscribe(partner_ids=partners.ids)
                if rec.partner_id:
                    rec.partner_id.message_subscribe(partner_ids=partners.ids)

    @api.onchange('user_id', 'co_owner_ids', 'process_team_ids', 'process_2_ids')
    def _onchange_assignment_followers(self):
        # Follower subscription happens on save; nothing needed here for UI
        pass

    # ── Standalone JHM fields (always stored, synced to/from partner) ─────
    partner_gender = fields.Selection([
        ('M', 'M'), ('F', 'F'), ('Male', 'Male'), ('Female', 'Female'), ('TBD', 'TBD'),
    ], string='Gender')
    partner_client_nationality_id = fields.Many2one(
        'jhm.nationality', string="Client's Nationality")
    partner_jhm_line_id = fields.Char(string='Line ID')
    partner_wechat = fields.Char(string='WeChat')
    partner_b2b_engagement = fields.Boolean(string='B2B Engagement')
    partner_background_id = fields.Many2one('jhm.background', string='Background')
    partner_immigration_country = fields.Char(string='Immigration Country')
    partner_communication_channel_id = fields.Many2one(
        'jhm.communication.channel', string='Communication Channel')
    partner_visa_program_id = fields.Many2one('jhm.visa.program', string='Visa Program')
    partner_previous_visa_program_id = fields.Many2one(
        'jhm.visa.program', string='Previous Visa Program')
    partner_jhm_lead_source_id = fields.Many2one('jhm.lead.source', string='Lead Source')
    partner_source_details = fields.Char(string='Source Details')
    partner_commission = fields.Char(string='Commission')
    partner_migration_budget = fields.Char(string='Migration Budget')
    jhm_entity = fields.Selection([('jhm', 'JHM'), ('jhml', 'JHML')], string='JHM/JHML')
    jhm_category = fields.Selection([
        ('business', 'Business'),
        ('skill', 'Skill'),
        ('investment', 'Investment'),
        ('others', 'Others'),
        ('big_ticket', 'Big Ticket'),
        ('family', 'Family'),
        ('tbd', 'TBD'),
        ('employer_sponsorship', 'Employer Sponsorship'),
    ], string='Category')
    _FACING_PROBLEMS = [
        ('closed_sales', 'Closed Sales'),
        ('tbd', 'TBD'),
        ('compare_competitors', 'Compare Competitors'),
        ('compare_visas', 'Compare Visas'),
        ('compare_projects', 'Compare Projects'),
        ('problem_solved_soon', 'Problem can be solved soon'),
        ('cv', 'CV'),
        ('ielts', 'IELTS'),
        ('plans_visit', 'Plans to visit migration country'),
        ('await_new_policy', 'Await New Policy'),
        ('preparation', 'Preparation'),
        ('comparing_countries', 'Comparing Countries/ Initial'),
        ('source_of_fund', 'Source of Fund'),
        ('budget', 'Budget'),
        ('family_issue', 'Family Issue'),
        ('employer', 'Employer'),
        ('tax', 'Tax'),
        ('on_trip', 'On Trip'),
        ('on_hold', 'On Hold'),
        ('fail_to_contact', 'Fail to contact by call and WhatsApp'),
        ('closed_lost', 'Closed Lost'),
        ('do_not_disturb', 'Do not disturb'),
        ('no_immigration_need', 'No Immigration Need'),
        ('unqualified', 'Unqualified'),
        ('out_of_scope', 'Out-of-scope services'),
        ('diy', 'DIY'),
        ('fake_lead', 'Fake Lead'),
        ('scam', 'Scam'),
        ('partnership', 'Partnership'),
    ]
    partner_facing_problems = fields.Selection(_FACING_PROBLEMS, string='Facing Problems')
    partner_consultation_fee_paid = fields.Char(string='Consultation Fee Paid')
    partner_sf_creation_date = fields.Date(string='SF Creation Date')
    partner_appointment_date = fields.Date(string='Appointment Date', tracking=True)
    partner_appointment_date_2 = fields.Date(string='2nd Appointment Date')
    partner_appointment_notes = fields.Char(string='Appointment Notes')
    partner_last_call_date = fields.Date(string='Last Call Date', tracking=True)
    partner_sf_followup_date = fields.Date(string='Followup Date', tracking=True)
    partner_chat_log = fields.Text(string='Chat Log')
    partner_jhm_description = fields.Text(string='Description')
    partner_spouse_name = fields.Char(string='Spouse Name')
    partner_spouse_phone = fields.Char(string='Spouse Phone')
    partner_spouse_email = fields.Char(string='Spouse Email')

    # ── Taiwan / Webinar fields ───────────────────────────────────────────
    webinar_name = fields.Char(string='Webinar Name')
    _TW_STATUS = [('true', 'TRUE'), ('false', 'FALSE')]
    tw_call_connected = fields.Selection(_TW_STATUS, string='Call Connected')
    tw_added_on_line  = fields.Selection(_TW_STATUS, string='Added on LINE')
    tw_email_sent     = fields.Selection(_TW_STATUS, string='Email Sent')
    tw_group_created  = fields.Selection(_TW_STATUS, string='Group Created')
    tw_followup_1 = fields.Text(string='1st Follow-up')
    tw_followup_2 = fields.Text(string='2nd Follow-up')
    tw_followup_3 = fields.Text(string='3rd Follow-up')
    tw_followup_4 = fields.Text(string='4th Follow-up')

    # ── Case tracking fields ──────────────────────────────────────────────
    partner_occupation = fields.Char(string='Occupation')
    partner_birthday = fields.Date(string='Birthday')
    partner_nomination = fields.Selection(_CASE_STATUS, string='Nomination')
    partner_nomination_due_date = fields.Date(string='Nomination Due Date')
    partner_aus_skill_status = fields.Char(string='Aus Skill Status')
    partner_assessment_due_date = fields.Date(string='Assessment Due Date')
    partner_assessment = fields.Selection(_CASE_STATUS, string='Assessment')
    partner_spouse_occupation = fields.Char(string="Spouse's Occupation")
    partner_child_1 = fields.Char(string='Applicant Child 1')
    partner_child_2 = fields.Char(string='Applicant Child 2')
    partner_child_3 = fields.Char(string='Applicant Child 3')
    partner_child_4 = fields.Char(string='Applicant Child 4')
    partner_spouse_highest_qualification = fields.Char(string="Spouse's Highest Qualification")
    partner_admin = fields.Text(string='Admin')
    partner_eoi = fields.Selection(_CASE_STATUS, string='EOI')
    partner_eoi_date = fields.Date(string='EOI Date')
    partner_los_date = fields.Date(string='LOS Date')
    partner_lodgment_date = fields.Date(string='Lodgment Date')
    partner_ielts = fields.Selection(_CASE_STATUS, string='IELTS')
    partner_ielts_due_date = fields.Date(string='IELTS Due Date')
    partner_health = fields.Selection(_CASE_STATUS, string='Health')
    partner_health_due_date = fields.Date(string='Health Due Date')
    partner_police = fields.Selection(_CASE_STATUS, string='Police')
    partner_police_due_date = fields.Date(string='Police Due Date')

    # ── Sales tab ─────────────────────────────────────────────────────────
    sale_total_amount      = fields.Float(string='Total Amount', digits=(16, 2))
    sale_order_issue_date  = fields.Date(string='Order Issue Date')
    sale_referral          = fields.Float(string='Referral', digits=(16, 2))

    sale_payment_1         = fields.Float(string='1st Payment', digits=(16, 2))
    sale_payment_date_1    = fields.Date(string='1st Payment Date')
    sale_payment_2         = fields.Float(string='2nd Payment', digits=(16, 2))
    sale_payment_date_2    = fields.Date(string='2nd Payment Date')
    sale_payment_3         = fields.Float(string='3rd Payment', digits=(16, 2))
    sale_payment_date_3    = fields.Date(string='3rd Payment Date')
    sale_payment_4         = fields.Float(string='4th Payment', digits=(16, 2))
    sale_payment_date_4    = fields.Date(string='4th Payment Date')
    sale_payment_5         = fields.Float(string='5th Payment', digits=(16, 2))
    sale_payment_date_5    = fields.Date(string='5th Payment Date')

    sale_balance = fields.Float(
        string='Balance', digits=(16, 2),
        compute='_compute_sale_balance', store=True,
    )

    sale_commission_ratio  = fields.Float(string='Commission Ratio (%)', digits=(5, 2))
    sale_commission_1      = fields.Float(string='1st Payment Commission', digits=(16, 2),
                                          compute='_compute_sale_commissions', store=True)
    sale_commission_2      = fields.Float(string='2nd Payment Commission', digits=(16, 2),
                                          compute='_compute_sale_commissions', store=True)
    sale_commission_3      = fields.Float(string='3rd Payment Commission', digits=(16, 2),
                                          compute='_compute_sale_commissions', store=True)
    sale_commission_4      = fields.Float(string='4th Payment Commission', digits=(16, 2),
                                          compute='_compute_sale_commissions', store=True)
    sale_commission_5      = fields.Float(string='5th Payment Commission', digits=(16, 2),
                                          compute='_compute_sale_commissions', store=True)

    # Not stored — depends on "current calendar month" so must recalculate on every read
    sale_current_month_total_close = fields.Float(
        string='Current Month Total Close', digits=(16, 2),
        compute='_compute_sale_current_month',
    )
    sale_current_month_total_commission = fields.Float(
        string='Current Month Total Commission', digits=(16, 2),
        compute='_compute_sale_current_month',
    )

    @api.depends(
        'sale_total_amount',
        'sale_payment_1', 'sale_payment_2', 'sale_payment_3',
        'sale_payment_4', 'sale_payment_5',
    )
    def _compute_sale_balance(self):
        for rec in self:
            paid = (
                (rec.sale_payment_1 or 0) +
                (rec.sale_payment_2 or 0) +
                (rec.sale_payment_3 or 0) +
                (rec.sale_payment_4 or 0) +
                (rec.sale_payment_5 or 0)
            )
            rec.sale_balance = (rec.sale_total_amount or 0) - paid

    @api.depends(
        'sale_commission_ratio',
        'sale_payment_1', 'sale_payment_2', 'sale_payment_3',
        'sale_payment_4', 'sale_payment_5',
    )
    def _compute_sale_commissions(self):
        for rec in self:
            ratio = (rec.sale_commission_ratio or 0) / 100.0
            rec.sale_commission_1 = (rec.sale_payment_1 or 0) * ratio
            rec.sale_commission_2 = (rec.sale_payment_2 or 0) * ratio
            rec.sale_commission_3 = (rec.sale_payment_3 or 0) * ratio
            rec.sale_commission_4 = (rec.sale_payment_4 or 0) * ratio
            rec.sale_commission_5 = (rec.sale_payment_5 or 0) * ratio

    def _compute_sale_current_month(self):
        today = fields.Date.today()
        for rec in self:
            total_close = 0.0
            total_comm  = 0.0
            payments = [
                (rec.sale_payment_1, rec.sale_payment_date_1, rec.sale_commission_1),
                (rec.sale_payment_2, rec.sale_payment_date_2, rec.sale_commission_2),
                (rec.sale_payment_3, rec.sale_payment_date_3, rec.sale_commission_3),
                (rec.sale_payment_4, rec.sale_payment_date_4, rec.sale_commission_4),
                (rec.sale_payment_5, rec.sale_payment_date_5, rec.sale_commission_5),
            ]
            for amount, date, commission in payments:
                if date and date.year == today.year and date.month == today.month:
                    total_close += (amount or 0)
                    total_comm  += (commission or 0)
            rec.sale_current_month_total_close      = total_close
            rec.sale_current_month_total_commission = total_comm

    # ── Inactive Lead flag ────────────────────────────────────────────────
    inactive_lead = fields.Boolean(string='Inactive Lead', default=False)

    # ── Time to Close ─────────────────────────────────────────────────────
    time_to_close = fields.Selection([
        ('tbd',      'TBD'),
        ('1month',   '1 Month'),
        ('2_3month', '2-3 Months'),
    ], string='Time to Close')

    time_to_close_set_date = fields.Date(string='Time to Close Set Date', readonly=True)

    def _apply_time_to_close(self, vals):
        """If time_to_close is being set, overwrite date_deadline accordingly."""
        from datetime import timedelta
        ttc = vals.get('time_to_close')
        if ttc == '1month':
            set_date = fields.Date.today()
            vals['time_to_close_set_date'] = set_date
            vals['date_deadline'] = set_date + timedelta(days=30)
        elif ttc == '2_3month':
            set_date = fields.Date.today()
            vals['time_to_close_set_date'] = set_date
            vals['date_deadline'] = set_date + timedelta(days=90)
        elif ttc in ('tbd', False, None) and 'time_to_close' in vals:
            vals['time_to_close_set_date'] = False

    # ── Stage isolation per company ───────────────────────────────────────
    @api.model
    def _read_group_stage_ids(self, stages, domain):
        """Restrict Kanban columns / status-bar to stages belonging to the
        current company only.  Always filters by company — even stages already
        on records are excluded if they belong to a different company."""
        company_id = self.env.company.id
        search_domain = [('company_id', '=', company_id)]
        stage_ids = stages.sudo()._search(search_domain, order=stages._order)
        return stages.browse(stage_ids)

    # ── Stage → probability (HK company only) ────────────────────────────
    def _get_hk_stage_probability(self):
        """Return the probability string for the current stage, or None."""
        stage_name = (self.stage_id.name or '').lower()
        for keyword, probability in _STAGE_NAME_PROBABILITY:
            if keyword in stage_name:
                return probability
        return None

    def _apply_hk_stage_probability(self):
        """If the opportunity belongs to JHML HK,
        auto-set jhm_probability based on the current stage name.
        Uses SQL to bypass Odoo's PLS recomputation that overwrites probability."""
        jhm_hk = self.env['res.company'].search(
            [('name', '=', 'JHML HK')], limit=1
        )
        if not jhm_hk:
            return
        for rec in self:
            if rec.company_id.id == jhm_hk.id and isinstance(rec.id, int):
                prob = rec._get_hk_stage_probability()
                if prob:
                    prob_float = float(prob)
                    self.env.cr.execute(
                        "UPDATE crm_lead SET jhm_probability = %s, probability = %s, "
                        "automated_probability = %s WHERE id = %s",
                        (prob, prob_float, prob_float, rec.id)
                    )
                    rec.invalidate_recordset(['jhm_probability', 'probability', 'automated_probability'])

    @api.onchange('partner_visa_program_id')
    def _onchange_visa_program_entity(self):
        """Auto-set JHM/JHML based on visa program name."""
        for rec in self:
            if rec.company_id and rec.company_id.id == 1 and rec.partner_visa_program_id:
                name = (rec.partner_visa_program_id.name or '').upper()
                if name.startswith('AU') or name.startswith('NZ'):
                    rec.jhm_entity = 'jhm'

    @api.onchange('stage_id')
    def _onchange_stage_probability(self):
        """UI onchange — sets probability via ORM (record may not be saved yet)."""
        jhm_hk = self.env['res.company'].search(
            [('name', '=', 'JHML HK')], limit=1
        )
        if not jhm_hk:
            return
        for rec in self:
            if rec.company_id.id == jhm_hk.id:
                prob = rec._get_hk_stage_probability()
                if prob:
                    rec.jhm_probability = prob
                    rec.probability = float(prob)
                    rec.automated_probability = float(prob)

    # ── Forecast row subtotal ─────────────────────────────────────────────
    forecast_row_total = fields.Monetary(
        string='Subtotal',
        compute='_compute_forecast_row_total',
        store=True,
        currency_field='company_currency',
        group_operator='sum',
    )

    @api.depends('expected_revenue', 'prorated_revenue')
    def _compute_forecast_row_total(self):
        for rec in self:
            rec.forecast_row_total = (rec.expected_revenue or 0.0) + (rec.prorated_revenue or 0.0)

    # ── Sale order total (for Ready to Close report) ──────────────────────
    sale_order_amount = fields.Float(
        string='Sales Order Amount',
        compute='_compute_sale_order_amount',
        digits=(16, 2),
    )

    def _compute_sale_order_amount(self):
        for rec in self:
            self.env.cr.execute("""
                SELECT COALESCE(SUM(amount_untaxed), 0)
                FROM sale_order
                WHERE opportunity_id = %s AND state IN ('sale', 'done')
            """, [rec.id])
            rec.sale_order_amount = self.env.cr.fetchone()[0]

    # ── Quotation, Invoiced, Outstanding amounts (for Sales Report) ───────
    quotation_amount = fields.Float(
        string='Quotation Amount',
        compute='_compute_sales_report_amounts',
        digits=(16, 2),
    )
    invoiced_amount = fields.Float(
        string='Invoiced Amount',
        compute='_compute_sales_report_amounts',
        digits=(16, 2),
    )
    outstanding_balance_amount = fields.Float(
        string='Outstanding Balance Amount',
        compute='_compute_sales_report_amounts',
        digits=(16, 2),
    )

    def _compute_sales_report_amounts(self):
        ids = self.ids
        if not ids:
            for rec in self:
                rec.quotation_amount = 0.0
                rec.invoiced_amount = 0.0
                rec.outstanding_balance_amount = 0.0
            return

        # Quotation = draft/sent sale orders
        self.env.cr.execute("""
            SELECT opportunity_id, COALESCE(SUM(amount_untaxed), 0)
            FROM sale_order
            WHERE opportunity_id = ANY(%s) AND state IN ('draft', 'sent')
            GROUP BY opportunity_id
        """, [ids])
        quotations = dict(self.env.cr.fetchall())

        # Invoiced & outstanding via sale_order → invoice lines → invoices
        self.env.cr.execute("""
            SELECT
                so.opportunity_id,
                COALESCE(SUM(DISTINCT am.amount_untaxed), 0)  AS invoiced,
                COALESCE(SUM(DISTINCT am.amount_residual), 0) AS outstanding
            FROM sale_order so
            JOIN sale_order_line sol     ON sol.order_id = so.id
            JOIN sale_order_line_invoice_rel rel ON rel.order_line_id = sol.id
            JOIN account_move_line aml   ON aml.id = rel.invoice_line_id
            JOIN account_move am         ON am.id = aml.move_id
            WHERE so.opportunity_id = ANY(%s)
              AND am.move_type = 'out_invoice'
              AND am.state = 'posted'
            GROUP BY so.opportunity_id
        """, [ids])
        invoice_data = {row[0]: (row[1], row[2]) for row in self.env.cr.fetchall()}

        for rec in self:
            inv, out = invoice_data.get(rec.id, (0.0, 0.0))
            rec.quotation_amount = quotations.get(rec.id, 0.0)
            rec.invoiced_amount = inv
            rec.outstanding_balance_amount = out

    # ── Documents smart button ────────────────────────────────────────────
    jhm_documents_count = fields.Integer(
        string='Documents', compute='_compute_jhm_documents_count')

    def _compute_jhm_documents_count(self):
        for rec in self:
            rec.jhm_documents_count = self.env['documents.document'].sudo().search_count([
                ('type', '=', 'folder'),
                ('res_model', '=', 'crm.lead'),
                ('res_id', '=', rec.id),
            ])

    def action_open_jhm_documents(self):
        self.ensure_one()
        # Find folder by this specific lead's res_id (most precise)
        folder = self.env['documents.document'].sudo().search([
            ('type', '=', 'folder'),
            ('res_model', '=', 'crm.lead'),
            ('res_id', '=', self.id),
        ], limit=1)
        # Fallback: find by the linked contact's partner_id
        if not folder and self.partner_id:
            folder = self.env['documents.document'].sudo().search([
                ('type', '=', 'folder'),
                ('partner_id', '=', self.partner_id.id),
                ('res_model', '=', 'crm.lead'),
            ], limit=1)
        if folder:
            return {
                'type': 'ir.actions.act_window',
                'name': folder.name,
                'res_model': 'documents.document',
                'view_mode': 'kanban,list,activity',
                'target': 'current',
                'context': {
                    'searchpanel_default_user_folder_id': folder.id,
                },
            }
        # No folder yet — open Documents root
        return {
            'type': 'ir.actions.act_window',
            'name': 'Documents',
            'res_model': 'documents.document',
            'view_mode': 'kanban,list,activity',
            'target': 'current',
        }

    # ── Batch action: create document folders for selected opportunities ──
    def action_batch_create_document_folders(self):
        """Called from list-view Action menu. Creates a client FOLDER (type='folder')
        inside the CRM folder for every selected opportunity, regardless of probability."""
        Document = self.env['documents.document'].sudo()
        Access = self.env['documents.access'].sudo()
        crm_folder = self._get_or_create_crm_folder()
        forbidden = self.env['res.users'].browse([1]).mapped('partner_id')
        created = 0
        for rec in self:
            existing = Document.search([
                ('type', '=', 'folder'),
                ('res_model', '=', 'crm.lead'),
                ('res_id', '=', rec.id),
            ], limit=1)
            if existing:
                continue
            client_name = rec.partner_id.name or rec.contact_name or rec.name or 'Client'
            visa = rec.partner_visa_program_id.name if rec.partner_visa_program_id else ''
            folder_name = ('%s-%s — Client File' % (visa, client_name)) if visa else ('%s — Client File' % client_name)
            folder = Document.create({
                'type': 'folder',
                'name': folder_name,
                'folder_id': crm_folder.id,
                'owner_id': rec.user_id.id or self.env.user.id,
                'partner_id': rec.partner_id.id or False,
                'res_model': 'crm.lead',
                'res_id': rec.id,
            })
            # Grant edit access to followers (client is linked via partner_id on the folder)
            follower_partners = rec.message_follower_ids.mapped('partner_id') - forbidden
            if rec.partner_id:
                follower_partners -= rec.partner_id
            existing_pids = Access.search([('document_id', '=', folder.id)]).mapped('partner_id').ids
            for partner in follower_partners:
                if partner.id in existing_pids:
                    continue
                try:
                    with self.env.cr.savepoint():
                        Access.create({'document_id': folder.id, 'partner_id': partner.id, 'role': 'edit'})
                except Exception:
                    pass
            created += 1
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Folders Created',
                'message': '%d client folder(s) created in Documents.' % created,
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.act_window_close'},
            },
        }

    # ── Document creation at probability >= 50% ───────────────────────────
    def _get_or_create_crm_folder(self):
        """Return (or create) the top-level 'CRM' folder in Documents."""
        folder = self.env['documents.document'].sudo().search(
            [('type', '=', 'folder'), ('name', '=', 'CRM'), ('folder_id', '=', False)],
            limit=1,
        )
        if not folder:
            folder = self.env['documents.document'].sudo().create({
                'type': 'folder',
                'name': 'CRM',
            })
        return folder

    def _create_met_followup_document(self):
        """Create a client FOLDER (type='folder') in Documents linked to the lead
        when the opportunity probability reaches >= 50%."""
        Document = self.env['documents.document'].sudo()
        Access = self.env['documents.access'].sudo()
        crm_folder = self._get_or_create_crm_folder()
        for rec in self:
            if float(rec.jhm_probability or 0) < 50 and float(rec.probability or 0) < 50:
                continue
            # Skip if a folder for this lead already exists
            existing = Document.search([
                ('type', '=', 'folder'),
                ('res_model', '=', 'crm.lead'),
                ('res_id', '=', rec.id),
            ], limit=1)
            if existing:
                continue

            # Build name: [Visa Program]-[Client Name] — Client File
            client_name = rec.partner_id.name or rec.contact_name or rec.name or 'Client'
            visa = rec.partner_visa_program_id.name if rec.partner_visa_program_id else ''
            folder_name = ('%s-%s — Client File' % (visa, client_name)) if visa else ('%s — Client File' % client_name)

            folder = Document.create({
                'type': 'folder',
                'name': folder_name,
                'folder_id': crm_folder.id,
                'owner_id': rec.user_id.id or self.env.user.id,
                'partner_id': rec.partner_id.id or False,
                'res_model': 'crm.lead',
                'res_id': rec.id,
            })

            # Grant edit access to followers (client linked via partner_id on folder)
            forbidden = self.env['res.users'].browse([1]).mapped('partner_id')
            follower_partners = rec.message_follower_ids.mapped('partner_id') - forbidden
            if rec.partner_id:
                follower_partners -= rec.partner_id
            existing_partner_ids = Access.search([
                ('document_id', '=', folder.id)
            ]).mapped('partner_id').ids
            for partner in follower_partners:
                if partner.id in existing_partner_ids:
                    continue
                try:
                    with self.env.cr.savepoint():
                        Access.create({
                            'document_id': folder.id,
                            'partner_id': partner.id,
                            'role': 'edit',
                        })
                except Exception:
                    pass  # constraint — skip safely

    # ── Portal access creation ────────────────────────────────────────────
    def _create_portal_access_if_needed(self):
        """For opportunities with probability >= 50%, auto-create portal access
        for the linked contact using phone as login and password."""
        for rec in self:
            prob = float(rec.jhm_probability or 0)
            if prob < 50:
                continue
            partner = rec.partner_id
            if not partner:
                continue
            phone = partner.phone or rec.phone
            if not phone:
                continue
            phone = phone.strip()
            # Skip if portal user already exists for this partner
            existing_user = self.env['res.users'].sudo().search(
                [('partner_id', '=', partner.id), ('share', '=', True)], limit=1
            )
            if existing_user:
                continue
            # Also skip if login already taken
            login_taken = self.env['res.users'].sudo().search(
                [('login', '=', phone)], limit=1
            )
            if login_taken:
                continue
            group_portal = self.env.ref('base.group_portal')
            company = partner.company_id or rec.company_id or self.env.company
            user = self.env['res.users'].sudo().with_context(
                no_reset_password=True
            )._create_user_from_template({
                'name': partner.name,
                'login': phone,
                'partner_id': partner.id,
                'company_id': company.id,
                'company_ids': [(6, 0, [company.id])],
            })
            user.sudo().write({
                'active': True,
                'group_ids': [(4, group_portal.id)],
            })
            user.sudo()._set_encrypted_password(
                user.id,
                self.env['res.users']._crypt_context().hash(phone)
            )

    # ── Pre-fill from partner when partner is selected ────────────────────
    @api.onchange('partner_id')
    def _onchange_partner_jhm_fields(self):
        for rec in self:
            if rec.partner_id:
                for crm_field, partner_field in _CRM_TO_PARTNER.items():
                    rec[crm_field] = rec.partner_id[partner_field]

    # ── Sync JHM fields → partner when edited in CRM ─────────────────────
    @api.onchange(*list(_CRM_TO_PARTNER.keys()))
    def _onchange_jhm_fields_to_partner(self):
        for rec in self:
            if rec.partner_id:
                for crm_field, partner_field in _CRM_TO_PARTNER.items():
                    rec.partner_id[partner_field] = rec[crm_field]

    # ── Opportunity name auto-build ───────────────────────────────────────
    def _build_opportunity_name(self):
        """[Immigration Country]-[Visa Program]-[Contact Name]"""
        # Prefer first+last if filled, fall back to partner name or contact_name
        fn = self.partner_first_name or ''
        ln = self.partner_last_name or ''
        full_name = ' '.join(filter(None, [fn, ln]))
        if not full_name:
            full_name = (self.partner_id.name or self.contact_name or '').strip()
        if not full_name:
            return None
        parts = []
        if self.partner_immigration_country:
            parts.append(self.partner_immigration_country)
        if self.partner_visa_program_id:
            parts.append(self.partner_visa_program_id.name)
        parts.append(full_name)
        return '-'.join(parts)

    @api.onchange(
        'partner_first_name', 'partner_last_name',
        'partner_id', 'contact_name',
        'partner_visa_program_id', 'partner_immigration_country',
    )
    def _onchange_opportunity_name(self):
        for rec in self:
            opp_name = rec._build_opportunity_name()
            if opp_name:
                rec.name = opp_name

    # ── Persist on create ────────────────────────────────────────────────
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            self._apply_time_to_close(vals)
        records = super().create(vals_list)
        if self.env.context.get('jhm_no_sync'):
            return records
        for rec in records:
            fn = rec.partner_first_name or ''
            ln = rec.partner_last_name or ''
            full_name = ' '.join(filter(None, [fn, ln]))

            if not rec.partner_id and full_name:
                # Auto-create a contact from the opportunity data
                partner_vals = {
                    'name': full_name,
                    'first_name': fn,
                    'last_name': ln,
                    'company_id': rec.company_id.id or False,
                    'is_company': False,
                }
                # Add email/phone from the lead
                if rec.email_from:
                    partner_vals['email'] = rec.email_from
                if rec.phone:
                    partner_vals['phone'] = rec.phone
                # Add all JHM fields
                for crm_field, partner_field in _CRM_TO_PARTNER.items():
                    val = rec[crm_field]
                    if val:
                        if hasattr(val, 'id'):
                            partner_vals[partner_field] = val.id
                        else:
                            partner_vals[partner_field] = val
                partner = self.env['res.partner'].with_context(jhm_no_sync=True).create(partner_vals)
                rec.with_context(jhm_no_sync=True).write({'partner_id': partner.id})

            elif rec.partner_id:
                # Partner already linked — sync JHM fields to it
                partner_vals = {
                    pf: rec[cf].id if hasattr(rec[cf], 'id') else rec[cf]
                    for cf, pf in _CRM_TO_PARTNER.items()
                    if rec[cf]
                }
                if fn or ln:
                    partner_vals['first_name'] = fn
                    partner_vals['last_name'] = ln
                if partner_vals:
                    rec.partner_id.with_context(jhm_no_sync=True).write(partner_vals)

        if not self.env.context.get('jhm_import'):
            for rec in records:
                rec._sync_assignment_followers()
            # Apply HK stage probability for newly created records
            records._apply_hk_stage_probability()
            # Create document + portal access if probability >= 50%
            try:
                with self.env.cr.savepoint():
                    records._create_met_followup_document()
            except Exception as e:
                _logger.warning("Document creation failed on create: %s", e)
            try:
                with self.env.cr.savepoint():
                    records._create_portal_access_if_needed()
            except Exception as e:
                _logger.warning("Portal access creation failed on create: %s", e)
        return records

    # ── Persist on write ─────────────────────────────────────────────────
    def write(self, vals):
        if vals.get('jhm_probability'):
            vals['probability'] = float(vals['jhm_probability'])

        # Apply time_to_close → overwrite date_deadline
        if 'time_to_close' in vals:
            self._apply_time_to_close(vals)

        # Capture co_owner state before write for change logging
        old_co_owners = {}
        if 'co_owner_ids' in vals:
            for rec in self:
                old_co_owners[rec.id] = set(rec.co_owner_ids.ids)

        result = super().write(vals)

        # Log co_owner additions for the daily sales report
        if 'co_owner_ids' in vals:
            today = fields.Date.today()
            for rec in self:
                added = len(set(rec.co_owner_ids.ids) - old_co_owners.get(rec.id, set()))
                if added > 0 and rec.user_id:
                    self.env['jhm.co.owner.log'].sudo().create({
                        'lead_id': rec.id,
                        'lead_user_id': rec.user_id.id,
                        'added_count': added,
                        'log_date': today,
                    })

        # Sync opportunity name
        name_triggers = {
            'partner_first_name', 'partner_last_name',
            'partner_id', 'contact_name',
            'partner_immigration_country', 'partner_visa_program_id',
        }
        if name_triggers & set(vals):
            for rec in self:
                opp_name = rec._build_opportunity_name()
                if opp_name:
                    super(CrmLead, rec).write({'name': opp_name})

        # Sync JHM fields to partner
        jhm_vals_in_write = {
            k: v for k, v in vals.items() if k in _CRM_TO_PARTNER
        }
        if jhm_vals_in_write and not self.env.context.get('jhm_no_sync'):
            partner_vals = {
                _CRM_TO_PARTNER[cf]: v
                for cf, v in jhm_vals_in_write.items()
            }
            for rec in self:
                if rec.partner_id:
                    rec.partner_id.with_context(jhm_no_sync=True).write(partner_vals)

        # Sync followers when assignment fields change
        assignment_keys = {'user_id', 'co_owner_ids', 'process_team_ids', 'process_2_ids'}
        if assignment_keys & set(vals):
            for rec in self:
                rec._sync_assignment_followers()

        # Trigger spouse contact creation when spouse fields are set in CRM
        spouse_keys = {'partner_spouse_name', 'partner_spouse_phone', 'partner_spouse_email'}
        if spouse_keys & set(vals):
            for rec in self:
                if rec.partner_id:
                    rec.partner_id._sync_spouse_contact()

        # Apply HK stage probability when stage changes
        if 'stage_id' in vals:
            self._apply_hk_stage_probability()

        # Create document and portal access when probability reaches >= 50%
        if 'stage_id' in vals or 'jhm_probability' in vals:
            try:
                with self.env.cr.savepoint():
                    self._create_met_followup_document()
            except Exception as e:
                _logger.warning("Document creation failed: %s", e)
            try:
                with self.env.cr.savepoint():
                    self._create_portal_access_if_needed()
            except Exception as e:
                _logger.warning("Portal access creation failed: %s", e)

        # Auto-update Last Call Date when a meaningful action occurs
        _ACTION_FIELDS = {
            'stage_id', 'jhm_probability', 'probability',
            'partner_appointment_date', 'partner_appointment_date_2',
            'partner_appointment_notes', 'partner_chat_log',
            'partner_jhm_description', 'partner_facing_problems',
            'partner_sf_followup_date',
        }
        if (_ACTION_FIELDS & set(vals)) and not self.env.context.get('jhm_import'):
            today = fields.Date.today()
            for rec in self:
                if rec.partner_last_call_date != today:
                    super(CrmLead, rec).write({'partner_last_call_date': today})

        return result

    # ── Followup overdue notification cron ────────────────────────────────
    @api.model
    def _cron_followup_overdue_notification(self):
        """Notify salesperson when Last Call Date < Followup Date and
        probability is between 50% and 90% (inclusive)."""
        today = fields.Date.today()
        leads = self.search([
            ('partner_sf_followup_date', '!=', False),
            ('partner_sf_followup_date', '<=', today),
            ('partner_last_call_date', '<', today),
            ('probability', '>=', 50),
            ('probability', '<=', 90),
            ('user_id', '!=', False),
            ('active', '=', True),
            ('type', '=', 'opportunity'),
        ])
        for lead in leads:
            if lead.partner_last_call_date and lead.partner_sf_followup_date \
                    and lead.partner_last_call_date < lead.partner_sf_followup_date:
                lead.activity_schedule(
                    'mail.mail_activity_data_todo',
                    date_deadline=today,
                    summary='Followup overdue: %s' % lead.name,
                    note='The followup date (%s) has passed and no action has been '
                         'taken since %s. Please follow up on this opportunity.'
                         % (lead.partner_sf_followup_date, lead.partner_last_call_date),
                    user_id=lead.user_id.id,
                )

    def action_sale_quotations_new_jhm(self):
        """Create a new quotation under 'JHM HK' company."""
        jhm_company = self.env['res.company'].sudo().search(
            [('name', '=', 'JHM HK')], limit=1
        )
        if not jhm_company:
            from odoo.exceptions import UserError
            raise UserError('Company "JHM HK" not found.')
        if not self.partner_id:
            return self.env["ir.actions.actions"]._for_xml_id("sale_crm.crm_quotation_partner_action")
        action = self.env["ir.actions.actions"]._for_xml_id("sale_crm.sale_action_quotations_new")
        ctx = self._prepare_opportunity_quotation_context()
        ctx['default_company_id'] = jhm_company.id
        ctx['search_default_opportunity_id'] = self.id
        action['context'] = ctx
        return action

    def action_open_contact_sync_wizard(self):
        """Open the contact sync wizard pre-loaded with this opportunity."""
        return {
            'type':      'ir.actions.act_window',
            'name':      'Sync Contact',
            'res_model': 'jhm.crm.contact.sync.wizard',
            'view_mode': 'form',
            'target':    'new',
            'context': {
                'active_ids':   self.ids,
                'active_model': 'crm.lead',
            },
        }

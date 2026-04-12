import logging
from odoo import api, fields, models

_logger = logging.getLogger(__name__)

PROBABILITY_SELECTION = [
    ('10', '10%'),
    ('30', '30%'),
    ('50', '50%'),
    ('70', '70%'),
    ('90', '90%'),
    ('100', '100%'),
]

MET_FOLLOW_UP_STAGE_ID = 8   # Met & Follow Up stage for John Hu Migration

# HK stage ID → probability string
_HK_STAGE_PROBABILITY = {
    5: '10',   # New Lead
    6: '30',   # Valid Whatsapp Op
    7: '50',   # Appointment
    8: '70',   # Met & Follow Up
    9: '90',   # Service Agreement
    10: '90',  # Ready to Close
}

# Maps each standalone crm.lead field → the matching res.partner field name
_CRM_TO_PARTNER = {
    'partner_gender': 'gender',
    'partner_client_nationality_id': 'client_nationality_id',
    'partner_jhm_line_id': 'jhm_line_id',
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
    'partner_appointment_notes': 'appointment_notes',
    'partner_last_call_date': 'last_call_date',
    'partner_sf_followup_date': 'sf_followup_date',
    'partner_chat_log': 'chat_log',
    'partner_jhm_description': 'jhm_description',
    'partner_spouse_name': 'spouse_name',
    'partner_spouse_phone': 'spouse_phone',
    'partner_spouse_email': 'spouse_email',
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
    partner_facing_problems = fields.Char(string='Facing Problems')
    partner_consultation_fee_paid = fields.Char(string='Consultation Fee Paid')
    partner_sf_creation_date = fields.Date(string='SF Creation Date')
    partner_appointment_date = fields.Date(string='Appointment Date', tracking=True)
    partner_appointment_notes = fields.Char(string='Appointment Notes')
    partner_last_call_date = fields.Date(string='Last Call Date', tracking=True)
    partner_sf_followup_date = fields.Date(string='SF Followup Date')
    partner_chat_log = fields.Text(string='Chat Log')
    partner_jhm_description = fields.Text(string='Description')
    partner_spouse_name = fields.Char(string='Spouse Name')
    partner_spouse_phone = fields.Char(string='Spouse Phone')
    partner_spouse_email = fields.Char(string='Spouse Email')

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

    # ── Stage → probability (HK company only) ────────────────────────────
    def _apply_hk_stage_probability(self):
        """If the opportunity belongs to John Hu Migration Consulting Ltd.,
        auto-set jhm_probability based on the current stage."""
        hk_company = self.env.ref('base.main_company', raise_if_not_found=False)
        # Find JHM HK company by name in case ref differs
        jhm_hk = self.env['res.company'].search(
            [('name', 'like', 'John Hu Migration')], limit=1
        )
        for rec in self:
            if jhm_hk and rec.company_id.id == jhm_hk.id:
                prob = _HK_STAGE_PROBABILITY.get(rec.stage_id.id)
                if prob:
                    rec.jhm_probability = prob
                    rec.probability = float(prob)

    @api.onchange('stage_id')
    def _onchange_stage_probability(self):
        self._apply_hk_stage_probability()

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

        return result

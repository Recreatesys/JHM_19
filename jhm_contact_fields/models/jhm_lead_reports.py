from odoo import fields, models


class JhmLeadPerformanceLine(models.Model):
    """Lead Performance Report — rows = Lead Source (ALL, even zero),
    columns = Visa Program × Probability."""
    _name = 'jhm.lead.performance.line'
    _description = 'Lead Performance Report'
    _auto = False
    _rec_name = 'lead_source_id'
    _order = 'probability_sort, lead_source_id'

    lead_source_id  = fields.Many2one('jhm.lead.source',  string='Lead Source',  readonly=True)
    visa_program_id = fields.Many2one('jhm.visa.program', string='Visa Program', readonly=True)
    probability     = fields.Char(string='Probability', readonly=True)
    probability_sort = fields.Integer(string='Probability Sort', readonly=True)
    lead_count      = fields.Integer(string='# Leads', readonly=True)

    def init(self):
        self.env.cr.execute("DROP VIEW IF EXISTS jhm_lead_performance_line CASCADE")
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW jhm_lead_performance_line AS
            WITH combos AS (
                -- All lead sources × all visa programs × all probabilities that appear in leads
                SELECT
                    ls.id  AS lead_source_id,
                    cl.partner_visa_program_id AS visa_program_id,
                    cl.jhm_probability         AS probability
                FROM jhm_lead_source ls
                CROSS JOIN (
                    SELECT DISTINCT partner_visa_program_id, jhm_probability
                    FROM crm_lead
                    WHERE type = 'opportunity'
                ) cl

                UNION

                -- Ensure every lead source appears at least once (with NULLs)
                SELECT ls.id, NULL::integer, NULL::varchar
                FROM jhm_lead_source ls
            ),
            counts AS (
                SELECT
                    partner_jhm_lead_source_id AS lead_source_id,
                    partner_visa_program_id    AS visa_program_id,
                    jhm_probability            AS probability,
                    COUNT(*)                   AS lead_count
                FROM crm_lead
                WHERE type = 'opportunity'
                GROUP BY 1, 2, 3
            )
            SELECT
                row_number() OVER ()          AS id,
                c.lead_source_id,
                c.visa_program_id,
                c.probability,
                CASE WHEN c.probability ~ '^\d+$' THEN c.probability::int ELSE 0 END AS probability_sort,
                COALESCE(cnt.lead_count, 0)   AS lead_count
            FROM combos c
            LEFT JOIN counts cnt
                ON cnt.lead_source_id IS NOT DISTINCT FROM c.lead_source_id
               AND cnt.visa_program_id IS NOT DISTINCT FROM c.visa_program_id
               AND cnt.probability     IS NOT DISTINCT FROM c.probability
        """)


class JhmQualifiedLeadLine(models.Model):
    """Qualified Lead Report — leads with probability >= 30%,
    grouped by Salesperson × Probability × Create Month."""
    _name = 'jhm.qualified.lead.line'
    _description = 'Qualified Lead Report'
    _auto = False
    _rec_name = 'user_id'
    _order = 'create_month desc, probability_sort, user_id'

    user_id      = fields.Many2one('res.users', string='Salesperson',  readonly=True)
    probability  = fields.Char(string='Probability', readonly=True)
    probability_sort = fields.Integer(string='Probability Sort', readonly=True)
    create_month = fields.Date(string='Create Date', readonly=True)
    lead_count   = fields.Integer(string='# Qualified Leads', readonly=True)

    def init(self):
        self.env.cr.execute("DROP VIEW IF EXISTS jhm_qualified_lead_line CASCADE")
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW jhm_qualified_lead_line AS
            SELECT
                row_number() OVER ()                                         AS id,
                user_id,
                jhm_probability                                              AS probability,
                CASE WHEN jhm_probability ~ '^\d+$' THEN jhm_probability::int ELSE 0 END AS probability_sort,
                date_trunc('month', create_date AT TIME ZONE 'UTC')::date   AS create_month,
                COUNT(*)                                                     AS lead_count
            FROM crm_lead
            WHERE type = 'opportunity'
              AND probability >= 30
              AND user_id IS NOT NULL
            GROUP BY user_id, jhm_probability, create_month
        """)


class JhmAppointmentLine(models.Model):
    """Lead to Appointment Report — one row per (salesperson, visa program, appointment date)."""
    _name = 'jhm.appointment.line'
    _description = 'Lead to Appointment Report'
    _auto = False
    _rec_name = 'user_id'
    _order = 'appointment_date desc, user_id'

    user_id         = fields.Many2one('res.users',        string='Salesperson',   readonly=True)
    visa_program_id = fields.Many2one('jhm.visa.program', string='Visa Program',  readonly=True)
    appointment_date = fields.Date(string='Appointment Date', readonly=True)
    appointment_count = fields.Integer(string='# Appointments', readonly=True)

    def init(self):
        self.env.cr.execute("DROP VIEW IF EXISTS jhm_appointment_line CASCADE")
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW jhm_appointment_line AS
            SELECT
                row_number() OVER ()             AS id,
                user_id,
                partner_visa_program_id          AS visa_program_id,
                partner_appointment_date         AS appointment_date,
                COUNT(*)                         AS appointment_count
            FROM crm_lead
            WHERE type = 'opportunity'
              AND partner_appointment_date IS NOT NULL
            GROUP BY user_id, partner_visa_program_id, partner_appointment_date
        """)


class JhmFollowUpLine(models.Model):
    """Follow Up Report — one row per (salesperson, visa program, create date, follow-up date)."""
    _name = 'jhm.follow.up.line'
    _description = 'Follow Up Report'
    _auto = False
    _rec_name = 'user_id'
    _order = 'followup_date desc, user_id'

    user_id         = fields.Many2one('res.users',        string='Salesperson',   readonly=True)
    visa_program_id = fields.Many2one('jhm.visa.program', string='Visa Program',  readonly=True)
    create_date     = fields.Date(string='Create Date',   readonly=True)
    followup_date   = fields.Date(string='Follow Up Date', readonly=True)
    lead_count      = fields.Integer(string='Count',      readonly=True)

    def init(self):
        self.env.cr.execute("DROP VIEW IF EXISTS jhm_follow_up_line CASCADE")
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW jhm_follow_up_line AS
            SELECT
                row_number() OVER ()                                        AS id,
                user_id,
                partner_visa_program_id                                     AS visa_program_id,
                date_trunc('day', create_date AT TIME ZONE 'UTC')::date     AS create_date,
                partner_sf_followup_date                                    AS followup_date,
                COUNT(*)                                                    AS lead_count
            FROM crm_lead
            WHERE type = 'opportunity'
              AND user_id IS NOT NULL
            GROUP BY user_id, partner_visa_program_id, create_date, partner_sf_followup_date
        """)


class JhmSalesChannelLine(models.Model):
    """Sales Report by Channel — Rows: Industry | Cols: Lead Source (ALL, even zero)
    Measure: Invoiced Amount (posted invoices from sale orders)."""
    _name = 'jhm.sales.channel.line'
    _description = 'Sales Report by Channel'
    _auto = False
    _rec_name = 'lead_source_id'
    _order = 'industry_id, lead_source_id'

    industry_id    = fields.Many2one('res.partner.industry', string='Industry',    readonly=True)
    lead_source_id = fields.Many2one('jhm.lead.source',      string='Lead Source', readonly=True)
    invoiced_amount = fields.Float(string='Invoiced Amount', digits=(16, 2),       readonly=True)

    def init(self):
        self.env.cr.execute("DROP VIEW IF EXISTS jhm_sales_channel_line CASCADE")
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW jhm_sales_channel_line AS
            WITH combos AS (
                -- Every industry × every lead source (ensures all appear even with 0)
                SELECT pi.id AS industry_id, ls.id AS lead_source_id
                FROM res_partner_industry pi
                CROSS JOIN jhm_lead_source ls

                UNION

                -- NULL industry row so lead sources without an industry still appear
                SELECT NULL::integer AS industry_id, ls.id AS lead_source_id
                FROM jhm_lead_source ls
            ),
            invoiced AS (
                -- Distinct invoice total per opportunity to avoid line-level duplication
                SELECT
                    rp.industry_id,
                    cl.partner_jhm_lead_source_id             AS lead_source_id,
                    SUM(am_agg.amount_untaxed)                AS invoiced_amount
                FROM (
                    SELECT DISTINCT am.id, am.amount_untaxed, sol.order_id
                    FROM sale_order_line sol
                    JOIN sale_order_line_invoice_rel rel ON rel.order_line_id = sol.id
                    JOIN account_move_line aml ON aml.id = rel.invoice_line_id
                    JOIN account_move am ON am.id = aml.move_id
                    WHERE am.move_type = 'out_invoice'
                      AND am.state     = 'posted'
                ) am_agg
                JOIN sale_order so ON so.id = am_agg.order_id
                LEFT JOIN crm_lead cl ON cl.id = so.opportunity_id
                LEFT JOIN res_partner rp ON rp.id = so.partner_id
                GROUP BY rp.industry_id, cl.partner_jhm_lead_source_id
            )
            SELECT
                row_number() OVER ()             AS id,
                c.industry_id,
                c.lead_source_id,
                COALESCE(inv.invoiced_amount, 0) AS invoiced_amount
            FROM combos c
            LEFT JOIN invoiced inv
                ON inv.industry_id    IS NOT DISTINCT FROM c.industry_id
               AND inv.lead_source_id IS NOT DISTINCT FROM c.lead_source_id
        """)

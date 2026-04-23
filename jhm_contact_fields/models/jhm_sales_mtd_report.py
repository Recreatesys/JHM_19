import math
from odoo import api, fields, models


class JhmSalesMtdLine(models.Model):
    """SQL view: one row per (salesperson × visa_program × month).
    Backs the 'Sales Report (MTD)' pivot in CRM → Reporting.

    Definitions:
      - New Leads:       leads assigned to the salesperson within the period
                         (date_open falls in the month)
      - Qualified Leads: subset of New Leads with probability >= 50%
      - Appointment:     subset of New Leads with partner_appointment_date
                         within the period
      - Sales #:         sale orders created in the period from New Leads only
      - Sales $:         total amount of those sale orders
      - % conversions:   computed in Python so pivot totals don't sum them
    """
    _name = 'jhm.sales.mtd.line'
    _description = 'Sales Report (MTD)'
    _auto = False
    _rec_name = 'user_id'
    _order = 'month desc, user_id'

    user_id          = fields.Many2one('res.users',       string='Salesperson',  readonly=True)
    visa_program_id  = fields.Many2one('jhm.visa.program', string='Visa Program', readonly=True)
    month            = fields.Date(string='Month', readonly=True)

    new_leads           = fields.Integer(string='New Leads',              readonly=True)
    qualified_leads     = fields.Integer(string='Qualified Leads',        readonly=True)
    qualified_pct       = fields.Integer(string='% Qualified',            readonly=True,
                                         compute='_compute_pct', aggregator='avg')
    appointments        = fields.Integer(string='Appointment',            readonly=True)
    appointment_pct     = fields.Integer(string='% Appointment',          readonly=True,
                                         compute='_compute_pct', aggregator='avg')
    sales_count         = fields.Integer(string='Sales #',                readonly=True)
    sales_pct           = fields.Integer(string='% Sales',                readonly=True,
                                         compute='_compute_pct', aggregator='avg')
    sales_amount        = fields.Float(string='Sales $',                  readonly=True, digits=(16, 2))

    @api.depends('new_leads', 'qualified_leads', 'appointments', 'sales_count')
    def _compute_pct(self):
        for rec in self:
            nl = rec.new_leads or 0
            ql = rec.qualified_leads or 0
            ap = rec.appointments or 0
            sc = rec.sales_count or 0
            rec.qualified_pct = math.ceil(ql / nl * 100) if nl > 0 else 0
            rec.appointment_pct = math.ceil(ap / nl * 100) if nl > 0 else 0
            rec.sales_pct = math.ceil(sc / ql * 100) if ql > 0 else 0

    def init(self):
        self.env.cr.execute("DROP VIEW IF EXISTS jhm_sales_mtd_line CASCADE")
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW jhm_sales_mtd_line AS
            WITH

            -- New Leads: assigned to salesperson in the month (date_open)
            nl AS (
                SELECT user_id,
                       partner_visa_program_id          AS visa_program_id,
                       date_trunc('month', date_open AT TIME ZONE 'UTC')::date AS month,
                       COUNT(*) AS cnt
                FROM crm_lead
                WHERE type = 'opportunity'
                  AND user_id IS NOT NULL
                  AND date_open IS NOT NULL
                GROUP BY 1, 2, 3
            ),

            -- Qualified Leads: assigned in the month AND probability >= 50
            ql AS (
                SELECT user_id,
                       partner_visa_program_id          AS visa_program_id,
                       date_trunc('month', date_open AT TIME ZONE 'UTC')::date AS month,
                       COUNT(*) AS cnt
                FROM crm_lead
                WHERE type = 'opportunity'
                  AND user_id IS NOT NULL
                  AND date_open IS NOT NULL
                  AND probability >= 50
                GROUP BY 1, 2, 3
            ),

            -- Appointments: assigned in the month AND appointment_date within same month
            ap AS (
                SELECT user_id,
                       partner_visa_program_id          AS visa_program_id,
                       date_trunc('month', date_open AT TIME ZONE 'UTC')::date AS month,
                       COUNT(*) AS cnt
                FROM crm_lead
                WHERE type = 'opportunity'
                  AND user_id IS NOT NULL
                  AND date_open IS NOT NULL
                  AND partner_appointment_date IS NOT NULL
                  AND date_trunc('month', date_open AT TIME ZONE 'UTC')
                    = date_trunc('month', partner_appointment_date)
                GROUP BY 1, 2, 3
            ),

            -- Sales: sale orders from leads assigned in the period,
            --        with order date also in the same period
            so AS (
                SELECT cl.user_id,
                       cl.partner_visa_program_id       AS visa_program_id,
                       date_trunc('month', cl.date_open AT TIME ZONE 'UTC')::date AS month,
                       COUNT(DISTINCT s.id)             AS cnt,
                       SUM(s.amount_untaxed)            AS amt
                FROM sale_order s
                JOIN crm_lead cl
                    ON cl.id = s.opportunity_id
                   AND cl.user_id IS NOT NULL
                   AND cl.date_open IS NOT NULL
                WHERE s.state NOT IN ('cancel')
                  AND date_trunc('month', s.date_order AT TIME ZONE 'UTC')
                    = date_trunc('month', cl.date_open AT TIME ZONE 'UTC')
                GROUP BY 1, 2, 3
            ),

            -- All combos from new leads (the anchor)
            combos AS (
                SELECT DISTINCT user_id, visa_program_id, month FROM nl
            )

            SELECT
                row_number() OVER ()         AS id,
                c.user_id,
                c.visa_program_id,
                c.month,
                COALESCE(nl.cnt,  0)         AS new_leads,
                COALESCE(ql.cnt,  0)         AS qualified_leads,
                COALESCE(ap.cnt,  0)         AS appointments,
                COALESCE(so.cnt,  0)         AS sales_count,
                COALESCE(so.amt,  0.0)       AS sales_amount
            FROM combos c
            LEFT JOIN nl ON nl.user_id = c.user_id AND nl.visa_program_id IS NOT DISTINCT FROM c.visa_program_id AND nl.month = c.month
            LEFT JOIN ql ON ql.user_id = c.user_id AND ql.visa_program_id IS NOT DISTINCT FROM c.visa_program_id AND ql.month = c.month
            LEFT JOIN ap ON ap.user_id = c.user_id AND ap.visa_program_id IS NOT DISTINCT FROM c.visa_program_id AND ap.month = c.month
            LEFT JOIN so ON so.user_id = c.user_id AND so.visa_program_id IS NOT DISTINCT FROM c.visa_program_id AND so.month = c.month
        """)

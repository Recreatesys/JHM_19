from odoo import fields, models


class JhmSalesMtdLine(models.Model):
    """SQL view: one row per (salesperson × month).
    Backs the 'Sales Report (MTD)' pivot in CRM → Reporting."""
    _name = 'jhm.sales.mtd.line'
    _description = 'Sales Report (MTD)'
    _auto = False
    _rec_name = 'user_id'
    _order = 'month desc, user_id'

    user_id          = fields.Many2one('res.users',       string='Salesperson',  readonly=True)
    visa_program_id  = fields.Many2one('jhm.visa.program', string='Visa Program', readonly=True)
    month            = fields.Date(string='Month', readonly=True)

    new_leads      = fields.Integer(string='New Leads',       readonly=True)
    qualified_leads = fields.Integer(string='Qualified Leads', readonly=True)
    appointments   = fields.Integer(string='Appointment',     readonly=True)
    sales_count    = fields.Integer(string='Sales #',         readonly=True)
    sales_amount   = fields.Float(string='Sales $',           readonly=True, digits=(16, 2))

    def init(self):
        self.env.cr.execute("DROP VIEW IF EXISTS jhm_sales_mtd_line CASCADE")
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW jhm_sales_mtd_line AS
            WITH

            -- All (salesperson, visa_program, month) combos that have any data
            combos AS (
                -- leads created
                SELECT user_id,
                       partner_visa_program_id          AS visa_program_id,
                       date_trunc('month', create_date AT TIME ZONE 'UTC')::date AS month
                FROM crm_lead
                WHERE type = 'opportunity' AND user_id IS NOT NULL

                UNION

                -- appointment months
                SELECT user_id,
                       partner_visa_program_id          AS visa_program_id,
                       date_trunc('month', partner_appointment_date)::date AS month
                FROM crm_lead
                WHERE type = 'opportunity'
                  AND user_id IS NOT NULL
                  AND partner_appointment_date IS NOT NULL

                UNION

                -- sale order months (via opportunity)
                SELECT cl.user_id,
                       cl.partner_visa_program_id       AS visa_program_id,
                       date_trunc('month', so.date_order AT TIME ZONE 'UTC')::date AS month
                FROM sale_order so
                JOIN crm_lead cl
                    ON cl.id = so.opportunity_id
                   AND cl.user_id IS NOT NULL
                WHERE so.state NOT IN ('cancel')
            ),

            -- New leads: created in the month
            nl AS (
                SELECT user_id,
                       partner_visa_program_id          AS visa_program_id,
                       date_trunc('month', create_date AT TIME ZONE 'UTC')::date AS month,
                       COUNT(*) AS cnt
                FROM crm_lead
                WHERE type = 'opportunity' AND user_id IS NOT NULL
                GROUP BY 1, 2, 3
            ),

            -- Qualified leads: probability >= 30%, grouped by creation month
            ql AS (
                SELECT user_id,
                       partner_visa_program_id          AS visa_program_id,
                       date_trunc('month', create_date AT TIME ZONE 'UTC')::date AS month,
                       COUNT(*) AS cnt
                FROM crm_lead
                WHERE type = 'opportunity'
                  AND user_id IS NOT NULL
                  AND probability >= 30
                GROUP BY 1, 2, 3
            ),

            -- Appointments: partner_appointment_date falls in the month
            ap AS (
                SELECT user_id,
                       partner_visa_program_id          AS visa_program_id,
                       date_trunc('month', partner_appointment_date)::date AS month,
                       COUNT(*) AS cnt
                FROM crm_lead
                WHERE type = 'opportunity'
                  AND user_id IS NOT NULL
                  AND partner_appointment_date IS NOT NULL
                GROUP BY 1, 2, 3
            ),

            -- Sales: sale orders linked via opportunity, grouped by order date
            so AS (
                SELECT cl.user_id,
                       cl.partner_visa_program_id       AS visa_program_id,
                       date_trunc('month', s.date_order AT TIME ZONE 'UTC')::date AS month,
                       COUNT(DISTINCT s.id)             AS cnt,
                       SUM(s.amount_untaxed)            AS amt
                FROM sale_order s
                JOIN crm_lead cl
                    ON cl.id = s.opportunity_id
                   AND cl.user_id IS NOT NULL
                WHERE s.state NOT IN ('cancel')
                GROUP BY 1, 2, 3
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

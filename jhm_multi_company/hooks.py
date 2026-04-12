"""
Post-install / post-upgrade hooks for jhm_multi_company.
These run as Python code and bypass the ir.model.data noupdate flag,
ensuring the partner rule and user partner settings are always correct.
"""


def post_install_hook(env):
    _apply_settings(env)


def post_upgrade_hook(env):
    _apply_settings(env)


def _apply_settings(env):
    # Force the partner record rule to use user.company_ids (all allowed companies)
    # instead of company_ids (only the currently active session companies).
    # This lets multi-company admins read contacts across all their companies.
    rule = env.ref('base.res_partner_rule', raise_if_not_found=False)
    if rule:
        rule.write({
            'domain_force': (
                "['|', ('company_id', 'in', user.company_ids.ids), "
                "('company_id', '=', False)]"
            )
        })
        # Ensure future module upgrades can also update this rule
        imd = env['ir.model.data'].search([
            ('module', '=', 'base'), ('name', '=', 'res_partner_rule')
        ])
        imd.write({'noupdate': False})

    # Internal user partners should have no company restriction so they are
    # always accessible regardless of which company is active in the session.
    internal_users = env['res.users'].search([('share', '=', False)])
    partner_ids = internal_users.mapped('partner_id').filtered('company_id')
    if partner_ids:
        partner_ids.write({'company_id': False})

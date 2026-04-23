from . import models


def _post_init_hook(env):
    """Patch base CRM lead record rules to enforce current-company isolation.
    Base rules use company_ids (all user companies) which is too broad."""
    current_company_domain = (
        "['|', ('company_id', '=', False), "
        "('company_id', '=', user.company_id.id)]"
    )
    for xmlid in ('crm.crm_lead_company_rule', 'crm.crm_rule_all_lead'):
        rule = env.ref(xmlid, raise_if_not_found=False)
        if rule:
            rule.sudo().write({'domain_force': current_company_domain})

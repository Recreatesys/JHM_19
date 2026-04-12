{
    'name': 'JHM Multi-Company Isolation',
    'version': '19.0.1.0.0',
    'summary': 'Enforce strict per-company data isolation for JHM entities',
    'category': 'Technical',
    'depends': ['base', 'contacts'],
    'data': [
        'data/ir_rule.xml',
        'data/lang_settings.xml',
    ],
    'post_init_hook': 'post_install_hook',
    'post_update_module_hook': 'post_upgrade_hook',
    'installable': True,
    'auto_install': False,
    'license': 'LGPL-3',
}

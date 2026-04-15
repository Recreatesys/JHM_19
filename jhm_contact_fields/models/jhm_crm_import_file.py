# -*- coding: utf-8 -*-
from odoo import fields, models


class JhmCrmImportFile(models.TransientModel):
    _name = 'jhm.crm.import.file'
    _description = 'JHM CRM Import File'
    _order = 'sequence, id'

    wizard_id      = fields.Many2one('jhm.crm.import.wizard', ondelete='cascade')
    sequence       = fields.Integer(default=10)
    file_data      = fields.Binary('File', attachment=False)
    file_name      = fields.Char('File Name')
    state          = fields.Selection([
        ('pending', 'Pending'),
        ('running', 'Importing'),
        ('done',    'Done'),
        ('error',   'Error'),
    ], default='pending', string='Status')
    imported_count = fields.Integer('Imported',       readonly=True)
    skipped_count  = fields.Integer('Skipped/Errors', readonly=True)
    result_log     = fields.Text(   'Log',            readonly=True)


from odoo import api, models, fields


class AccountChartTemplate(models.Model):
    _inherit = 'account.chart.template'

    @api.multi
    def import_record(self, stacks):
        for stack in stacks:
            migration = stack.migration_id
            relation = stack.model
            obj = migration.connection[0].env[relation].browse(stack.remote_id)

            
            res_id = stack.find_record_by_external_id()
            if not res_id:

                res_id = stack.find_ident_record()
                res_id = res_id and res_id[0]
                
            vals = stack.prepare_vals()
            if not vals and not res_id:
                continue
            
            if not res_id:
                transfer_account = self.env['account.account.template'].create({
                    'code': 113,
                    'name': 'Transfer Account',
                    'reconcile': True,
                    'user_type_id': self.env.ref('account.data_account_type_current_assets').id
                })
                vals.update({'transfer_account_id': transfer_account.id})
                res_id = self.env[relation].create(vals)
                transfer_account.write({'chart_template_id': res_id.id})
                
            elif vals:
                res_id.write(vals)
            stack.update_refs()
            for lang in self.env['res.lang'].search([('code', '!=', self.env.context['lang'])]):
                vals_to_translate = {}
                translated_obj = obj.with_context(lang=lang.code)
                for f in stack.model_id.field_ids.filtered(lambda x: x.ttype in ('char', 'text')):
                    vals_to_translate.update({
                        f.name: getattr(translated_obj, f.name)
                    })
                if vals_to_translate:
                    res_id.with_context(lang=lang.code).write(vals_to_translate)
            stack.write({'state': 'done', 'res_id': res_id.id, 'blocked': False})
            return res_id
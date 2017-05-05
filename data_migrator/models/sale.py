from odoo import api, models, fields


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

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
            
            product_tmpl = obj.product_id.product_tmpl_id
            product_tmpl_model = self.env['migration.model'].search([
                ('name','=','product.template'),
                ('migration_id','=',stack.migration_id.id)])
            local_product_tmpl_st = self.env['migration.stack'].search([
                ('migration_id','=',stack.migration_id.id),
                ('model_id','=',product_tmpl_model.id),
                ('remote_id','=',product_tmpl.id)])
            local_product_tmpl = self.env['product.template'].browse(local_product_tmpl_st.res_id)
            mapping = {
                'metal': 'Metal',
                'bois1': 'Bois 1'
                'bois2': 'Bois 2',
                'patte': 'Patte',
                'tissu': 'Tissu',
                'poignee': 'Poignée'
            }
            attr_values = []
            for k,n in mapping.iteritems():
                attr = getattr(obj, k)
                if attr:
                    local_attr = self.env['product.attribute'].search([('name','=',n)])
                    local_val = local_attr.value_ids.filtered(lambda x: x.code == attr.code_fini)
                    if not local_val:
                        continue
                    attr_values.append(local_val.id)
                    l = self.env['product.attribute.line'].search([
                        ('product_tmpl_id','=',local_product_tmpl.id),
                        ('attribute_id','=', local_attr.id)])
                    if not l:
                        l = self.env['product.attribute.line'].create({
                            'product_tmpl_id':local_product_tmpl.id,
                            'attribute_id': local_attr.id,
                            'value_ids': [(4, local_val.id)]
                        })
                    else:
                        l.write({
                            'value_ids': [(4, local_val.id)]
                        })

            local_product_tmpl.create_variant_ids()
            product = False
            
            for p in local_product_tmpl.product_variant_ids:
                found = True
                for attr_val in attr_values:
                    if not p.attribute_value_ids.filtered(lambda x: x.id == attr_val):
                        found = False
                if found:
                    product_id = p
            if not product:
                product = self.env['product.product'].create({
                    'product_tmpl_id': tmpl_id.id,
                    'attribute_value_ids': [(6, 0, attr_values)]
                })

            vals.update({'product_id': product.id})
            product.write({'price': obj.price_unit})

            if not res_id:
                res_id = self.env[relation].create(vals)
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


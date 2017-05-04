
from odoo import api, models, fields


class ProductAttributeValue(models.Model):
    _inherit = 'product.attribute.value'

    def import_record(self, stacks):
        for stack in stacks:
            obj = stack.migration_id.connection[0].env['product.finition'].browse(stack.remote_id)
            if obj.type_fini_id:
                type_fini_id = obj.type_fini_id.name
            else:
                stack.write({'state': 'done'})
                continue
            attrs = []
            attr = self.env['product.attribute'].search([('name','=',type_fini_id)])
            if attr:
                attrs.append(attr)
            if not attrs:
                attrs.append(self.env['product.attribute'].create({'name': type_fini_id}))
                if type_fini_id == 'Bois':
                    attrs.append(self.env['product.attribute'].create({'name': '%s 2' % type_fini_id}))
            elif type_fini_id == 'Bois':
                attrs.append(self.env['product.attribute'].search([('name', '=', '%s 2' % type_fini_id)]))
            for a in attrs:
                if not self.env['product.attribute.value'].search([('code','=',obj.code_fini), ('attribute_id','=',a.id)]):
                    name = obj.couleur_finien or obj.couleur_finifr
                    if self.env['product.attribute.value'].search([('name','=',name)]):
                        name = '%s %s' % (obj.code_fini, name)
                    value = self.env['product.attribute.value'].create({
                        'code': obj.code_fini,
                        'name': name,
                        'description': obj.desc_finien or obj.desc_finifr,
                        'image_name': obj.fi_ficphoto,
                        'fi_sorte': obj.fi_sorte and obj.fi_sorte.name,
                        'attribute_id': a.id
                    })

                    value.with_context(lang='fr_FR').write({
                        'name': obj.couleur_finifr,
                        'description': obj.desc_finifr
                    })
                    stack.write({'state': 'done', 'res_id': value and value.id})
                else:
                    stack.write({'state': 'done'})
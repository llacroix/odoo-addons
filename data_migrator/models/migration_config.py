# -*- coding: utf-8 -*-
import odoorpc
from odoo import api, models, fields

EXCLUDE_FIELDS = ['id', 'create_uid', 'create_date', 'write_uid', 'write_date', '__last_update']
STACK_STATE = [
    ('queued', 'Queued'),
    ('done', 'Done'),
    ('failed', 'Failed')
]

EXCEPTIONS = {'sale_refund': 'sale', 'purchase_refund': 'purchase', 'procent': 'percent', 'product': 'consu',
    'waiting_date':'sale', 'progress':'sale', 'manual':'sale', 'shipping_except':'sale', 'invoice_except':'sale'}

class MigrationConfig(models.Model):
    _name = 'migration.config'
    _connection = False
    _id_map = {}

    name = fields.Char('Name')
    address = fields.Char('Remote Address')
    database = fields.Char('Remote Database')
    login = fields.Char('Remote Login')
    password = fields.Char('Remote Password')

    include_pattern_ids = fields.Many2many('migration.pattern')
    exclude_pattern_ids = fields.Many2many('migration.pattern')

    model_ids = fields.One2many('migration.model', 'migration_id', 'Models')
    stack_ids = fields.One2many('migration.stack', 'migration_id', 'Stack')
    
    @property
    @api.one
    def connection(self):
        if not self._connection:
            self._connection = odoorpc.ODOO(self.address.split(':')[0], port=self.address.split(':')[1])
            self._connection.login(self.database, self.login, self.password)
        return self._connection

    @api.multi
    def run_cron(self):
        stack = self.env['migration.stack'].search([
            ('state', '=', 'queued')], order='id desc', limit=1)
        stack.import_record()

    @api.multi
    def put_to_stack(self, model, res_id, referenced_to=False, referenced_field=''):
        for migration in self:
            self.env['migration.stack'].create({
                'model_id': model.id,
                'remote_id': res_id,
                'state': 'queued',
            })

    @api.multi
    def execute(self):
        for migration in self:
            for model in migration.model_ids.sorted(key='sequence', reverse=True):
                remote_pool = migration.connection[0].env[model.remote_name or model.name]
                stack_pool = self.env['migration.stack']
                has_results = True
                limit = 200
                offset = 0
                while has_results:
                    ids = remote_pool.search([], limit=200, offset=offset, order='id desc')
                    offset += limit
                    if ids:
                        for id in ids:
                            if not stack_pool.search([
                                    ('model_id','=',model.name),
                                    ('remote_id','=',id),
                                    ('migration_id','=',migration.id)]):
                                migration.put_to_stack(model, id)
                    else:
                        has_results = False

    @api.multi
    def clear_models(self):
        for m in self:
            m.model_ids.unlink()

    @api.one
    def load_data(self):
        domain = []
        for p in self.include_pattern_ids:
            domain.append(('model', 'like', p.name))
        if self.include_pattern_ids:
            domain = ['|'] * (len(domain) - 1) + domain
        domain = [('transient', '=', False)] + domain

        models_to_process = self.env['ir.model'].search(domain).mapped('model')
        for model in models_to_process:
            fields = self.env[model]._fields
            for parent_model, parent_field in self._inherits.iteritems():
                parent = self.env[parent_model]
                fields.update(parent._fields)
            if not self.env['migration.model'].search([
                    ('name', '=', model),
                    ('migration_id', '=', self.id)]):
                remote_model = self.connection[0].env['ir.model'].search([('model', '=', model)])
                if remote_model:
                    remote_model = self.connection[0].env['ir.model'].browse(remote_model[0])
                else:
                    continue
                self.env.cr.execute('SELECT COALESCE(MAX(sequence),0) FROM migration_model WHERE migration_id = %s', (self.id,))
                last_seq = self.env.cr.fetchone()

                fields_to_mig = []
                for f in remote_model.field_id:
                    if f.name in EXCLUDE_FIELDS:
                        continue
                    if f.name in fields:
                        if fields[f.name].compute:
                            continue
                        if fields[f.name].type == 'one2many':
                            continue
                        fields_to_mig.append((0, 0, {
                            'name': f.name,
                            'remote_name': f.name,
                            'ttype': fields[f.name].type,
                            'remote_ttype': f.ttype
                        }))

                self.env['migration.model'].create({
                    'name': model,
                    'remote_name': model,
                    'migration_id': self.id,
                    'sequence': (last_seq and (last_seq[0] + 1)) or 1,
                    'field_ids': fields_to_mig
                })

class MigrationPattern(models.Model):
    _name = 'migration.pattern'

    name = fields.Char('Pattern')


class MigrationModels(models.Model):
    _name = 'migration.model'

    name = fields.Char('Name')
    remote_name = fields.Char('Remote Name')
    sequence = fields.Integer('Sequence')
    migration_id = fields.Many2one('migration.config', 'Migration ID')
    field_ids = fields.One2many('migration.model.fields', 'model_id', 'Fields Mapping')
    completness = fields.Float(string='Completeness', compute="compute_completeness")
    imported = fields.Integer(string='Imported', compute="compute_completeness")
    count = fields.Integer(string='Count', compute="compute_completeness")
    actual_import = fields.Integer(string='Count', compute="compute_completeness")
    no_create = fields.Boolean(string='No create')

    def compute_completeness(self):
        stack_obj = self.env['migration.stack']
        for obj in self:
            model_obj = self.env[obj.name]

            obj.imported = imported = stack_obj.search_count([['model_id', '=', obj.id]])

            local_search_domain = []
            if 'active' in model_obj._fields.keys():
                local_search_domain.append('|')
                local_search_domain.append(['active', '=', True])
                local_search_domain.append(['active', '=', False])

            actual_objs = model_obj.search(local_search_domain)
            actual_imported = stack_obj.search_count([
                ['model_id', '=', obj.id],
                ['res_id', 'in', actual_objs.ids]
            ])

            obj.actual_import = actual_imported
            obj.count = actual_count = len(actual_objs)

            obj.completness = (imported * 1.0 / actual_count if actual_count else 0) * 100

            if (obj.actual_import == obj.count):
                obj.completness = 100

class MigrationField(models.Model):
    _name = 'migration.model.fields'

    model_id = fields.Many2one('migration.model')
    name = fields.Char('Field')
    ttype = fields.Char('Type')
    ident = fields.Boolean('Identifying field', default=False)
    remote_name = fields.Char('Remote Field')
    remote_ttype = fields.Char('Remote Type')
    default_value = fields.Char('Default Value')
    exceptions = fields.Char('Exceptions')
    create_only = fields.Boolean('Create only')
    update_only = fields.Boolean('Update only')


class MigrationStackRef(models.Model):
    _name = 'migration.stack.ref'

    stack_from = fields.Many2one('migration.stack')
    stack_to = fields.Many2one('migration.stack')
    field = fields.Char('Field')

class MigrationStack(models.Model):
    _name = 'migration.stack'

    model_id = fields.Many2one('migration.model')
    model = fields.Char('Model', related='model_id.name')
    remote_model = fields.Char('Remote Model', related='model_id.remote_name')
    migration_id = fields.Many2one('migration.config', related='model_id.migration_id')
    remote_id = fields.Integer('Remote ID')
    res_id = fields.Integer('Local ID')
    state = fields.Selection(STACK_STATE, 'State', default='queued')
    blocked = fields.Boolean('Blocked', default=False)
    ref_ids = fields.One2many('migration.stack.ref', 'stack_from')
    ref_to_ids = fields.One2many('migration.stack.ref', 'stack_to')

    @api.multi
    def find_record_by_external_id(self):
        self.ensure_one()
        stack = self
        # search in ir.model.data
        remote_rec = stack.migration_id.connection[0].env[stack.remote_model].browse(stack.remote_id)
        remote_external_id = stack.migration_id.connection[0].env['ir.model.data'].search([
            ('res_id', '=', stack.remote_id),
            ('model', '=', stack.remote_model)])
        if len(remote_external_id) == 1:
            remote_external_id = stack.migration_id.connection[0].env['ir.model.data'].browse(remote_external_id[0])
        else:
            return False
        if remote_external_id:
            local_external_id = self.env['ir.model.data'].search([
                ('model', '=', stack.model),
                ('name', '=', remote_external_id.name)])
            if len(local_external_id) == 1:
                return self.env[stack.model].browse(local_external_id.res_id)
        return False

    @api.multi
    def find_ident_record(self):
        self.ensure_one()
        stack = self
        ident_fields = stack.model_id.field_ids.filtered(lambda x: x.ident)
        remote_rec = stack.migration_id.connection[0].env[stack.remote_model].browse(stack.remote_id)
        if ident_fields:
            ident_domain = []
            for fi in ident_fields:
                val = getattr(remote_rec, fi.name)
                if fi.exceptions:
                    val = eval(fi.exceptions).get(val, val)
                if fi.ttype == 'many2one':
                    fobj = self.env[stack.model]._fields[fi.name]
                    if fobj.comodel_name in stack.migration_id.model_ids.mapped('name'):
                        rel_model = self.env['migration.model'].search([
                            ('migration_id', '=', stack.migration_id.id),
                            ('name', '=', fobj.comodel_name)])
                        
                        rel_stack = self.env['migration.stack'].search([
                            ('model_id', '=', rel_model.id),
                            ('remote_id', '=', getattr(remote_rec, fi.remote_name))
                        ])

                        if rel_stack and rel_stack.res_id:
                            ident_domain.append((fi.name, '=', rel_stack.res_id))
                        elif rel_stack and rel_stack.state == 'queued':
                            ident_domain.append((fi.name, '=', rel_stack.import_record().id))
                        # elif not rel_stack:
                        #     migration_model = self.env['migration.model'].search([
                        #         ('name', '=', fobj.comodel_name),
                        #         ('migration_id', '=', stack.migration_id.id)
                        #     ])
                        #     rel_stack = migration.put_to_stack(migration_model[0], val,
                        #         stack.id, fi.name)
                        #     ident_domain.append((fi.name, '=', rel_stack.import_record().id))
                        else:
                            return False
                else:
                    ident_domain.append((fi.name, '=', val))
            if ident_domain and 'active' in stack.model_id.field_ids.mapped('name'):
                ident_domain.append('|')
                ident_domain.append(('active', '=', True))
                ident_domain.append(('active', '=', False))
            ident_rec = self.env[stack.model].search(ident_domain)
            if ident_rec:
                return ident_rec
        return False

    @api.multi
    def prepare_vals(self):
        self.ensure_one()
        vals = {}
        remote_rec = self.migration_id.connection[0].env[self.remote_model].browse(self.remote_id)
        for field in self.model_id.field_ids:
            fobj = self.env[self.model]._fields[field.name]
            val = getattr(remote_rec, field.remote_name)
            if fobj.type in ('boolean', 'float', 'integer', 'char', 'text', 'binary', 'selection', 'date', 'datetime') and \
                    type(val) in (bool, float, int, str, unicode):
                if field.exceptions:
                    val = eval(field.exceptions).get(val, val)
                vals.update({field.name: val})

            elif fobj.type == 'many2one' and fobj.comodel_name in self.migration_id.model_ids.mapped('name') and \
                    val and not (fobj.comodel_name == self.model and val.id == remote_rec.id):

                rel_id = self.env['migration.stack'].search([
                    ('remote_id', '=', val.id),
                    ('migration_id', '=', self.migration_id.id),
                    ('model', '=', fobj.comodel_name)
                ])
                if rel_id:
                    if rel_id.state == 'done' and rel_id.res_id:
                        vals.update({
                            field.name: rel_id.res_id
                        })
                    elif rel_id.state == 'queued':
                        if fobj.required:
                            vals.update({field.name: rel_id.import_record().id})
                        else:
                            self.env['migration.stack.ref'].create({
                                'stack_from': self.id,
                                'stack_to': rel_id.id,
                                'field': field.name
                            })
                            vals.update({
                                field.name: False
                            })
                else:
                    migration_model = self.env['migration.model'].search([
                        ('name', '=', fobj.comodel_name),
                        ('migration_id', '=', self.migration_id.id)
                    ])
                    self.migration_id.put_to_stack(migration_model[0], val.id, self.id, field.name)
                    return False
            elif fobj.type == 'many2many' and fobj.comodel_name in self.migration_id.model_ids.mapped('name'):
                val_to_update = []
                for m2m_val in val:
                    rel_id = self.env['migration.stack'].search([
                        ('remote_id', '=', m2m_val.id),
                        ('migration_id', '=', self.migration_id.id),
                        ('model', '=', fobj.comodel_name)
                    ])

                    if rel_id:
                        if rel_id.state == 'done' and rel_id.res_id:
                            val_to_update.append(rel_id.res_id)
                        # else:
                        #     self.env['migration.stack.ref'].create({
                        #         'stack_from': self.id,
                        #         'stack_to': rel_id.id,
                        #         'field': field.name
                        #     })
                vals.update({
                    field.name: [(6, 0, val_to_update)]
                })
        return vals

    @api.one
    def update_refs(self):
        for ref in self.ref_to_ids:
            fobj = self.env[ref.stack_from.model]._fields[ref.field]
            self.env[ref.stack_from.model].browse(ref.stack_from.res_id).write({
                ref.field: self.res_id if fobj.type == 'many2one' else [(4, self.res_id)]
            })
        self.ref_to_ids.unlink()



    @api.multi
    def import_record(self):
        

        for stack in self:
            if hasattr(self.env[stack.model], 'import_record'):
                self.env[stack.model].import_record(stack)
                continue
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
            if relation == 'product.template':
                if not res_id:
                    res_id = self.env[relation].with_context(create_product_product=True).create(vals)
                elif vals:
                    res_id.with_context(create_product_product=True).write(vals)

            else:
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

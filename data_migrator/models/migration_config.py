# -*- coding: utf-8 -*-
import odoorpc
from odoo import api, models, fields

EXCLUDE_FIELDS = ['id', 'create_uid', 'create_date', 'write_uid', 'write_date', '__last_update',]
STACK_STATE = [('queued', 'Queued'), ('done', 'Done'), ('failed', 'Failed')]

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
        # stack.write({'blocked': True})
        # self.env.cr.commit()
        stack.import_record()
        # stack.write({'blocked': False})

    @api.multi
    def put_to_stack(self, model, res_id):
        for migration in self:
            self.env['migration.stack'].create({
                'migration_id': migration.id,
                'model': model,
                'remote_id': res_id,
                'state': 'queued'
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
                                    ('model','=',model.name),
                                    ('remote_id','=',id),
                                    ('migration_id','=',migration.id)]):
                                migration.put_to_stack(model.name, id)
                    else:
                        has_results = False

    @api.multi
    def clear_models(self):
        for m in self:
            m.model_ids.unlink()

    @api.one
    def load_data(self):
        # self.ensure_one()

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

class MigrationField(models.Model):
    _name = 'migration.model.fields'

    model_id = fields.Many2one('migration.model')
    name = fields.Char('Field')
    ttype = fields.Char('Type')
    ident = fields.Boolean('Identifying field', default=False)
    remote_name = fields.Char('Remote Field')
    remote_ttype = fields.Char('Remote Type')
    # default_value = fields.Char('Default Value')


class MigrationStack(models.Model):
    _name = 'migration.stack'

    model = fields.Char('Model')
    res_id = fields.Integer('ID')
    migration_id = fields.Many2one('migration.config', 'Migration')
    remote_id = fields.Integer('Remote ID')
    state = fields.Selection(STACK_STATE, 'State', default='queued')
    blocked = fields.Boolean('Blocked', default=False)


    # @api.one
    # def prepare_vals(self):

    
    
    @api.multi
    def import_record(self):
        def map_existing_record(migration, mig_model, relation, obj):
            ident_fields = mig_model.field_ids.filtered(lambda x: x.ident)
            if ident_fields:
                ident_domain = []
                for fi in ident_fields:
                    if fi.ttype in ('many2one', 'many2many'):
                        fobj = self.env[relation]._fields[fi.name]
                        if fobj.comodel_name in migration.model_ids.mapped('name'):
                            rel_stack = self.env['migration.stack'].search([
                                ('model', '=', fobj.comodel_name),
                                ('migration_id', '=', migration.id),
                                ('remote_id', '=', getattr(obj, fi.remote_name))
                            ])
                            if rel_stack and rel_stack.res_id:
                                ident_domain.append((fi.name, '=', rel_stack.res_id))
                            elif rel_stack and rel_stack.state == 'queued':
                                rel_stack.import_record()
                                return False
                            elif not rel_stack:
                                migration.put_to_stack(fobj.comodel_name, getattr(obj, fi.remote_name))
                                return False
                    else:
                        ident_domain.append((fi.name, '=', getattr(obj, fi.remote_name)))
                if 'active' in mig_model.field_ids.mapped('name'):
                    ident_domain.append('|')
                    ident_domain.append(('active', '=', True))
                    ident_domain.append(('active', '=', False))
                ident_rec = self.env[relation].search(ident_domain)
                if ident_rec:
                    return ident_rec
            return False

        def prepare_vals(migration, mig_model, relation, obj):
            vals = {}
            for mig_field in mig_model.field_ids:
                fobj = self.env[relation]._fields[mig_field.name]
                try:
                    val = getattr(obj, mig_field.remote_name)
                except:
                    continue
                if fobj.type in ('boolean', 'float', 'integer', 'char', 'text', 'binary', 'selection') and \
                        type(val) in (bool, float, int, str, unicode):
                    val = EXCEPTIONS.get(val, val)
                    vals.update({mig_field.name: val})
                elif fobj.type == 'many2one' and fobj.comodel_name in migration.model_ids.mapped('name') and \
                        val and not (fobj.comodel_name == relation and val.id == obj.id):

                    rel_id = self.env['migration.stack'].search([
                        ('remote_id', '=', val.id),
                        ('migration_id', '=', migration.id),
                        ('model', '=', fobj.comodel_name)
                    ])
                    if rel_id:
                        if rel_id.state == 'done' and rel_id.res_id:
                            vals.update({
                                mig_field.name: rel_id.res_id
                            })
                        elif rel_id.state == 'queued':
                            rel_id.import_record()
                            return False
                    else:
                        migration.put_to_stack(fobj.comodel_name, val.id)
                        return False
                elif fobj.type == 'many2many' and fobj.comodel_name in migration.model_ids.mapped('name'):
                    val_to_update = []
                    for m2m_val in val:
                        rel_id = self.env['migration.stack'].search([
                            ('remote_id', '=', val.id),
                            ('migration_id', '=', migration.id),
                            ('model', '=', fobj.comodel_name)
                        ])

                        if rel_id:
                            if rel_id.state == 'done' and rel_id.res_id:
                                val_to_update.append(rel_id.res_id)
                            elif rel_id.state == 'queued':
                                rel_id.import_record()
                                return False
                        else:
                            migration.put_to_stack(fobj.comodel_name, val.id)
                            return False
                    vals.update({
                        mig_field.name: val_to_update
                    })
            return vals

        for stack in self:
            if hasattr(self.env[stack.model], 'import_record'):
                self.env[stack.model].import_record(stack)
                continue
            # stack.write({'blocked': True})
            # self.env.cr.commit()
            
            migration = stack.migration_id
            relation = stack.model
            obj = migration.connection[0].env[relation].browse(stack.remote_id)

            mig_model = self.env['migration.model'].search([
                ('name','=', relation),
                ('migration_id', '=', migration.id)
            ])

            res_id = map_existing_record(migration, mig_model, relation, obj)
            
            vals = prepare_vals(migration, mig_model, relation, obj)
            if not vals:
                # stack.write({ 'blocked': False})
                # self.env.cr.commit()
                stack.write({'state': 'done'})
                continue
                    
            if relation == 'product.template':
                if not res_id:
                    res_id = self.env[relation].with_context(create_product_product=True).create(vals)
                else:
                    res_id.with_context(create_product_product=True).write(vals)

            else:
                if res_id:
                    res_id.write(vals)
                else:
                    res_id = self.env[relation].create(vals)
            for lang in self.env['res.lang'].search([('code', '!=', self.env.context['lang'])]):
                vals_to_translate = {}
                translated_obj = obj.with_context(lang=lang.code)
                for f in mig_model.field_ids.filtered(lambda x: x.ttype in ('char', 'text')):
                    vals_to_translate.update({
                        f.name: getattr(translated_obj, f.name)
                    })
                res_id.with_context(lang=lang.code).write(vals_to_translate)
            if res_id:
                if self.env[relation]:
                    for fn, fo in self.env[relation]._inherits.iteritems():
                        if not self.env['migration.stack'].search([('model', '=', fo.relation),
                                ('remote_id','=', getattr(obj, fn).id),
                                ('migration_id', '=', migration.id)]):
                            self.env['migration.stack'].create({
                                'migration_id': migration.id,
                                'model': fo.relation,
                                'remote_id': getattr(obj, fn).id,
                                'res_id', '=', getattr(res_id, fn),
                                'state': 'done'
                                })
            stack.write({'state': 'done', 'res_id': res_id.id, 'blocked': False})
            # self.env.cr.commit()
            return res_id.id

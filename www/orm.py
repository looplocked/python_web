#!/usr/bin/env python3
# -*- coding: utf-8 -*-


import asyncio, logging

import aiomysql

__author__ = 'Frank Wang'


logging.basicConfig(level=logging.INFO)


def log(sql, args=()):    # sql是一种什么对象？
    logging.info('SQL: %s' % sql)

# 创建连接池，每个http请求都可以从连接池中直接获取数据库连接。使用连接池的好处是不必频繁地打开和关闭数据库连接，而是能复用就尽量复用
async def create_pool(loop, **kw):
    logging.info('create database connection pool...')    # 打印日志
    global __pool
    __pool  = await aiomysql.create_pool(    # create_pool(minsize=1, maxsize=10, loop=None, **kwargs)  A coroutine that create a pool of connection to MySQL database.
        host=kw.get('host', 'localhost'),    # dict有get方法, key=host, default=localhost
        port=kw.get('port', 3306),        #
        user=kw['user'],
        password=kw['password'],
        db=kw['db'],
        charset=kw.get('charset','utf8'),
        autocommit=kw.get('maxsize',10),
        minsize=kw.get('minsize',1),
        loop=loop
    )

# Cursors allow Python code to execute MySQL command in a database session. They are bound to the connection for the
# entire lifetime and all the commands are executed in the context of the database wrapped by the connection.
# cursor.execute(query, args=None) Coroutine, executes the given operation substituting any markers with the given parameters.
# For example, getting all rows where id is 5: yield from cursor.execute("SELECT * FROM t1 WHERE id=%s", (5,))
# Return number of rows that has been produced of affected.
# DictCursor A cursor which returns results as a dictionary. All methods and arguments same as Cursor.
async def select(sql, args, size=None):    #sql是需要执行的select语句，args需要替换的参数, size是选择的行数
    log(sql, args)
    global __pool
    async with __pool.get() as conn:    # 为什么不是acquire()
        async with conn.cursor(aiomysql.DictCursor) as cur:    # conn.cursor() is a coroutine that creates a new cursor using the connection. return a cursor instance.
            await cur.execute(sql.replace('?', '%s'), args or ())    #SQL语句占位符是?，而MySQL语句占位符是%s，select()函数自动在内部替换。
            if size:
                rs = await cur.fetchmany(size)    # 如果传入size 参数，就通过fetchmany()获取最多指定数量的记录 return list of fetched rows
            else:
                rs = await cur.fetchall()    # return all rows
        logging.info('rows returned: %s' % len(rs))
        return rs

# execute()和select()不同的是，cursor对象不返回结果集，而通过rowcount返回结果数
async def execute(sql, args, autocommit=True):
    log(sql.replace('?', '%s')+str(args))
    async with __pool.get() as conn:
        if not autocommit:
            await conn.begin()
        try:
            async with conn.cursor(aiomysql.DictCursor) as cur:
                await cur.execute(sql.replace('?', '%s'), args)
                affected = cur.rowcount    # Returns the number of rows that has been produced of affected.
            if not autocommit:    # 为什么每执行一次都要检测autocommit?
                await conn.commit()
        except BaseException as e:
            if not autocommit:
                await conn.rollback()    # 如果执行失败，则回滚
            raise    # 收集异常，但不处理
        finally:
            conn.close()
        return affected


def create_args_string(num):
    L = []
    for n in range(num):
        L.append('?')
    return ', '.join(L)


# 创建MySQL中集中常用的数据类型
class Field(object):

    def __init__(self, name, column_type, primary_key, default):
        self.name = name
        self.column_type = column_type
        self.primary_key = primary_key
        self.default = default

    def __str__(self):
        return '<%s, %s: %s>' % (self.__class__.__name__, self.column_type, self.name)    # 返回对于自身的描述


class StringField(Field):

    def __init__(self, name=None, primary_key=None, default=None, ddl='varchar(100)'):
        super().__init__(name, ddl, primary_key, default)


class BooleanField(Field):

    def __init__(self, name=None, default=False):
        super().__init__(name, 'boolean', False, default)


class IntegerField(Field):

    def __init__(self, name=None, primary_key=False, default=0):
        super().__init__(name, 'bigint', primary_key, default)


class FloatField(Field):

    def __init__(self, name=None, primary_key=False, default=0.0):
        super().__init__(name, 'real', primary_key, default)


class TextField(Field):

    def __init__(self, name=None, default=None):
        super().__init__(name,'text', False, default)


# 元类在此处的作用是修改类属性，还可以用来修改类方法，还可用来添加类属性和类方法
# 元类在此处的作用是添加属性和删除所有Field属性，否则实例的属性会遮盖类的同名属性，即将所有Field属性移至mappings中
class ModelMetaclass(type):    # ModelMetaclass是继承了type 的一个元类，所以和type是平级的

    def __new__(cls, name, bases, attrs):
        # 排除Model类本身，为什么要排除Model类本身，Model类除了用来派生，还有其他作用吗？
        if name=='Model':
            return type.__new__(cls, name, bases, attrs)    # 如果类名为Model, 则用type实例化，下文中Model在此创建，attrs是一个dict
        tableName = attrs.get('__table__', None) or name    # 表名有类中的__table__定义，如果没有定义，则和类名相同
        logging.info('found model: %s (table: %s)' % (name, tableName))
        mappings = dict()
        fields = []
        primaryKey = None
        for k, v in attrs.items():
            if isinstance(v, Field):
                logging.info('   found mapping: %s ==> %s' % (k, v))
                mappings[k] = v
                if v.primary_key:
                    # 找到主键
                    if primaryKey:    #如果找到两个主键
                        raise RuntimeError('Duplicate primary key for field: %s' % k)
                    primaryKey = k
                else:
                    fields.append(k)
        if not primaryKey:
            raise RuntimeError('Primary key not found.')
        for k in mappings.keys():
            attrs.pop(k)
        escaped_fields = list(map(lambda f: ' %s ' % f, fields))    # 将fields转化为string
        attrs['__mappings__'] = mappings    # 保存属性和列的映射关系，属性就是k,列就是Field类，注意这里mappings是一个dict,这里是保存了所有的映射关系
        attrs['__table__'] = tableName
        attrs['__primary_key__'] = primaryKey    # 主键属性名
        attrs['__fields__'] = fields   # 除主键外的属性名
        attrs['__select__'] = 'select `%s` , %s from `%s`' % (primaryKey, ', '.join(escaped_fields), tableName)
        attrs['__insert__'] = 'insert into `%s` (%s, `%s`) values (%s)' % (tableName, ', '.join(escaped_fields), primaryKey, create_args_string(len(escaped_fields) + 1))
        attrs['__update__'] = 'update `%s` set %s where `%s`=?' % (tableName, ', '.join(map(lambda f: '`%s` = ?' % (mappings.get(f).name or f), fields)), primaryKey)
        attrs['__delete__'] = 'delete from `%s` where `%s`=?' % (tableName, primaryKey)
        return type.__new__(cls, name, bases, attrs)    # 这是元类的实例化是通过复写type的__new__()方法实现的，name在下文中就是指Model，bases是指当通过Model形成派生类时，Model就是bases


# 注意Model类本身并没有修改attrs属性，但是由Model类派生的子类却可以通过metaclass实现attrs属性。
# 换句话说，Model仅仅是一个过渡的作用，只是为其子类提供一些共有的方法，本身并不会实例化。
# Model类的类方法和实例方法都可以被子类继承
class Model(dict, metaclass=ModelMetaclass):

    def __init__(self, **kw):
        super(Model, self).__init__(**kw)

    def __getattr__(self, key):
        try:
            return self[key]
        except KeyError:
            raise AttributeError(r"'Model' object has no attribute '%s'" % key)

    def __setattr__(self, key, value):
        self[key] = value

    def getValue(self, key):
        return getattr(self, key, None)

    def getValueOrDefault(self, key):
        value = getattr(self, key, None)
        if value is None:
            field = self.__mappings__[key]     # 如果实例属性中未找到该属性，则到类属性中去找默认值，由于类属性已移至__mappings__中，所有有了以下代码
            if field.default is not None:
                value = field.default() if callable(field.default) else field.default    # primary_key 的值通过default获得
                logging.debug('using default value for %s: %s' % (key, str(value)))
                setattr(self, key, value)
        return value

    # 根据where条件查找
    @classmethod
    async def findAll(cls, where=None, args=None, **kw):
        ' find objects by where clause. '
        sql = [cls.__select__]    # 获取sql查询语句
        if where:
            sql.append('where')    # 获取where条件
            sql.append(where)
        if args is None:
            args = []
        orderBy = kw.get('orderBy', None)    # 获取orderby条件
        if orderBy:
            sql.append('order by')
            sql.append(orderBy)
        limit = kw.get('limit', None)    # 获取limit条件
        if limit is not None:
            sql.append('limit')
            if isinstance(limit, int):
                sql.append('?')
                args.append(limit)
            elif isinstance(limit,tuple) and len(limit) == 2:
                sql.append('?, ?')
                args.extend(limit)
            else:
                raise ValueError('Invalid limit value: %s' % str(limit))
        rs = await select(' '.join(sql), args)    # 调用select函数查找
        return [cls(**r) for r in rs]    # 返回list of records, 由于findAll是类方法，所以使用model类对record进行construct

    @classmethod
    async def findNumber(cls, selectField, where=None, args=None):
        ' find number by select and where. '
        sql = ['select %s _num_ from `%s`' % (selectField, cls.__table__)]
        if where:
            sql.append('where')    # 获取where条件
            sql.append(where)
        rs = await select(' '.join(sql), args, 1)
        if len(rs) == 0:
            return None
        return rs[0]['_num_']    # 返回找到记录的行数

    # 根据主键查找
    @classmethod
    async def find(cls, pk):
        ' find object by primary key. '
        rs = await select('%s where `%s`=?' % (cls.__select__, cls.__primary_key__), [pk], 1)
        if len(rs) == 0:
            return None
        return cls(**rs[0])    # 返回找到的第一条记录

    # 插入一条记录
    async def save(self):
        args = list(map(self.getValueOrDefault, self.__fields__))    # 将除主键以外的属性组成List
        args.append(self.getValueOrDefault(self.__primary_key__))    # 将主键属性也添加进去, 此处为什么没有__primary_key__=id?
        logging.info('The problem is '+str(args))
        rows = await execute(self.__insert__, args)
        if rows != 1:
            logging.warn('failed to insert record: affected rows: %s' % rows)

    # 更新记录，更新数据是指对表中存在的记录进行修改
    async def update(self):
        args = list(map(self.getValue, self.__fields__))
        args.append(self.getValue(self.__primary_key__))
        rows = await execute(self.__update__, args)
        if rows != 1:
            logging.warn('failed to update by primary key: affected rows: %s' % rows)

    async def remove(self):
        args = [self.getValueOrDefault(self.__primary_key__)]    # 必须在一个loop里面save和remove
        rows = await execute(self.__delete__, args)
        if rows != 1:
            logging.warn('failed to update by primary key: affected rows: %s' % rows)

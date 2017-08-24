#!/usr/bin/env python3
# -*- coding: utf-8 -*-


import os
import functools
import inspect
from aiohttp import web
from urllib import parse
import logging
import asyncio
from apis import APIError

__author__ = 'Frank Wang'


# inspect.signature return a signature object. parameters method returns an ordered mapping of parameters' names to the
# corresponding Parameter objects
def get_params(fn):
        return inspect.signature(fn).parameters


# use inspect module to obtain the relationship between URL handle function and
# arguments of requests
# 找出函数的无默认值的命名关键字参数组成tuple并返回
def get_required_kw_args(fn):
    args = []
    params = get_params(fn)
    # use inspect to check the function, its parameters would be stored in
    # OrderedDict
    for name, param in params.items():    # Parameter继承了dict?
        if str(param.kind) == 'KEYWORD_ONLY'\
                and param.default == inspect.Parameter.empty:    # empty: A special class-level marker to specify absence of default values and annotations.
            # for function, if there is one `*,` `args`,
            # in parameters ,parameters
            # after the `*` would all be keyword only
            # inspect.Parameter.empty is one class, if the param have no default
            # value, param.default would return the class.
            args.append(name)
    return tuple(args)


# 返回函数的所有命名关键字参数
def get_named_kw_args(fn):
    args = []
    params = inspect.signature(fn).parameters
    for name, param in params.items():
        if param.kind == inspect.Parameter.KEYWORD_ONLY:
            args.append(name)
    return tuple(args)


# 判断函数是否存在命名关键字参数
def has_named_kw_arg(fn):
    # tell whether there is one keyword paramters
    params = get_params(fn)
    for name, param in params.items():
        if str(param.kind) == 'KEYWORD_ONLY':
            return True


# 判断是否存在可变关键字参数
def has_var_kw_arg(fn):
    # tell whether there is var_keyword
    # var_keyword means **kwargs (a dict of keyword argument)
    params = get_params(fn)
    for name, param in params.items():
        if str(param.kind) == 'VAR_KEYWORD':
            return True


def has_request_arg(fn):
    # tell whether there is one parameter named as `request` and is the last
    # named parameter
    sig = inspect.signature(fn)
    params = sig.parameters
    found = False
    logging.info(params)
    for name, param in params.items():
        if name == 'request':
            found = True
            continue
            # end this loop and goes to the next loop, which means would check
            # the following name and param in params
        if (found and str(param.kind) not in
                ['VAR_POSITIONAL', 'KEYWORD_ONLY', 'VAR_KEYWORD']):
            raise ValueError(
                'request parameter must be the last named\
                parameter in function: {0}{1}'.format(fn.__name__, str(sig)))
    return found


def get(path):
    # define decorator @get('/path')
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kw):
            return func(*args, **kw)
        wrapper.__method__ = 'GET'    # 在get被用作装饰器时，wrapper就是被装饰函数?
        wrapper.__route__ = path
        return wrapper
    return decorator


def post(path):
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kw):
            return func(*args, **kw)
        wrapper.__method__ = 'POST'
        wrapper.__route__ = path
        return wrapper
    return decorator


# RequestHandler的目的就是从URL函数中分析其需要接受的参数，从request中获取必要的参数，调用URL函数，
# 然后把结果转换为web.Response对象，这样，就完全符合aiohttp框架的要求
class RequestHandler(object):

    def __init__(self, app, fn):
        self._app = app    # app是web.Application?
        self._func = fn    # fn是URL处理函数？
        self._has_request_arg = has_request_arg(fn)
        self._has_var_kw_arg = has_var_kw_arg(fn)
        self._has_named_kw_arg = has_named_kw_arg(fn)
        self._named_kw_arg = get_named_kw_args(fn)
        self._get_required_kw_args = get_required_kw_args(fn)

    async def __call__(self, request):
        # request is one object or class of aiohttp.web, it has these functions
        # request would be passed in add_route()
        kw = None
        logging.info(str(request))
        if(self._has_var_kw_arg or self._has_named_kw_arg
               or self. _get_required_kw_args):    # 存在可变关键字参数，或者命名关键字参数或者无默认值的命名关键字参数
            if request.method == 'POST':
                if not request.content_type:
                    # tell  whether there is content-type, normally content_type
                    # could include value of text/html, charset: utf-8
                    return web.HTTPBadRequest(text='Missing content-type.')
                ct = request.content_type.lower()
                if ct.startswith('application/json'):
                    # application/json as response head tell server that the
                    # information body is JSON object
                    params = await request.json()    # coroutine. Read request body decoded as json.
                    # read request body decode as json
                    if not isinstance(params, dict):    # json should be a dict.
                        return web.HTTPBadRequest(
                            text='JSON body must be dict object')
                    kw = params
                elif (ct.startswith('application/x-www-form-urlencoded') or
                    ct.startswith('multipart/form-data')):
                    # `application/x-www-form-urlencoded` - most normal POST
                    # method, if we do not set <form> enctype property, it would
                    # be sent in this way
                    # WTF is enctype?? 编码方式
                    # `multipart/form-data` - if we set `entype`, it would be
                    # sent in this way
                    params = await request.post()    # Returns MultiDictProxy instance filled with parsed data.
                    kw = dict(**params)
                else:
                    return web.HTTPBadRequest(
                        text='Unsupported content-type {0}'.format(
                            request.content_type))
            if request.method == 'GET':
                qs = request.query_string    # query_string: the query string in the URL
                if qs:
                    kw = dict()
                    for k, v in parse.parse_qs(qs, True).items():
                        # parse.parse_qs parse a query string argument (data
                        # type of application/x-www-form-urlencoded), data are
                        # returned in form of dict, the dict keys are the unique
                        # query variable names and the values are lists of
                        # values for each name
                        kw[k] = v[0]    # kw直接从k开始？
        if kw is None:    # 若不满足以上条件
            kw = dict(**request.match_info)
            # match_info would return one dict and all keyword_only parameters
            # obtained from request would be stored in this dict
        else:
            if not self._has_var_kw_arg and self._named_kw_arg:    # 若无可变关键字参数但有命名关键字参数
                copy = dict()
                for name in self._named_kw_arg:
                    # remove all the unnamed kw
                    if name in kw:
                        copy[name] = kw[name]
                kw = copy
            for k, v in request.match_info.items():
                if k in kw:
                    logging.warning('Duplicate arg name in named'
                                    'arg and kw args: {0}'.format(k))
                kw[k] = v
        logging.info('has request? {0}'.format(str(self._has_request_arg)))
        if self._has_request_arg:    # 若有request参数且为最后一个参数
            kw['request'] = request
        if self._get_required_kw_args:    # 若存在无默认值的命名关键字参数
            for name in self._get_required_kw_args:
                if name not in kw:
                    return web.HTTPBadRequest(text='Missing argument {0}'.format(name))
        logging.info('call with args: {0}'.format(str(kw)))
        try:
            r = await self._func(**kw)    # 调用URL处理函数，对解析出来的request进行处理
            return r
        except APIError as e:
            return dict(error=e.error, data=e.data, message=e.message)


# 添加静态文件夹，静态文件夹中存放css和javascript文件
def add_static(app):
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static')
    app.router.add_static('/static/', path)
    # app is one object within aiohttp module
    logging.info('add static {0} => {1}'.format('/static/', path))


def add_route(app, fn):
    # one simple URL handler function
    logging.info('start add route')
    method = getattr(fn, '__method__', None)
    path = getattr(fn, '__route__', None)
    if path is None or method is None:
        raise ValueError('@get or @post not defined in {0}'.format(str(fn)))
    if not asyncio.iscoroutine(fn) and not inspect.isgeneratorfunction(fn):
        fn = asyncio.coroutine(fn)    # 检查fn是否为协程或生成器，如果不是，转化为生成器
    logging.info('add route {0} {1} => {2} ({3})'.format(
        method, path, fn.__name__,
        ','.join(inspect.signature(fn).parameters.keys())))
    app.router.add_route(method, path, RequestHandler(app, fn))    # 核心部分，将URL处理函数注册到app中真正URL处理函数并不是fn，而是实例化之后的RequestHandler


# 批量注册URL处理函数，从模块导入
def add_routes(app, module_name):
    n = module_name.rfind('.')
    # rfind would return where is the character last appear, if it did not
    # appear, it would return -1
    if n == (-1):
        mod = __import__(module_name, globals(), locals())
    else:
        name = module_name
        mod = getattr(__import__(module_name[:n], globals(), locals(),
                                 [name], 0), name)
        # ergodic the imported module to get function, because we used decorator
        # @post and @get, there would be attribute `__method__` and `__route__`
        # assume we the module name is `aaa.bbb`, `bbb` would be function within
        # the module `aaa`, we only need to import the module `aaa`
    for attr in dir(mod):    # 读取模块的每一个属性
        # dir() return attribute of module
        if attr.startswith('_'):
            continue
        fn = getattr(mod, attr)    # 获取属性值
        if callable(fn):    # 如果属性值可调用
            method = getattr(fn, '__method__', None)
            path = getattr(fn, '__route__', None)
            if method and path:
                add_route(app, fn)

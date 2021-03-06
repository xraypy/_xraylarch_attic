#!/usr/bin/env python
"""
  Larch show() function
"""
import sys
import types
import numpy

def _get(sym=None, _larch=None, **kws):
    """get object from symbol table from symbol name"""
    if _larch is None:
        raise Warning("cannot show group -- larch broken?")
    if sym is None:
        sym = '_main'
    group = None
    symtable = _larch.symtable
    if symtable.isgroup(sym):
        group = sym
    elif isinstance(sym, types.ModuleType):
        group = sym
    elif isinstance(sym, (str, unicode)):
        group = symtable._lookup(sym, create=False)

    return group


def _show(sym=None, _larch=None, **kws):
    """display group members"""
    if _larch is None:
        raise Warning("cannot show group -- larch broken?")
    if sym is None:
        sym = '_main'
    group = None
    symtable = _larch.symtable
    title = sym
    if symtable.isgroup(sym):
        group = sym
        title = repr(sym)[1:-1]
    elif isinstance(sym, types.ModuleType):
        group = sym
        title = sym.__name__
    elif isinstance(sym, (str, unicode)):
        group = symtable._lookup(sym, create=False)

    if group is None:
        _larch.writer.write("%s\n" % repr(sym))
        return
    if title.startswith(symtable.top_group):
        title = title[6:]

    if group == symtable:
        title = 'SymbolTable _main'

    members = dir(group)
    out = ['== %s: %i symbols ==' % (title, len(members))]
    for item in members:
        obj = getattr(group, item)
        dval = None
        if isinstance(obj, numpy.ndarray):
            if len(obj) > 10 or len(obj.shape)>1:
                dval = "array<shape=%s, type=%s>" % (repr(obj.shape),
                                                         repr(obj.dtype))
        if dval is None:
            dval = repr(obj)
        out.append('  %s: %s' % (item, dval))
#         if not (item.startswith('_Group__') or
#                 item == '__name__' or item == '_larch' or
#                 item.startswith('_SymbolTable__')):

    _larch.writer.write("%s\n" % '\n'.join(out))

def registerLarchPlugin():
    return ('_builtin', {'show': _show, 'get': _get})

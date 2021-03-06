'''
Helper classes for larch interpreter
'''

import ast 
import sys, os
import traceback
import inspect
from .utils import Closure
from .symboltable import Group

class LarchExceptionHolder:
    "basic exception handler"
    def __init__(self, node, msg='', fname='<stdin>',
                 func=None, expr=None, exc=None, lineno=0):
        self.node = node
        self.fname  = fname
        self.func = func
        self.expr = expr
        self.msg  = msg
        self.exc  = exc
        self.lineno = lineno
        self.exc_info = sys.exc_info()

        if self.exc_info[0] is not None:
            self.exc = self.exc_info[0]
        if self.msg in ('', None) and self.exc_info[1] is not None:
            self.msg = self.exc_info[1]

    def get_error(self):
        "retrieve error data"
        col_offset = -1
        e_type, e_val, e_tb = self.exc_info
        if self.node is not None:
            try:
                col_offset = self.node.col_offset
            except AttributeError:
                pass

        # print(" GET ERROR ", self.exc, self.msg, self.expr,
        #       self.fname, self.func, self.lineno)
        try:
            exc_name = self.exc.__name__
        except AttributeError:
            exc_name = str(self.exc)
        if exc_name in (None, 'None'):
            exc_name = 'UnknownError'

        out = []
        call_expr = None
        fname = self.fname
        fline = None
        if fname != '<stdin>' or self.lineno > 0:
            fline = 'file %s, line %i' % (fname, self.lineno)

        if self.func is not None:
            func = self.func
            fname = self.fname 

            if isinstance(func, Closure):
                func = func.func
                fname = inspect.getmodule(func).__file__                
            if fname is None:
                try:
                    fname = inspect.getmodule(func).__file__
                except AttributeError:
                    fname = 'unknown'
            if fname.endswith('.pyc'):
                fname = fname[:-1]
            found = False
            for tb in traceback.extract_tb(self.exc_info[2]):
                found = found or tb[0].startswith(fname)
                if found:
                    u = 'File "%s", line %i, in %s\n    %s' % tb
                    words = u.split('\n')
                    fline = words[0]
                    call_expr = self.expr
                    self.expr = words[1]
                    # 'File "%s", line %i, in %s\n    %s' % tb)
            if not found and isinstance(self.func, Procedure):
                pname = self.func.name
                fline = "%s, in %s" % (fline, pname)

        if fline is not None:
            out.append(fline)
            
        tline = exc_name
        if self.msg not in ('',  None):
            tline = "%s: %s" % (exc_name, str(self.msg))
        out.append(tline)

        if call_expr is None and (self.expr == '<>' or
                                  fname not in (None, '', '<stdin>')):
            # denotes non-saved expression -- go fetch from file!
            # print 'Trying to get non-saved expr ', self.fname
            try:
                if fname is not None and os.path.exists(fname):
                    ftmp = open(fname, 'r')
                    _expr = ftmp.readlines()[self.lineno-1][:-1]
                    call_expr = self.expr
                    self.expr = _expr
                    ftmp.close()
            except (IOError, TypeError):
                pass
        if '\n' in self.expr:
            out.append("\n%s" % self.expr)
        else:
            out.append("    %s" % self.expr)
        if col_offset > 0:
            if '\n' in self.expr:
                out.append("%s^^^" % ((col_offset)*' '))
            else:
                out.append("    %s^^^" % ((col_offset)*' '))
        if call_expr is not None:
            out.append('  %s' % call_expr)
        return (exc_name, '\n'.join(out))

    def xget_error(self):
        "retrieve error data"
        node = self.node
        node_lineno = 1
        node_col_offset = 0
        # print ("EXTENDED GET ERROR ", self.exc, node, self.exc_info)
        e_type, e_val, e_tb = self.exc_info
        if node is not None:
            try:
                node_lineno = node.lineno
                node_col_offset = self.node.col_offset
            except:
                pass

        lineno = self.lineno + node_lineno
        if isinstance(e_val, SyntaxError):
            exc_text = 'SyntaxError'
        elif isinstance(e_val, (str, unicode)):
            exc_text = e_val
        else:
            exc_text = repr(e_val)

        if exc_text in (None, 'None'):
            try:
                exc_text = "%s: %s" % (e_val.__class__.__name__, e_val.args[0])
            except:
                exc_text = e_val
        elif exc_text.endswith(',)'):
            exc_text = "%s)" % exc_text[:-2]

        if exc_text in (None, 'None'):
            exc_text = ''
        expr = self.expr
        if expr == '<>': # denotes non-saved expression -- go fetch from file!
            try:
                ftmp = open(self.fname, 'r')
                expr = ftmp.readlines()[lineno-1][:-1]
                ftmp.close()
            except (IOError, TypeError):
                pass

        out = []
        if self.msg not in (None, 'Runtime Error', 'Syntax Error') and len(self.msg)>0:
            out = [self.msg]
        if self.func is not None:
            func = self.func
            if isinstance(func, Closure): func = func.func
            try:
                fname = inspect.getmodule(func).__file__
            except AttributeError:
                fname = 'unknown'

            if fname.endswith('.pyc'): fname = fname[:-1]
            found = False
            for tb in traceback.extract_tb(e_tb):
                found = found or tb[0].startswith(fname)
                if found:
                    out.append('  File "%s", line %i, in %s\n    %s' % tb)

        if len(exc_text) > 0:
            out.append(exc_text)
        else:
            if e_type is not None and e_val is not None:
                out.append("%s: %s" % (e_type, e_val))
        if (self.fname == '<stdin>' and self.lineno <= 0):
            out.append("<stdin>")
        else:
            out.append("%s, line number %i" % (self.fname, 1+self.lineno))

        if expr is not None and len(expr)>0:
            out.append("    %s" % expr)
        if node_col_offset > 0:
            out.append("    %s^^^" % ((node_col_offset)*' '))
        return '\n'.join(out)

class Procedure(object):
    """larch procedure:  function """
    def __init__(self, name, _larch=None, doc=None,
                 fname='<stdin>', lineno=0,
                 body=None, args=None, kwargs=None,
                 vararg=None, varkws=None):
        self.name     = name
        self._larch    = _larch
        self.modgroup = _larch.symtable._sys.moduleGroup
        self.body     = body
        self.argnames = args
        self.kwargs   = kwargs
        self.vararg   = vararg
        self.varkws   = varkws
        self.__doc__  = doc
        self.lineno   = lineno
        self.__file__ = fname

    def __repr__(self):
        sig = ""
        if len(self.argnames) > 0:
            sig = "%s%s" % (sig, ', '.join(self.argnames))
        if self.vararg is not None:
            sig = "%s, *%s" % (sig, self.vararg)
        if len(self.kwargs) > 0:
            if len(sig) > 0:
                sig = "%s, " % sig
            _kw = ["%s=%s" % (k, v) for k, v in self.kwargs]
            sig = "%s%s" % (sig, ', '.join(_kw))

            if self.varkws is not None:
                sig = "%s, **%s" % (sig, self.varkws)
        sig = "<Procedure %s(%s), file=%s>" % (self.name, sig, self.__file__)
        if self.__doc__ is not None:
            sig = "%s\n  %s" % (sig, self.__doc__)
        return sig

    def raise_exc(self, **kws):
        ekws = dict(lineno=self.lineno, func=self, fname=self.__file__)
        ekws.update(kws)
        # print 'PROC  RAISE EXCEPTION " ', ekws
        self._larch.raise_exception(None,  **ekws)

    def __call__(self, *args, **kwargs):
        # msg = 'Cannot run Procedure %s' % self.name
        lgroup  = Group()
        args    = list(args)
        n_args  = len(args)
        n_names = len(self.argnames)
        n_kws   = len(kwargs)

        # may need to move kwargs to args if names align!
        if (n_args < n_names) and n_kws > 0:
            for name in self.argnames[n_args:]:
                if name in kwargs:
                    args.append(kwargs.pop(name))
            n_args = len(args)
            n_names = len(self.argnames)
            n_kws = len(kwargs)

        if len(self.argnames) > 0 and kwargs is not None:
            msg = "%s() got multiple values for keyword argument '%s'"
            for targ in self.argnames:
                if targ in kwargs:
                    self.raise_exc(exc=TypeError,
                                   msg=msg % (targ, self.name))

       
        if n_args != n_names:
            msg = None
            if n_args < n_names:
                msg = 'not enough arguments for %s() expected %i, got %i' 
                msg = msg % (self.name, n_names, n_args)
                # print '\n >>> raise exc ', msg
                self.raise_exc(exc=TypeError, msg=msg)

        for argname in self.argnames:
            setattr(lgroup, argname, args.pop(0))

        try:
            if self.vararg is not None:
                setattr(lgroup, self.vararg, tuple(args))

            for key, val in self.kwargs:
                if key in kwargs:
                    val = kwargs.pop(key)
                setattr(lgroup, key, val)

            if self.varkws is not None:
                setattr(lgroup, self.varkws, kwargs)
            elif len(kwargs) > 0:
                msg = 'extra keyword arguments for procedure %s (%s)'
                msg = msg % (self.name, ','.join(list(kwargs.keys())))
                self.raise_exc(exc=TypeError, msg=msg)

        except (ValueError, LookupError, TypeError,
                NameError, AttributeError):
            msg = 'incorrect arguments for procedure %s' % self.name
            self.raise_exc(msg=msg)

        stable  = self._larch.symtable
        stable.save_frame()
        stable.set_frame((lgroup, self.modgroup))
        retval = None
        self._larch.retval = None

        for node in self.body:
            self._larch.run(node, fname=self.__file__, func=self,
                            lineno=node.lineno+self.lineno, with_raise=False)
            if len(self._larch.error) > 0:
                break
            if self._larch.retval is not None:
                retval = self._larch.retval
                break
        stable.restore_frame()
        self._larch.retval = None
        del lgroup
        return retval

class DefinedVariable(object):
    """defined variable: re-evaluate on access

    Note that the localGroup/moduleGroup are cached
    at compile time, and restored for evaluation.
    """
    def __init__(self, expr=None, _larch=None):
        self.expr = expr
        self._larch = _larch
        self.ast = None
        self._groups = None, None
        self.compile()

    def __repr__(self):
        return "<DefinedVariable: '%s'>" % (self.expr)

    def compile(self):
        """compile to ast"""
        if self._larch is not None and self.expr is not None:
            self.ast = self._larch.parse(self.expr)

    def evaluate(self):
        "actually evaluate ast to a value"
        if self.ast is None:
            self.compile()
        if self.ast is None:
            msg = "Cannot compile '%s'"  % (self.expr)
            raise Warning(msg)

        if hasattr(self._larch, 'run'):
            # save current localGroup/moduleGroup
            self._larch.symtable.save_frame()
            rval = self._larch.run(self.ast, expr=self.expr)
            self._larch.symtable.restore_frame()
            return rval
        else:
            raise ValueError("Cannot evaluate '%s'"  % (self.expr))

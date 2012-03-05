'''
   Main Larch interpreter
'''
from __future__ import division, print_function
import os
import sys
import ast
import math
try:
    import numpy
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False

from . import builtins
from . import site_config
from .symboltable import SymbolTable, Group, isgroup
from .larchlib import LarchExceptionHolder, Procedure, DefinedVariable
from .utils import Closure

__version__ = '0.9.8'

OPERATORS = {ast.Is:     lambda a, b: a is b,
             ast.IsNot:  lambda a, b: a is not b,
             ast.In:     lambda a, b: a in b,
             ast.NotIn:  lambda a, b: a not in b,
             ast.Add:    lambda a, b: a + b,
             ast.BitAnd: lambda a, b: a & b,
             ast.BitOr:  lambda a, b: a | b,
             ast.BitXor: lambda a, b: a ^ b,
             ast.Div:    lambda a, b: a / b,
             ast.FloorDiv: lambda a, b: a // b,
             ast.LShift: lambda a, b: a << b,
             ast.RShift: lambda a, b: a >> b,
             ast.Mult:   lambda a, b: a * b,
             ast.Pow:    lambda a, b: a ** b,
             ast.Sub:    lambda a, b: a - b,
             ast.Mod:    lambda a, b: a % b,
             ast.And:    lambda a, b: a and b,
             ast.Or:     lambda a, b: a or b,
             ast.Eq:     lambda a, b: a == b,
             ast.Gt:     lambda a, b: a > b,
             ast.GtE:    lambda a, b: a >= b,
             ast.Lt:     lambda a, b: a < b,
             ast.LtE:    lambda a, b: a <= b,
             ast.NotEq:  lambda a, b: a != b,
             ast.Invert: lambda a: ~a,
             ast.Not:    lambda a: not a,
             ast.UAdd:   lambda a: +a,
             ast.USub:   lambda a: -a}


class Interpreter:
    """larch program compiler and interpreter.
  This module compiles expressions and statements to AST representation,
  using python's ast module, and then executes the AST representation
  using a custom SymbolTable for named object (variable, functions).
  This then gives a restricted version of Python, with slightly modified
  namespace rules.  The program syntax here is expected to be valid Python,
  but that may have been translated as with the inputText module.

  The following Python syntax is not supported:
      Exec, Lambda, Class, Global, Generators, Yield, Decorators

  In addition, Function is greatly altered so as to allow a Larch procedure.
  """

    supported_nodes = ('assert', 'assign', 'attribute', 'augassign', 'binop',
                       'boolop', 'break', 'call', 'compare', 'continue',
                       'delete', 'dict', 'ellipsis', 'excepthandler', 'expr',
                       'expression', 'extslice', 'for', 'functiondef', 'if',
                       'ifexp', 'import', 'importfrom', 'index', 'interrupt',
                       'list', 'listcomp', 'module', 'name', 'num', 'pass',
                       'print', 'raise', 'repr', 'return', 'slice', 'str',
                       'subscript', 'tryexcept', 'tuple', 'unaryop', 'while')

    def __init__(self, symtable=None, writer=None):
        self.writer = writer or sys.stdout

        if symtable is None:
            symtable = SymbolTable(larch=self)
        self.symtable   = symtable
        self._interrupt = None
        self.error      = []
        self.expr       = None
        self.retval     = None
        self.fname     = '<StdInput>'
        self.lineno    = -1
        builtingroup = getattr(symtable,'_builtin')
        mathgroup    = getattr(symtable,'_math')
        setattr(mathgroup, 'j', 1j)

        for sym in builtins.from_math:
            setattr(mathgroup, sym, getattr(math, sym))

        for sym in builtins.from_builtin:
            setattr(builtingroup, sym, __builtins__[sym])

        if HAS_NUMPY:
            for sym in builtins.from_numpy:
                try:
                    setattr(mathgroup, sym, getattr(numpy, sym))
                except AttributeError:
                    pass
            for fname, sym in list(builtins.numpy_renames.items()):
                setattr(mathgroup, fname, getattr(numpy, sym))

        for fname, fcn in list(builtins.local_funcs.items()):
            setattr(builtingroup, fname,
                    Closure(func=fcn, larch=self, _name=fname))
        setattr(builtingroup, 'definevar',
                Closure(func=self.set_definedvariable))

        self.node_handlers = {}
        for tnode in self.supported_nodes:
            self.node_handlers[tnode] = getattr(self, "on_%s" % tnode)

        # add all plugins in standard plugins folder
        plugins_dir = os.path.join(site_config.sys_larchdir, 'plugins')
        for pname in os.listdir(plugins_dir):
            pdir = os.path.join(plugins_dir, pname)
            if os.path.isdir(pdir):
                self.add_plugin(pdir)

    def add_plugin(self, mod, **kws):
        """add plugin components from plugin directory"""
        builtins._addplugin(mod, larch=self, **kws)

    def set_definedvariable(self, name, expr):
        """define a defined variable (re-evaluate on access)"""
        self.symtable.set_symbol(name,
                                 DefinedVariable(expr=expr, larch=self))

    def unimplemented(self, node):
        "unimplemented nodes"
        msg = "'%s' not supported" % (node.__class__.__name__)
        self.raise_exception(node=node, msg=msg)

    def raise_exception(self, node=None, msg='', expr=None, exc=None,
                        fname=None, lineno=None, func=None):
        "add an exception"
        if self.error is None: self.error = []
        if expr  is None:   expr  = self.expr
        if fname is None:   fname = self.fname
        if lineno is None:  lineno = self.lineno

        if len(self.error) > 0 and not isinstance(node, ast.Module):
            msg = '%s' % msg
        err = LarchExceptionHolder(node, msg=msg, expr=expr, exc=exc,
                                   fname=fname, lineno=lineno, func=func)
        self.error.append(err)
        self.symtable._sys.last_error = err
        self._interrupt = ast.Break()

        # print("_Raise ", self.error)

    # main entry point for Ast node evaluation
    #  compile:  string statement -> ast
    #  interp :  ast -> result
    #  eval   :  string statement -> result = interp(compile(statement))
    def compile(self, text, fname=None, lineno=-4):
        """compile statement/expression to Ast representation    """
        self.expr  = text
        try:
            return ast.parse(text)
        except:
            self.raise_exception(msg='Syntax Error',
                                 expr=text, fname=fname, lineno=lineno)

    def interp(self, node, expr=None, fname=None, lineno=None):
        """executes compiled Ast representation for an expression"""
        # Note: keep the 'node is None' test: internal code here may run
        #    interp(None) and expect a None in return.
        # print(" Interp", node, expr)
        if node is None:
            return None
        if isinstance(node, str):
            node = self.compile(node)
        if lineno is not None:
            self.lineno = lineno
        if fname  is not None:
            self.fname  = fname
        if expr   is not None:
            self.expr   = expr

        # get handler for this node:
        #   on_xxx with handle nodes of type 'xxx', etc
        try:
            handler = self.node_handlers[node.__class__.__name__.lower()]
        except KeyError:
            return self.unimplemented(node)

        # run the handler:  this will likely generate
        # recursive calls into this interp method.
        try:
            #print(" Interp NODE ", ast.dump(node))
            ret = handler(node)
            if isinstance(ret, enumerate):
                ret = list(ret)
            return ret

        except:
            self.raise_exception(node=node, msg='Runtime Error',
                                 expr=expr, fname=fname, lineno=lineno)

    def __call__(self, expr, **kw):
        return self.eval(expr, **kw)

    def eval(self, expr, fname=None, lineno=0):
        """evaluates a single statement"""
        self.fname = fname
        self.lineno = lineno
        self.error = []

        node = self.compile(expr, fname=fname, lineno=lineno)
        out = None
        if len(self.error) > 0:
            self.raise_exception(node=node, msg='Syntax Error', expr=expr,
                                 fname=fname, lineno=lineno)
        else:
            out = self.interp(node, expr=expr, fname=fname, lineno=lineno)
        return out

    def run_init_scripts(self):
        for fname in site_config.init_files:
            if os.path.exists(fname):
                try:
                    builtins._run(filename=fname, larch=self,
                                  printall = True)
                except:
                    self.raise_exception(msg='Initialization Error')

    def dump(self, node, **kw):
        "simple ast dumper"
        return ast.dump(node, **kw)

    # handlers for ast components
    def on_expr(self, node):
        "expression"
        return self.interp(node.value)  # ('value',)

    def on_index(self, node):
        "index"
        return self.interp(node.value)  # ('value',)

    def on_return(self, node): # ('value',)
        "return statement"
        self.retval = self.interp(node.value)
        return

    def on_repr(self, node):
        "repr "
        return repr(self.interp(node.value))  # ('value',)

    def on_module(self, node):    # ():('body',)
        "module def"
        out = None
        for tnode in node.body:
            out = self.interp(tnode)
        return out

    def on_expression(self, node):
        "basic expression"
        return self.on_module(node) # ():('body',)

    def on_pass(self, node):
        "pass statement"
        return None  # ()

    def on_ellipsis(self, node):
        "ellipses"
        return Ellipsis

    # for break and continue: set the instance variable _interrupt
    def on_interrupt(self, node):    # ()
        "interrupt handler"
        self._interrupt = node
        return node

    def on_break(self, node):
        "break"
        return self.on_interrupt(node)

    def on_continue(self, node):
        "continue"
        return self.on_interrupt(node)

    def on_assert(self, node):    # ('test', 'msg')
        "assert statement"
        if not self.interp(node.test):
            raise AssertionError(self.interp(node.msg()))
        return True

    def on_list(self, node):    # ('elt', 'ctx')
        "list"
        return [self.interp(e) for e in node.elts]

    def on_tuple(self, node):    # ('elts', 'ctx')
        "tuple"
        return tuple(self.on_list(node))

    def on_dict(self, node):    # ('keys', 'values')
        "dictionary"
        nodevals = list(zip(node.keys, node.values))
        interp = self.interp
        return dict([(interp(k), interp(v)) for k, v in nodevals])

    def on_num(self, node):
        'return number'
        return node.n  # ('n',)

    def on_str(self, node):
        'return string'
        return node.s  # ('s',)

    def on_name(self, node):    # ('id', 'ctx')
        """ Name node """
        ctx = node.ctx.__class__
        if ctx == ast.Del:
            val = self.symtable.del_symbol(node.id)
        elif ctx == ast.Param:  # for Function Def
            val = str(node.id)
        else:
            val = self.symtable.get_symbol(node.id)
            if isinstance(val, DefinedVariable):
                val = val.evaluate()
        return val

    def node_assign(self, nod, val):
        """here we assign a value (not the node.value object) to a node
        this is used by on_assign, but also by for, list comprehension, etc.
        """
        if len(self.error) > 0:
            return
        if nod.__class__ == ast.Name:
            sym = self.symtable.set_symbol(nod.id, value=val)
        elif nod.__class__ == ast.Attribute:
            if nod.ctx.__class__  == ast.Load:
                errmsg = "cannot assign to attribute %s" % nod.attr
                self.raise_exception(node=nod, msg=errmsg)

            setattr(self.interp(nod.value), nod.attr, val)

        elif nod.__class__ == ast.Subscript:
            sym    = self.interp(nod.value)
            xslice = self.interp(nod.slice)
            if isinstance(nod.slice, ast.Index):
                sym.__setitem__(xslice, val)
            elif isinstance(nod.slice, ast.Slice):
                i = xslice.start
                if i is None: i = 0
                j = xslice.stop
                if j is None: j = len(sym)
                if xslice.step is None:
                    sym.__setslice__(i, j, val)
                else:
                    for ival, isym in enumerate(range(i, j , xslice.step)):
                        sym.__setitem__(isym, val[ival])
            elif isinstance(nod.slice, ast.ExtSlice):
                sym[(xslice)] = val
        elif nod.__class__ in (ast.Tuple, ast.List):
            if len(val) == len(nod.elts):
                for telem, tval in zip(nod.elts, val):
                    self.node_assign(telem, tval)
            else:
                raise ValueError('too many values to unpack')

    def on_attribute(self, node):    # ('value', 'attr', 'ctx')
        "extract attribute"
        ctx = node.ctx.__class__
        # print("on_attribute",node.value,node.attr,ctx)
        if ctx == ast.Load:
            sym = self.interp(node.value)
            if hasattr(sym, node.attr):
                val = getattr(sym, node.attr)
                if isinstance(val, DefinedVariable):
                    val = val.evaluate()
                return val
            else:
                obj = self.interp(node.value)
                fmt = "%s does not have member '%s'"
                if not isgroup(obj):
                    obj = obj.__class__
                    fmt = "%s does not have attribute '%s'"
                msg = fmt % (obj, node.attr)

                self.raise_exception(node=node, msg=msg)

        elif ctx == ast.Del:
            return delattr(sym, node.attr)
        elif ctx == ast.Store:
            msg = "attribute for storage: shouldn't be here!"
            self.raise_exception(node=node, msg=msg)

    def on_assign(self, node):    # ('targets', 'value')
        "simple assignment"
        val = self.interp(node.value)
        if len(self.error) > 0:
            return
        for tnode in node.targets:
            self.node_assign(tnode, val)
        return # return val

    def on_augassign(self, node):    # ('target', 'op', 'value')
        "augmented assign"
        # print( "AugASSIGN ", node.target, node.value)
        return self.on_assign(ast.Assign(targets=[node.target],
                                         value=ast.BinOp(left = node.target,
                                                         op   = node.op,
                                                         right= node.value)))

    def on_slice(self, node):    # ():('lower', 'upper', 'step')
        "simple slice"
        return slice(self.interp(node.lower), self.interp(node.upper),
                     self.interp(node.step))

    def on_extslice(self, node):    # ():('dims',)
        "extended slice"
        return tuple([self.interp(tnode) for tnode in node.dims])

    def on_subscript(self, node):    # ('value', 'slice', 'ctx')
        "subscript handling -- one of the tricky parts"
        # print("on_subscript: ", ast.dump(node))
        val    = self.interp(node.value)
        nslice = self.interp(node.slice)
        ctx = node.ctx.__class__
        if ctx in ( ast.Load, ast.Store):
            if isinstance(node.slice, (ast.Index, ast.Slice, ast.Ellipsis)):
                return val.__getitem__(nslice)
            elif isinstance(node.slice, ast.ExtSlice):
                return val[(nslice)]
        else:
            msg = "subscript with unknown context"
            self.raise_exception(node=node, msg=msg)

    def on_delete(self, node):    # ('targets',)
        "delete statement"
        for tnode in node.targets:
            if tnode.ctx.__class__ != ast.Del:
                break
            children = []
            while tnode.__class__ == ast.Attribute:
                children.append(tnode.attr)
                tnode = tnode.value

            if tnode.__class__ == ast.Name:
                children.append(tnode.id)
                children.reverse()
                self.symtable.del_symbol('.'.join(children))
            else:
                msg = "could not delete symbol"
                self.raise_exception(node=node, msg=msg)

    def on_unaryop(self, node):    # ('op', 'operand')
        "unary operator"
        return OPERATORS[node.op.__class__](self.interp(node.operand))

    def on_binop(self, node):    # ('left', 'op', 'right')
        "binary operator"
        # print( 'BINARY  OP! ', node.left, node.right, node.op)
        return OPERATORS[node.op.__class__](self.interp(node.left),
                                            self.interp(node.right))

    def on_boolop(self, node):    # ('op', 'values')
        "boolean operator"
        val = self.interp(node.values[0])
        is_and = ast.And == node.op.__class__
        if (is_and and val) or (not is_and and not val):
            for n in node.values[1:]:
                val =  OPERATORS[node.op.__class__](val, self.interp(n))
                if (is_and and not val) or (not is_and and val):
                    break
        return val

    def on_compare(self, node):    # ('left', 'ops', 'comparators')
        "comparison operators"
        lval = self.interp(node.left)
        out  = True
        for oper, rnode in zip(node.ops, node.comparators):
            comp = OPERATORS[oper.__class__]
            rval = self.interp(rnode)
            out  = comp(lval, rval)
            lval = rval
            if HAS_NUMPY and isinstance(out, numpy.ndarray) and out.any():
                break
            elif not out:
                break
        return out

    def on_print(self, node):    # ('dest', 'values', 'nl')
        """ note: implements Python2 style print statement, not
        print() function.  Probably, the 'larch2py' translation
        should look for and translate print -> print_() to become
        a customized function call.
        """
        dest = self.interp(node.dest) or self.writer
        end = ''
        if node.nl:
            end = '\n'
        out = [self.interp(tnode) for tnode in node.values]
        if out and len(self.error)==0:
            print(*out, file=dest, end=end)

    def on_if(self, node):    # ('test', 'body', 'orelse')
        "regular if-then-else statement"
        block = node.body
        if not self.interp(node.test):
            block = node.orelse
        for tnode in block:
            self.interp(tnode)

    def on_ifexp(self, node):    # ('test', 'body', 'orelse')
        "if expressions"
        expr = node.orelse
        if self.interp(node.test):
            expr = node.body
        return self.interp(expr)

    def on_while(self, node):    # ('test', 'body', 'orelse')
        "while blocks"
        while self.interp(node.test):
            self._interrupt = None
            for tnode in node.body:
                self.interp(tnode)
                if self._interrupt is not None:
                    break
            if isinstance(self._interrupt, ast.Break):
                break
        else:
            for tnode in node.orelse:
                self.interp(tnode)
        self._interrupt = None

    def on_for(self, node):    # ('target', 'iter', 'body', 'orelse')
        "for blocks"
        for val in self.interp(node.iter):
            self.node_assign(node.target, val)
            if len(self.error) > 0:
                return
            self._interrupt = None
            for tnode in node.body:
                self.interp(tnode)
                if len(self.error) > 0:
                    return
                if self._interrupt is not None:
                    break
            if isinstance(self._interrupt, ast.Break):
                break
        else:
            for tnode in node.orelse:
                self.interp(tnode)
        self._interrupt = None

    def on_listcomp(self, node):    # ('elt', 'generators')
        "list comprehension"
        out = []
        for tnode in node.generators:
            if tnode.__class__ == ast.comprehension:
                for val in self.interp(tnode.iter):
                    self.node_assign(tnode.target, val)
                    if len(self.error) > 0:
                        return
                    add = True
                    for cond in tnode.ifs:
                        add = add and self.interp(cond)
                    if add:
                        out.append(self.interp(node.elt))
        return out


    #
    def on_excepthandler(self, node): # ('type', 'name', 'body')
        "exception handler..."
        # print("except handler %s / %s " % (node.type, ast.dump(node.name)))
        return (self.interp(node.type), node.name, node.body)

    def on_tryexcept(self, node):    # ('body', 'handlers', 'orelse')
        "try/except blocks"
        no_errors = True
        for tnode in node.body:
            self.interp(tnode)
            no_errors = no_errors and len(self.error) == 0
            if self.error:
                e_type, e_value, e_tb = self.error[-1].exc_info
                this_exc = e_type()
                for hnd in node.handlers:
                    htype = None
                    if hnd.type is not None:
                        htype = __builtins__.get(hnd.type.id, None)
                    if htype is None or isinstance(this_exc, htype):
                        self.error = []
                        if hnd.name is not None:
                            self.node_assign(hnd.name, e_value)
                        for tline in hnd.body:
                            self.interp(tline)
                        break
        if no_errors:
            for tnode in node.orelse:
                self.interp(tnode)


    def on_raise(self, node):    # ('type', 'inst', 'tback')
        "raise statement"
        # print(" ON RAISE ", node.type, node.inst, node.tback)
        if node.type.__class__ == ast.Name:
            msg = "%s: %s" % (self.interp(node.type).__name__,
                              self.interp(node.inst))
        elif node.type.__class__ == ast.Call:
            msg = "%s" % (repr(self.interp(node.type)))
        self.raise_exception(node=node.type, exc=(None, msg, None))

    def on_call(self, node):
        "function/procedure execution"
        #  ('func', 'args', 'keywords', 'starargs', 'kwargs')
        func = self.interp(node.func)
        if not hasattr(func, '__call__') and not hasattr(func, '__init__'):
            msg = "'%s' is not callable!!" % (func)
            self.raise_exception(node=node, msg=msg)

        args = [self.interp(targ) for targ in node.args]
        if node.starargs is not None:
            args = args + self.interp(node.starargs)

        keywords = {}
        for key in node.keywords:
            if not isinstance(key, ast.keyword):
                msg = "keyword error in function call '%s'" % (func)
                self.raise_exception(node=node, msg=msg)

            keywords[key.arg] = self.interp(key.value)
        if node.kwargs is not None:
            keywords.update(self.interp(node.kwargs))

        try:
            return func(*args, **keywords)
        except:
            self.raise_exception(node=node, func=func,
                                 msg = "Error running %s" % (func))

    def on_functiondef(self, node):
        "define procedures"
        # ('name', 'args', 'body', 'decorator_list')
        if node.decorator_list != []:
            raise Warning("decorated procedures not supported!")
        kwargs = []
        offset = len(node.args.args) - len(node.args.defaults)
        for idef, defnode in enumerate(node.args.defaults):
            defval = self.interp(defnode)
            keyval = self.interp(node.args.args[idef+offset])
            kwargs.append((keyval, defval))
        # kwargs.reverse()
        args = [tnode.id for tnode in node.args.args[:offset]]
        doc = None
        if (isinstance(node.body[0], ast.Expr) and
            isinstance(node.body[0].value, ast.Str)):
            docnode = node.body[0]
            doc = docnode.value.s
        proc = Procedure(node.name, larch= self, doc= doc,
                         body   = node.body,
                         fname  = self.fname,
                         lineno = self.lineno,
                         args   = args,
                         kwargs = kwargs,
                         vararg = node.args.vararg,
                         varkws = node.args.kwarg)
        self.symtable.set_symbol(node.name, value=proc)

    # imports
    def on_import(self, node):    # ('names',)
        "simple import"
        for tnode in node.names:
            self.import_module(tnode.name, asname=tnode.asname)

    def on_importfrom(self, node):    # ('module', 'names', 'level')
        "import/from"
        fromlist, asname = [], []
        for tnode in node.names:
            fromlist.append(tnode.name)
            asname.append(tnode.asname)
        self.import_module(node.module,
                           asname=asname, fromlist=fromlist)


    def import_module(self, name, asname=None,
                      fromlist=None, do_reload=False):
        """
        import a module (larch or python), installing it into the symbol table.
        required arg:
            name       name of module to import
                          'foo' in 'import foo'
        options:
            fromlist   list of symbols to import with 'from-import'
                          ['x','y'] in 'from foo import x, y'
            asname     alias for imported name(s)
                          'bar' in 'import foo as bar'
                       or
                          ['s','t'] in 'from foo import x as s, y as t'

        this method covers a lot of cases (larch or python, import
        or from-import, use of asname) and so is fairly long.
        """
        # print("IMPORT MOD ", name, asname, fromlist)
        st_sys = self.symtable._sys
        for idir in st_sys.path:
            if idir not in sys.path and os.path.exists(idir):
                sys.path.append(idir)
        #print( " (import  ", name, " )" )
        #print( " st path", st_sys.path)

        # step 1  import the module to a global location
        #   either sys.modules for python modules
        #   or  st_sys.modules for larch modules
        # reload takes effect here in the normal python way:
        if (do_reload or
            ((name not in st_sys.modules) and (name not in sys.modules))):
            # first look for "name.lar"
            # print('import_mod A ', name)
            islarch = False
            larchname = "%s.lar" % name
            for dirname in st_sys.path:
                if not os.path.exists(dirname):
                    continue
                if larchname in os.listdir(dirname):
                    islarch = True
                    modname = os.path.abspath(os.path.join(dirname, larchname))
                    try:
                        thismod = builtins._run(filename=modname, larch=self,
                                                new_module=name)
                    except:
                        self.raise_exception(msg='Import Error')
                    # print(" isLarch!!", name, modname)
                    # save current module group
                    #  create new group, set as moduleGroup and localGroup
            if len(self.error) > 0:
                st_sys.modules.pop(name)
                # thismod = None
                return
            # or, if not a larch module, load as a regular python module
            if not islarch and name not in sys.modules:
                try:
                    # print('import_mod: py import! ', name)
                    __import__(name)
                    thismod = sys.modules[name]
                except:
                    self.raise_exception(msg='Import Error')
                    return
        else: # previously loaded module, just do lookup
            # print("prev loaded?")
            if name in st_sys.modules:
                thismod = st_sys.modules[name]
            elif name in sys.modules:
                thismod = sys.modules[name]

        # now we install thismodule into the current moduleGroup
        # import full module
        if fromlist is None:
            if asname is None:
                asname = name
            parts = asname.split('.')
            asname = parts.pop()
            targetgroup = st_sys.moduleGroup
            while len(parts) > 0:
                subname = parts.pop(0)
                subgrp  = Group()
                setattr(targetgroup, subname, subgrp)
                targetgroup = subgrp
            setattr(targetgroup, asname, thismod)
        # import-from construct
        else:
            if asname is None:
                asname = [None]*len(fromlist)
            targetgroup = st_sys.moduleGroup
            for sym, alias in zip(fromlist, asname):
                if alias is None:
                    alias = sym
                setattr(targetgroup, alias, getattr(thismod, sym))
    # end of import_module

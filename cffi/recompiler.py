import os, sys, io
from . import ffiplatform, model
from .cffi_opcode import *

VERSION = "0x2601"

try:
    int_type = (int, long)
except NameError:    # Python 3
    int_type = int


class GlobalExpr:
    def __init__(self, name, address, type_op, size=0, check_value=0):
        self.name = name
        self.address = address
        self.type_op = type_op
        self.size = size
        self.check_value = check_value

    def as_c_expr(self):
        return '  { "%s", (void *)%s, %s, (void *)%s },' % (
            self.name, self.address, self.type_op.as_c_expr(), self.size)

    def as_python_expr(self):
        return "b'%s%s',%d" % (self.type_op.as_python_bytes(), self.name,
                               self.check_value)

class FieldExpr:
    def __init__(self, name, field_offset, field_size, fbitsize, field_type_op):
        self.name = name
        self.field_offset = field_offset
        self.field_size = field_size
        self.fbitsize = fbitsize
        self.field_type_op = field_type_op

    def as_c_expr(self):
        spaces = " " * len(self.name)
        return ('  { "%s", %s,\n' % (self.name, self.field_offset) +
                '     %s   %s,\n' % (spaces, self.field_size) +
                '     %s   %s },' % (spaces, self.field_type_op.as_c_expr()))

    def as_python_expr(self):
        raise NotImplementedError

    def as_field_python_expr(self):
        if self.field_type_op.op == OP_NOOP:
            size_expr = ''
        elif self.field_type_op.op == OP_BITFIELD:
            size_expr = format_four_bytes(self.fbitsize)
        else:
            raise NotImplementedError
        return "b'%s%s%s'" % (self.field_type_op.as_python_bytes(),
                              size_expr,
                              self.name)

class StructUnionExpr:
    def __init__(self, name, type_index, flags, size, alignment, comment,
                 first_field_index, c_fields):
        self.name = name
        self.type_index = type_index
        self.flags = flags
        self.size = size
        self.alignment = alignment
        self.comment = comment
        self.first_field_index = first_field_index
        self.c_fields = c_fields

    def as_c_expr(self):
        return ('  { "%s", %d, %s,' % (self.name, self.type_index, self.flags)
                + '\n    %s, %s, ' % (self.size, self.alignment)
                + '%d, %d ' % (self.first_field_index, len(self.c_fields))
                + ('/* %s */ ' % self.comment if self.comment else '')
                + '},')

    def as_python_expr(self):
        flags = eval(self.flags, G_FLAGS)
        fields_expr = [c_field.as_field_python_expr()
                       for c_field in self.c_fields]
        return "(b'%s%s%s',%s)" % (
            format_four_bytes(self.type_index),
            format_four_bytes(flags),
            self.name,
            ','.join(fields_expr))

class EnumExpr:
    def __init__(self, name, type_index, size, signed, allenums):
        self.name = name
        self.type_index = type_index
        self.size = size
        self.signed = signed
        self.allenums = allenums

    def as_c_expr(self):
        return ('  { "%s", %d, _cffi_prim_int(%s, %s),\n'
                '    "%s" },' % (self.name, self.type_index,
                                 self.size, self.signed, self.allenums))

    def as_python_expr(self):
        prim_index = {
            (1, 0): PRIM_UINT8,  (1, 1):  PRIM_INT8,
            (2, 0): PRIM_UINT16, (2, 1):  PRIM_INT16,
            (4, 0): PRIM_UINT32, (4, 1):  PRIM_INT32,
            (8, 0): PRIM_UINT64, (8, 1):  PRIM_INT64,
            }[self.size, self.signed]
        return "b'%s%s%s\\x00%s'" % (format_four_bytes(self.type_index),
                                     format_four_bytes(prim_index),
                                     self.name, self.allenums)

class TypenameExpr:
    def __init__(self, name, type_index):
        self.name = name
        self.type_index = type_index

    def as_c_expr(self):
        return '  { "%s", %d },' % (self.name, self.type_index)

    def as_python_expr(self):
        return "b'%s%s'" % (format_four_bytes(self.type_index), self.name)


# ____________________________________________________________


class Recompiler:

    def __init__(self, ffi, module_name, target_is_python=False):
        self.ffi = ffi
        self.module_name = module_name
        self.target_is_python = target_is_python

    def collect_type_table(self):
        self._typesdict = {}
        self._generate("collecttype")
        #
        all_decls = sorted(self._typesdict, key=str)
        #
        # prepare all FUNCTION bytecode sequences first
        self.cffi_types = []
        for tp in all_decls:
            if tp.is_raw_function:
                assert self._typesdict[tp] is None
                self._typesdict[tp] = len(self.cffi_types)
                self.cffi_types.append(tp)     # placeholder
                for tp1 in tp.args:
                    assert isinstance(tp1, (model.VoidType,
                                            model.BasePrimitiveType,
                                            model.PointerType,
                                            model.StructOrUnionOrEnum,
                                            model.FunctionPtrType))
                    if self._typesdict[tp1] is None:
                        self._typesdict[tp1] = len(self.cffi_types)
                    self.cffi_types.append(tp1)   # placeholder
                self.cffi_types.append('END')     # placeholder
        #
        # prepare all OTHER bytecode sequences
        for tp in all_decls:
            if not tp.is_raw_function and self._typesdict[tp] is None:
                self._typesdict[tp] = len(self.cffi_types)
                self.cffi_types.append(tp)        # placeholder
                if tp.is_array_type and tp.length is not None:
                    self.cffi_types.append('LEN') # placeholder
        assert None not in self._typesdict.values()
        #
        # collect all structs and unions and enums
        self._struct_unions = {}
        self._enums = {}
        for tp in all_decls:
            if isinstance(tp, model.StructOrUnion):
                self._struct_unions[tp] = None
            elif isinstance(tp, model.EnumType):
                self._enums[tp] = None
        for i, tp in enumerate(sorted(self._struct_unions,
                                      key=lambda tp: tp.name)):
            self._struct_unions[tp] = i
        for i, tp in enumerate(sorted(self._enums,
                                      key=lambda tp: tp.name)):
            self._enums[tp] = i
        #
        # emit all bytecode sequences now
        for tp in all_decls:
            method = getattr(self, '_emit_bytecode_' + tp.__class__.__name__)
            method(tp, self._typesdict[tp])
        #
        # consistency check
        for op in self.cffi_types:
            assert isinstance(op, CffiOp)
        self.cffi_types = tuple(self.cffi_types)    # don't change any more

    def _do_collect_type(self, tp):
        if not isinstance(tp, model.BaseTypeByIdentity):
            if isinstance(tp, tuple):
                for x in tp:
                    self._do_collect_type(x)
            return
        if tp not in self._typesdict:
            self._typesdict[tp] = None
            if isinstance(tp, model.FunctionPtrType):
                self._do_collect_type(tp.as_raw_function())
            elif isinstance(tp, model.StructOrUnion):
                if tp.fldtypes is not None and (
                        tp not in self.ffi._parser._included_declarations):
                    for name1, tp1, _ in tp.enumfields():
                        self._do_collect_type(self._field_type(tp, name1, tp1))
            else:
                for _, x in tp._get_items():
                    self._do_collect_type(x)

    def _get_declarations(self):
        return sorted(self.ffi._parser._declarations.items())

    def _generate(self, step_name):
        for name, tp in self._get_declarations():
            kind, realname = name.split(' ', 1)
            try:
                method = getattr(self, '_generate_cpy_%s_%s' % (kind,
                                                                step_name))
            except AttributeError:
                raise ffiplatform.VerificationError(
                    "not implemented in recompile(): %r" % name)
            try:
                method(tp, realname)
            except Exception as e:
                model.attach_exception_info(e, name)
                raise

    # ----------

    ALL_STEPS = ["global", "field", "struct_union", "enum", "typename"]

    def collect_step_tables(self):
        # collect the declarations for '_cffi_globals', '_cffi_typenames', etc.
        self._lsts = {}
        for step_name in self.ALL_STEPS:
            self._lsts[step_name] = []
        self._seen_struct_unions = set()
        self._generate("ctx")
        self._add_missing_struct_unions()
        #
        for step_name in self.ALL_STEPS:
            lst = self._lsts[step_name]
            if step_name != "field":
                lst.sort(key=lambda entry: entry.name)
            self._lsts[step_name] = tuple(lst)    # don't change any more
        #
        # check for a possible internal inconsistency: _cffi_struct_unions
        # should have been generated with exactly self._struct_unions
        lst = self._lsts["struct_union"]
        for tp, i in self._struct_unions.items():
            assert i < len(lst)
            assert lst[i].name == tp.name
        assert len(lst) == len(self._struct_unions)
        # same with enums
        lst = self._lsts["enum"]
        for tp, i in self._enums.items():
            assert i < len(lst)
            assert lst[i].name == tp.name
        assert len(lst) == len(self._enums)

    # ----------

    def _prnt(self, what=''):
        self._f.write(what + '\n')

    def write_source_to_f(self, f, preamble):
        if self.target_is_python:
            assert preamble is None
            self.write_py_source_to_f(f)
        else:
            assert preamble is not None
            self.write_c_source_to_f(f, preamble)

    def _rel_readlines(self, filename):
        g = open(os.path.join(os.path.dirname(__file__), filename), 'r')
        lines = g.readlines()
        g.close()
        return lines

    def write_c_source_to_f(self, f, preamble):
        self._f = f
        prnt = self._prnt
        #
        # first the '#include' (actually done by inlining the file's content)
        lines = self._rel_readlines('_cffi_include.h')
        i = lines.index('#include "parse_c_type.h"\n')
        lines[i:i+1] = self._rel_readlines('parse_c_type.h')
        prnt(''.join(lines))
        #
        # then paste the C source given by the user, verbatim.
        prnt('/************************************************************/')
        prnt()
        prnt(preamble)
        prnt()
        prnt('/************************************************************/')
        prnt()
        #
        # the declaration of '_cffi_types'
        prnt('static void *_cffi_types[] = {')
        typeindex2type = dict([(i, tp) for (tp, i) in self._typesdict.items()])
        for i, op in enumerate(self.cffi_types):
            comment = ''
            if i in typeindex2type:
                comment = ' // ' + typeindex2type[i]._get_c_name()
            prnt('/* %2d */ %s,%s' % (i, op.as_c_expr(), comment))
        if not self.cffi_types:
            prnt('  0')
        prnt('};')
        prnt()
        #
        # call generate_cpy_xxx_decl(), for every xxx found from
        # ffi._parser._declarations.  This generates all the functions.
        self._seen_constants = set()
        self._generate("decl")
        #
        # the declaration of '_cffi_globals' and '_cffi_typenames'
        nums = {}
        for step_name in self.ALL_STEPS:
            lst = self._lsts[step_name]
            nums[step_name] = len(lst)
            if nums[step_name] > 0:
                prnt('static const struct _cffi_%s_s _cffi_%ss[] = {' % (
                    step_name, step_name))
                for entry in lst:
                    prnt(entry.as_c_expr())
                prnt('};')
                prnt()
        #
        # the declaration of '_cffi_includes'
        if self.ffi._included_ffis:
            prnt('static const char * const _cffi_includes[] = {')
            for ffi_to_include in self.ffi._included_ffis:
                try:
                    included_module_name, included_source = (
                        ffi_to_include._assigned_source[:2])
                except AttributeError:
                    raise ffiplatform.VerificationError(
                        "ffi object %r includes %r, but the latter has not "
                        "been prepared with set_source()" % (
                            self.ffi, ffi_to_include,))
                if included_source is None:
                    raise ffiplatform.VerificationError(
                        "not implemented yet: ffi.include() of a Python-based "
                        "ffi inside a C-based ffi")
                prnt('  "%s",' % (included_module_name,))
            prnt('  NULL')
            prnt('};')
            prnt()
        #
        # the declaration of '_cffi_type_context'
        prnt('static const struct _cffi_type_context_s _cffi_type_context = {')
        prnt('  _cffi_types,')
        for step_name in self.ALL_STEPS:
            if nums[step_name] > 0:
                prnt('  _cffi_%ss,' % step_name)
            else:
                prnt('  NULL,  /* no %ss */' % step_name)
        for step_name in self.ALL_STEPS:
            if step_name != "field":
                prnt('  %d,  /* num_%ss */' % (nums[step_name], step_name))
        if self.ffi._included_ffis:
            prnt('  _cffi_includes,')
        else:
            prnt('  NULL,  /* no includes */')
        prnt('  %d,  /* num_types */' % (len(self.cffi_types),))
        prnt('  0,  /* flags */')
        prnt('};')
        prnt()
        #
        # the init function
        base_module_name = self.module_name.split('.')[-1]
        prnt('#ifdef PYPY_VERSION')
        prnt('PyMODINIT_FUNC')
        prnt('_cffi_pypyinit_%s(const void *p[])' % (base_module_name,))
        prnt('{')
        prnt('    p[0] = (const void *)%s;' % VERSION)
        prnt('    p[1] = &_cffi_type_context;')
        prnt('}')
        # on Windows, distutils insists on putting init_cffi_xyz in
        # 'export_symbols', so instead of fighting it, just give up and
        # give it one
        prnt('#  ifdef _MSC_VER')
        prnt('     PyMODINIT_FUNC')
        prnt('#  if PY_MAJOR_VERSION >= 3')
        prnt('     PyInit_%s(void) { return NULL; }' % (base_module_name,))
        prnt('#  else')
        prnt('     init%s(void) { }' % (base_module_name,))
        prnt('#  endif')
        prnt('#  endif')
        prnt('#elif PY_MAJOR_VERSION >= 3')
        prnt('PyMODINIT_FUNC')
        prnt('PyInit_%s(void)' % (base_module_name,))
        prnt('{')
        prnt('  return _cffi_init("%s", %s, &_cffi_type_context);' % (
            self.module_name, VERSION))
        prnt('}')
        prnt('#else')
        prnt('PyMODINIT_FUNC')
        prnt('init%s(void)' % (base_module_name,))
        prnt('{')
        prnt('  _cffi_init("%s", %s, &_cffi_type_context);' % (
            self.module_name, VERSION))
        prnt('}')
        prnt('#endif')

    def _to_py(self, x):
        if isinstance(x, str):
            return "b'%s'" % (x,)
        if isinstance(x, (list, tuple)):
            rep = [self._to_py(item) for item in x]
            if len(rep) == 1:
                rep.append('')
            return "(%s)" % (','.join(rep),)
        return x.as_python_expr()  # Py2: unicode unexpected; Py3: bytes unexp.

    def write_py_source_to_f(self, f):
        self._f = f
        prnt = self._prnt
        #
        # header
        prnt("# auto-generated file")
        prnt("import _cffi_backend")
        #
        # the 'import' of the included ffis
        num_includes = len(self.ffi._included_ffis or ())
        for i in range(num_includes):
            ffi_to_include = self.ffi._included_ffis[i]
            try:
                included_module_name, included_source = (
                    ffi_to_include._assigned_source[:2])
            except AttributeError:
                raise ffiplatform.VerificationError(
                    "ffi object %r includes %r, but the latter has not "
                    "been prepared with set_source()" % (
                        self.ffi, ffi_to_include,))
            if included_source is not None:
                raise ffiplatform.VerificationError(
                    "not implemented yet: ffi.include() of a C-based "
                    "ffi inside a Python-based ffi")
            prnt('from %s import ffi as _ffi%d' % (included_module_name, i))
        prnt()
        prnt("ffi = _cffi_backend.FFI('%s'," % (self.module_name,))
        prnt("    _version = %s," % (VERSION,))
        #
        # the '_types' keyword argument
        self.cffi_types = tuple(self.cffi_types)    # don't change any more
        types_lst = [op.as_python_bytes() for op in self.cffi_types]
        prnt('    _types = %s,' % (self._to_py(''.join(types_lst)),))
        typeindex2type = dict([(i, tp) for (tp, i) in self._typesdict.items()])
        #
        # the keyword arguments from ALL_STEPS
        for step_name in self.ALL_STEPS:
            lst = self._lsts[step_name]
            if len(lst) > 0 and step_name != "field":
                prnt('    _%ss = %s,' % (step_name, self._to_py(lst)))
        #
        # the '_includes' keyword argument
        if num_includes > 0:
            prnt('    _includes = (%s,),' % (
                ', '.join(['_ffi%d' % i for i in range(num_includes)]),))
        #
        # the footer
        prnt(')')

    # ----------

    def _gettypenum(self, type):
        # a KeyError here is a bug.  please report it! :-)
        return self._typesdict[type]

    def _convert_funcarg_to_c(self, tp, fromvar, tovar, errcode):
        extraarg = ''
        if isinstance(tp, model.BasePrimitiveType):
            if tp.is_integer_type() and tp.name != '_Bool':
                converter = '_cffi_to_c_int'
                extraarg = ', %s' % tp.name
            else:
                converter = '(%s)_cffi_to_c_%s' % (tp.get_c_name(''),
                                                   tp.name.replace(' ', '_'))
            errvalue = '-1'
        #
        elif isinstance(tp, model.PointerType):
            self._convert_funcarg_to_c_ptr_or_array(tp, fromvar,
                                                    tovar, errcode)
            return
        #
        elif isinstance(tp, (model.StructOrUnion, model.EnumType)):
            # a struct (not a struct pointer) as a function argument
            self._prnt('  if (_cffi_to_c((char *)&%s, _cffi_type(%d), %s) < 0)'
                      % (tovar, self._gettypenum(tp), fromvar))
            self._prnt('    %s;' % errcode)
            return
        #
        elif isinstance(tp, model.FunctionPtrType):
            converter = '(%s)_cffi_to_c_pointer' % tp.get_c_name('')
            extraarg = ', _cffi_type(%d)' % self._gettypenum(tp)
            errvalue = 'NULL'
        #
        else:
            raise NotImplementedError(tp)
        #
        self._prnt('  %s = %s(%s%s);' % (tovar, converter, fromvar, extraarg))
        self._prnt('  if (%s == (%s)%s && PyErr_Occurred())' % (
            tovar, tp.get_c_name(''), errvalue))
        self._prnt('    %s;' % errcode)

    def _extra_local_variables(self, tp, localvars):
        if isinstance(tp, model.PointerType):
            localvars.add('Py_ssize_t datasize')

    def _convert_funcarg_to_c_ptr_or_array(self, tp, fromvar, tovar, errcode):
        self._prnt('  datasize = _cffi_prepare_pointer_call_argument(')
        self._prnt('      _cffi_type(%d), %s, (char **)&%s);' % (
            self._gettypenum(tp), fromvar, tovar))
        self._prnt('  if (datasize != 0) {')
        self._prnt('    if (datasize < 0)')
        self._prnt('      %s;' % errcode)
        self._prnt('    %s = (%s)alloca((size_t)datasize);' % (
            tovar, tp.get_c_name('')))
        self._prnt('    memset((void *)%s, 0, (size_t)datasize);' % (tovar,))
        self._prnt('    if (_cffi_convert_array_from_object('
                   '(char *)%s, _cffi_type(%d), %s) < 0)' % (
            tovar, self._gettypenum(tp), fromvar))
        self._prnt('      %s;' % errcode)
        self._prnt('  }')

    def _convert_expr_from_c(self, tp, var, context):
        if isinstance(tp, model.BasePrimitiveType):
            if tp.is_integer_type():
                return '_cffi_from_c_int(%s, %s)' % (var, tp.name)
            elif tp.name != 'long double':
                return '_cffi_from_c_%s(%s)' % (tp.name.replace(' ', '_'), var)
            else:
                return '_cffi_from_c_deref((char *)&%s, _cffi_type(%d))' % (
                    var, self._gettypenum(tp))
        elif isinstance(tp, (model.PointerType, model.FunctionPtrType)):
            return '_cffi_from_c_pointer((char *)%s, _cffi_type(%d))' % (
                var, self._gettypenum(tp))
        elif isinstance(tp, model.ArrayType):
            return '_cffi_from_c_pointer((char *)%s, _cffi_type(%d))' % (
                var, self._gettypenum(model.PointerType(tp.item)))
        elif isinstance(tp, model.StructType):
            if tp.fldnames is None:
                raise TypeError("'%s' is used as %s, but is opaque" % (
                    tp._get_c_name(), context))
            return '_cffi_from_c_struct((char *)&%s, _cffi_type(%d))' % (
                var, self._gettypenum(tp))
        elif isinstance(tp, model.EnumType):
            return '_cffi_from_c_deref((char *)&%s, _cffi_type(%d))' % (
                var, self._gettypenum(tp))
        else:
            raise NotImplementedError(tp)

    # ----------
    # typedefs

    def _generate_cpy_typedef_collecttype(self, tp, name):
        self._do_collect_type(tp)

    def _generate_cpy_typedef_decl(self, tp, name):
        pass

    def _typedef_ctx(self, tp, name):
        type_index = self._typesdict[tp]
        self._lsts["typename"].append(TypenameExpr(name, type_index))

    def _generate_cpy_typedef_ctx(self, tp, name):
        self._typedef_ctx(tp, name)
        if getattr(tp, "origin", None) == "unknown_type":
            self._struct_ctx(tp, tp.name, approxname=None)
        elif isinstance(tp, model.NamedPointerType):
            self._struct_ctx(tp.totype, tp.totype.name, approxname=tp.name,
                             named_ptr=tp)

    # ----------
    # function declarations

    def _generate_cpy_function_collecttype(self, tp, name):
        self._do_collect_type(tp.as_raw_function())
        if tp.ellipsis and not self.target_is_python:
            self._do_collect_type(tp)

    def _generate_cpy_function_decl(self, tp, name):
        assert not self.target_is_python
        assert isinstance(tp, model.FunctionPtrType)
        if tp.ellipsis:
            # cannot support vararg functions better than this: check for its
            # exact type (including the fixed arguments), and build it as a
            # constant function pointer (no CPython wrapper)
            self._generate_cpy_constant_decl(tp, name)
            return
        prnt = self._prnt
        numargs = len(tp.args)
        if numargs == 0:
            argname = 'noarg'
        elif numargs == 1:
            argname = 'arg0'
        else:
            argname = 'args'
        #
        # ------------------------------
        # the 'd' version of the function, only for addressof(lib, 'func')
        arguments = []
        call_arguments = []
        context = 'argument of %s' % name
        for i, type in enumerate(tp.args):
            arguments.append(type.get_c_name(' x%d' % i, context))
            call_arguments.append('x%d' % i)
        repr_arguments = ', '.join(arguments)
        repr_arguments = repr_arguments or 'void'
        name_and_arguments = '_cffi_d_%s(%s)' % (name, repr_arguments)
        prnt('static %s' % (tp.result.get_c_name(name_and_arguments),))
        prnt('{')
        call_arguments = ', '.join(call_arguments)
        result_code = 'return '
        if isinstance(tp.result, model.VoidType):
            result_code = ''
        prnt('  %s%s(%s);' % (result_code, name, call_arguments))
        prnt('}')
        #
        prnt('#ifndef PYPY_VERSION')        # ------------------------------
        #
        prnt('static PyObject *')
        prnt('_cffi_f_%s(PyObject *self, PyObject *%s)' % (name, argname))
        prnt('{')
        #
        context = 'argument of %s' % name
        for i, type in enumerate(tp.args):
            arg = type.get_c_name(' x%d' % i, context)
            prnt('  %s;' % arg)
        #
        localvars = set()
        for type in tp.args:
            self._extra_local_variables(type, localvars)
        for decl in localvars:
            prnt('  %s;' % (decl,))
        #
        if not isinstance(tp.result, model.VoidType):
            result_code = 'result = '
            context = 'result of %s' % name
            result_decl = '  %s;' % tp.result.get_c_name(' result', context)
            prnt(result_decl)
        else:
            result_decl = None
            result_code = ''
        #
        if len(tp.args) > 1:
            rng = range(len(tp.args))
            for i in rng:
                prnt('  PyObject *arg%d;' % i)
            prnt('  PyObject **aa;')
            prnt()
            prnt('  aa = _cffi_unpack_args(args, %d, "%s");' % (len(rng), name))
            prnt('  if (aa == NULL)')
            prnt('    return NULL;')
            for i in rng:
                prnt('  arg%d = aa[%d];' % (i, i))
        prnt()
        #
        for i, type in enumerate(tp.args):
            self._convert_funcarg_to_c(type, 'arg%d' % i, 'x%d' % i,
                                       'return NULL')
            prnt()
        #
        prnt('  Py_BEGIN_ALLOW_THREADS')
        prnt('  _cffi_restore_errno();')
        call_arguments = ['x%d' % i for i in range(len(tp.args))]
        call_arguments = ', '.join(call_arguments)
        prnt('  { %s%s(%s); }' % (result_code, name, call_arguments))
        prnt('  _cffi_save_errno();')
        prnt('  Py_END_ALLOW_THREADS')
        prnt()
        #
        prnt('  (void)self; /* unused */')
        if numargs == 0:
            prnt('  (void)noarg; /* unused */')
        if result_code:
            prnt('  return %s;' %
                 self._convert_expr_from_c(tp.result, 'result', 'result type'))
        else:
            prnt('  Py_INCREF(Py_None);')
            prnt('  return Py_None;')
        prnt('}')
        #
        prnt('#else')        # ------------------------------
        #
        # the PyPy version: need to replace struct/union arguments with
        # pointers, and if the result is a struct/union, insert a first
        # arg that is a pointer to the result.
        difference = False
        arguments = []
        call_arguments = []
        context = 'argument of %s' % name
        for i, type in enumerate(tp.args):
            indirection = ''
            if isinstance(type, model.StructOrUnion):
                indirection = '*'
                difference = True
            arg = type.get_c_name(' %sx%d' % (indirection, i), context)
            arguments.append(arg)
            call_arguments.append('%sx%d' % (indirection, i))
        tp_result = tp.result
        if isinstance(tp_result, model.StructOrUnion):
            context = 'result of %s' % name
            arg = tp_result.get_c_name(' *result', context)
            arguments.insert(0, arg)
            tp_result = model.void_type
            result_decl = None
            result_code = '*result = '
            difference = True
        if difference:
            repr_arguments = ', '.join(arguments)
            repr_arguments = repr_arguments or 'void'
            name_and_arguments = '_cffi_f_%s(%s)' % (name, repr_arguments)
            prnt('static %s' % (tp_result.get_c_name(name_and_arguments),))
            prnt('{')
            if result_decl:
                prnt(result_decl)
            call_arguments = ', '.join(call_arguments)
            prnt('  { %s%s(%s); }' % (result_code, name, call_arguments))
            if result_decl:
                prnt('  return result;')
            prnt('}')
        else:
            prnt('#  define _cffi_f_%s _cffi_d_%s' % (name, name))
        #
        prnt('#endif')        # ------------------------------
        prnt()

    def _generate_cpy_function_ctx(self, tp, name):
        if tp.ellipsis and not self.target_is_python:
            self._generate_cpy_constant_ctx(tp, name)
            return
        type_index = self._typesdict[tp.as_raw_function()]
        numargs = len(tp.args)
        if self.target_is_python:
            meth_kind = OP_DLOPEN_FUNC
        elif numargs == 0:
            meth_kind = OP_CPYTHON_BLTN_N   # 'METH_NOARGS'
        elif numargs == 1:
            meth_kind = OP_CPYTHON_BLTN_O   # 'METH_O'
        else:
            meth_kind = OP_CPYTHON_BLTN_V   # 'METH_VARARGS'
        self._lsts["global"].append(
            GlobalExpr(name, '_cffi_f_%s' % name,
                       CffiOp(meth_kind, type_index),
                       size='_cffi_d_%s' % name))

    # ----------
    # named structs or unions

    def _field_type(self, tp_struct, field_name, tp_field):
        if isinstance(tp_field, model.ArrayType) and tp_field.length == '...':
            ptr_struct_name = tp_struct.get_c_name('*')
            actual_length = '_cffi_array_len(((%s)0)->%s)' % (
                ptr_struct_name, field_name)
            tp_item = self._field_type(tp_struct, '%s[0]' % field_name,
                                       tp_field.item)
            tp_field = model.ArrayType(tp_item, actual_length)
        return tp_field

    def _struct_collecttype(self, tp):
        self._do_collect_type(tp)

    def _struct_decl(self, tp, cname, approxname):
        if tp.fldtypes is None:
            return
        prnt = self._prnt
        checkfuncname = '_cffi_checkfld_%s' % (approxname,)
        prnt('_CFFI_UNUSED_FN')
        prnt('static void %s(%s *p)' % (checkfuncname, cname))
        prnt('{')
        prnt('  /* only to generate compile-time warnings or errors */')
        prnt('  (void)p;')
        for fname, ftype, fbitsize in tp.enumfields():
            try:
                if ftype.is_integer_type() or fbitsize >= 0:
                    # accept all integers, but complain on float or double
                    prnt('  (void)((p->%s) << 1);' % fname)
                    continue
                # only accept exactly the type declared, except that '[]'
                # is interpreted as a '*' and so will match any array length.
                # (It would also match '*', but that's harder to detect...)
                while (isinstance(ftype, model.ArrayType)
                       and (ftype.length is None or ftype.length == '...')):
                    ftype = ftype.item
                    fname = fname + '[0]'
                prnt('  { %s = &p->%s; (void)tmp; }' % (
                    ftype.get_c_name('*tmp', 'field %r'%fname), fname))
            except ffiplatform.VerificationError as e:
                prnt('  /* %s */' % str(e))   # cannot verify it, ignore
        prnt('}')
        prnt('struct _cffi_align_%s { char x; %s y; };' % (approxname, cname))
        prnt()

    def _struct_ctx(self, tp, cname, approxname, named_ptr=None):
        type_index = self._typesdict[tp]
        reason_for_not_expanding = None
        flags = []
        if isinstance(tp, model.UnionType):
            flags.append("_CFFI_F_UNION")
        if tp.fldtypes is None:
            flags.append("_CFFI_F_OPAQUE")
            reason_for_not_expanding = "opaque"
        if (tp not in self.ffi._parser._included_declarations and
                (named_ptr is None or
                 named_ptr not in self.ffi._parser._included_declarations)):
            if tp.fldtypes is None:
                pass    # opaque
            elif tp.partial or tp.has_anonymous_struct_fields():
                pass    # field layout obtained silently from the C compiler
            else:
                flags.append("_CFFI_F_CHECK_FIELDS")
            if tp.packed:
                flags.append("_CFFI_F_PACKED")
        else:
            flags.append("_CFFI_F_EXTERNAL")
            reason_for_not_expanding = "external"
        flags = '|'.join(flags) or '0'
        c_fields = []
        if reason_for_not_expanding is None:
            enumfields = list(tp.enumfields())
            for fldname, fldtype, fbitsize in enumfields:
                fldtype = self._field_type(tp, fldname, fldtype)
                # cname is None for _add_missing_struct_unions() only
                op = OP_NOOP
                if fbitsize >= 0:
                    op = OP_BITFIELD
                    size = '%d /* bits */' % fbitsize
                elif cname is None or (
                        isinstance(fldtype, model.ArrayType) and
                        fldtype.length is None):
                    size = '(size_t)-1'
                else:
                    size = 'sizeof(((%s)0)->%s)' % (
                        tp.get_c_name('*') if named_ptr is None
                                           else named_ptr.name,
                        fldname)
                if cname is None or fbitsize >= 0:
                    offset = '(size_t)-1'
                elif named_ptr is not None:
                    offset = '((char *)&((%s)0)->%s) - (char *)0' % (
                        named_ptr.name, fldname)
                else:
                    offset = 'offsetof(%s, %s)' % (tp.get_c_name(''), fldname)
                c_fields.append(
                    FieldExpr(fldname, offset, size, fbitsize,
                              CffiOp(op, self._typesdict[fldtype])))
            first_field_index = len(self._lsts["field"])
            self._lsts["field"].extend(c_fields)
            #
            if cname is None:  # unknown name, for _add_missing_struct_unions
                size = '(size_t)-2'
                align = -2
                comment = "unnamed"
            else:
                if named_ptr is not None:
                    size = 'sizeof(*(%s)0)' % (named_ptr.name,)
                    align = '-1 /* unknown alignment */'
                else:
                    size = 'sizeof(%s)' % (cname,)
                    align = 'offsetof(struct _cffi_align_%s, y)' % (approxname,)
                comment = None
        else:
            size = '(size_t)-1'
            align = -1
            first_field_index = -1
            comment = reason_for_not_expanding
        self._lsts["struct_union"].append(
            StructUnionExpr(tp.name, type_index, flags, size, align, comment,
                            first_field_index, c_fields))
        self._seen_struct_unions.add(tp)

    def _add_missing_struct_unions(self):
        # not very nice, but some struct declarations might be missing
        # because they don't have any known C name.  Check that they are
        # not partial (we can't complete or verify them!) and emit them
        # anonymously.
        for tp in list(self._struct_unions):
            if tp not in self._seen_struct_unions:
                if tp.partial:
                    raise NotImplementedError("internal inconsistency: %r is "
                                              "partial but was not seen at "
                                              "this point" % (tp,))
                if tp.name.startswith('$') and tp.name[1:].isdigit():
                    approxname = tp.name[1:]
                elif tp.name == '_IO_FILE' and tp.forcename == 'FILE':
                    approxname = 'FILE'
                    self._typedef_ctx(tp, 'FILE')
                else:
                    raise NotImplementedError("internal inconsistency: %r" %
                                              (tp,))
                self._struct_ctx(tp, None, approxname)

    def _generate_cpy_struct_collecttype(self, tp, name):
        self._struct_collecttype(tp)
    _generate_cpy_union_collecttype = _generate_cpy_struct_collecttype

    def _struct_names(self, tp):
        cname = tp.get_c_name('')
        if ' ' in cname:
            return cname, cname.replace(' ', '_')
        else:
            return cname, '_' + cname

    def _generate_cpy_struct_decl(self, tp, name):
        self._struct_decl(tp, *self._struct_names(tp))
    _generate_cpy_union_decl = _generate_cpy_struct_decl

    def _generate_cpy_struct_ctx(self, tp, name):
        self._struct_ctx(tp, *self._struct_names(tp))
    _generate_cpy_union_ctx = _generate_cpy_struct_ctx

    # ----------
    # 'anonymous' declarations.  These are produced for anonymous structs
    # or unions; the 'name' is obtained by a typedef.

    def _generate_cpy_anonymous_collecttype(self, tp, name):
        if isinstance(tp, model.EnumType):
            self._generate_cpy_enum_collecttype(tp, name)
        else:
            self._struct_collecttype(tp)

    def _generate_cpy_anonymous_decl(self, tp, name):
        if isinstance(tp, model.EnumType):
            self._generate_cpy_enum_decl(tp)
        else:
            self._struct_decl(tp, name, 'typedef_' + name)

    def _generate_cpy_anonymous_ctx(self, tp, name):
        if isinstance(tp, model.EnumType):
            self._enum_ctx(tp, name)
        else:
            self._struct_ctx(tp, name, 'typedef_' + name)

    # ----------
    # constants, declared with "static const ..."

    def _generate_cpy_const(self, is_int, name, tp=None, category='const',
                            check_value=None):
        if (category, name) in self._seen_constants:
            raise ffiplatform.VerificationError(
                "duplicate declaration of %s '%s'" % (category, name))
        self._seen_constants.add((category, name))
        #
        prnt = self._prnt
        funcname = '_cffi_%s_%s' % (category, name)
        if is_int:
            prnt('static int %s(unsigned long long *o)' % funcname)
            prnt('{')
            prnt('  int n = (%s) <= 0;' % (name,))
            prnt('  *o = (unsigned long long)((%s) << 0);'
                 '  /* check that we get an integer */' % (name,))
            if check_value is not None:
                if check_value > 0:
                    check_value = '%dU' % (check_value,)
                prnt('  if (!_cffi_check_int(*o, n, %s))' % (check_value,))
                prnt('    n |= 2;')
            prnt('  return n;')
            prnt('}')
        else:
            assert check_value is None
            prnt('static void %s(char *o)' % funcname)
            prnt('{')
            prnt('  *(%s)o = %s;' % (tp.get_c_name('*'), name))
            prnt('}')
        prnt()

    def _generate_cpy_constant_collecttype(self, tp, name):
        is_int = tp.is_integer_type()
        if not is_int or self.target_is_python:
            self._do_collect_type(tp)

    def _generate_cpy_constant_decl(self, tp, name):
        is_int = tp.is_integer_type()
        self._generate_cpy_const(is_int, name, tp)

    def _generate_cpy_constant_ctx(self, tp, name):
        if not self.target_is_python and tp.is_integer_type():
            type_op = CffiOp(OP_CONSTANT_INT, -1)
        else:
            if not tp.sizeof_enabled():
                raise ffiplatform.VerificationError(
                    "constant '%s' is of type '%s', whose size is not known"
                    % (name, tp._get_c_name()))
            if self.target_is_python:
                const_kind = OP_DLOPEN_CONST
            else:
                const_kind = OP_CONSTANT
            type_index = self._typesdict[tp]
            type_op = CffiOp(const_kind, type_index)
        self._lsts["global"].append(
            GlobalExpr(name, '_cffi_const_%s' % name, type_op))

    # ----------
    # enums

    def _generate_cpy_enum_collecttype(self, tp, name):
        self._do_collect_type(tp)

    def _generate_cpy_enum_decl(self, tp, name=None):
        for enumerator in tp.enumerators:
            self._generate_cpy_const(True, enumerator)

    def _enum_ctx(self, tp, cname):
        type_index = self._typesdict[tp]
        type_op = CffiOp(OP_ENUM, -1)
        for enumerator, enumvalue in zip(tp.enumerators, tp.enumvalues):
            self._lsts["global"].append(
                GlobalExpr(enumerator, '_cffi_const_%s' % enumerator, type_op,
                           check_value=enumvalue))
        #
        if cname is not None and '$' not in cname and not self.target_is_python:
            size = "sizeof(%s)" % cname
            signed = "((%s)-1) <= 0" % cname
        else:
            basetp = tp.build_baseinttype(self.ffi, [])
            size = self.ffi.sizeof(basetp)
            signed = int(int(self.ffi.cast(basetp, -1)) < 0)
        allenums = ",".join(tp.enumerators)
        self._lsts["enum"].append(
            EnumExpr(tp.name, type_index, size, signed, allenums))

    def _generate_cpy_enum_ctx(self, tp, name):
        self._enum_ctx(tp, tp._get_c_name())

    # ----------
    # macros: for now only for integers

    def _generate_cpy_macro_collecttype(self, tp, name):
        pass

    def _generate_cpy_macro_decl(self, tp, name):
        if tp == '...':
            check_value = None
        else:
            check_value = tp     # an integer
        self._generate_cpy_const(True, name, check_value=check_value)

    def _generate_cpy_macro_ctx(self, tp, name):
        if tp == '...':
            if self.target_is_python:
                raise ffiplatform.VerificationError(
                    "cannot use the syntax '...' in '#define %s ...' when "
                    "using the ABI mode" % (name,))
            check_value = None
        else:
            check_value = tp     # an integer
        type_op = CffiOp(OP_CONSTANT_INT, -1)
        self._lsts["global"].append(
            GlobalExpr(name, '_cffi_const_%s' % name, type_op,
                       check_value=check_value))

    # ----------
    # global variables

    def _global_type(self, tp, global_name):
        if isinstance(tp, model.ArrayType) and tp.length == '...':
            actual_length = '_cffi_array_len(%s)' % (global_name,)
            tp_item = self._global_type(tp.item, '%s[0]' % global_name)
            tp = model.ArrayType(tp_item, actual_length)
        return tp

    def _generate_cpy_variable_collecttype(self, tp, name):
        self._do_collect_type(self._global_type(tp, name))

    def _generate_cpy_variable_decl(self, tp, name):
        pass

    def _generate_cpy_variable_ctx(self, tp, name):
        tp = self._global_type(tp, name)
        type_index = self._typesdict[tp]
        type_op = CffiOp(OP_GLOBAL_VAR, type_index)
        if tp.sizeof_enabled():
            size = "sizeof(%s)" % (name,)
        else:
            size = 0
        self._lsts["global"].append(
            GlobalExpr(name, '&%s' % name, type_op, size))

    # ----------
    # emitting the opcodes for individual types

    def _emit_bytecode_VoidType(self, tp, index):
        self.cffi_types[index] = CffiOp(OP_PRIMITIVE, PRIM_VOID)

    def _emit_bytecode_PrimitiveType(self, tp, index):
        prim_index = PRIMITIVE_TO_INDEX[tp.name]
        self.cffi_types[index] = CffiOp(OP_PRIMITIVE, prim_index)

    def _emit_bytecode_UnknownIntegerType(self, tp, index):
        s = '_cffi_prim_int(sizeof(%s), (((%s)-1) << 0) <= 0)' % (
            tp.name, tp.name)
        self.cffi_types[index] = CffiOp(OP_PRIMITIVE, s)

    def _emit_bytecode_RawFunctionType(self, tp, index):
        self.cffi_types[index] = CffiOp(OP_FUNCTION, self._typesdict[tp.result])
        index += 1
        for tp1 in tp.args:
            realindex = self._typesdict[tp1]
            if index != realindex:
                if isinstance(tp1, model.PrimitiveType):
                    self._emit_bytecode_PrimitiveType(tp1, index)
                else:
                    self.cffi_types[index] = CffiOp(OP_NOOP, realindex)
            index += 1
        self.cffi_types[index] = CffiOp(OP_FUNCTION_END, int(tp.ellipsis))

    def _emit_bytecode_PointerType(self, tp, index):
        self.cffi_types[index] = CffiOp(OP_POINTER, self._typesdict[tp.totype])

    _emit_bytecode_ConstPointerType = _emit_bytecode_PointerType
    _emit_bytecode_NamedPointerType = _emit_bytecode_PointerType

    def _emit_bytecode_FunctionPtrType(self, tp, index):
        raw = tp.as_raw_function()
        self.cffi_types[index] = CffiOp(OP_POINTER, self._typesdict[raw])

    def _emit_bytecode_ArrayType(self, tp, index):
        item_index = self._typesdict[tp.item]
        if tp.length is None:
            self.cffi_types[index] = CffiOp(OP_OPEN_ARRAY, item_index)
        elif tp.length == '...':
            raise ffiplatform.VerificationError(
                "type %s badly placed: the '...' array length can only be "
                "used on global arrays or on fields of structures" % (
                    str(tp).replace('/*...*/', '...'),))
        else:
            assert self.cffi_types[index + 1] == 'LEN'
            self.cffi_types[index] = CffiOp(OP_ARRAY, item_index)
            self.cffi_types[index + 1] = CffiOp(None, str(tp.length))

    def _emit_bytecode_StructType(self, tp, index):
        struct_index = self._struct_unions[tp]
        self.cffi_types[index] = CffiOp(OP_STRUCT_UNION, struct_index)
    _emit_bytecode_UnionType = _emit_bytecode_StructType

    def _emit_bytecode_EnumType(self, tp, index):
        enum_index = self._enums[tp]
        self.cffi_types[index] = CffiOp(OP_ENUM, enum_index)


if sys.version_info >= (3,):
    NativeIO = io.StringIO
else:
    class NativeIO(io.BytesIO):
        def write(self, s):
            if isinstance(s, unicode):
                s = s.encode('ascii')
            super(NativeIO, self).write(s)

def _make_c_or_py_source(ffi, module_name, preamble, target_file):
    recompiler = Recompiler(ffi, module_name,
                            target_is_python=(preamble is None))
    recompiler.collect_type_table()
    recompiler.collect_step_tables()
    f = NativeIO()
    recompiler.write_source_to_f(f, preamble)
    output = f.getvalue()
    try:
        with open(target_file, 'r') as f1:
            if f1.read(len(output) + 1) != output:
                raise IOError
        return False     # already up-to-date
    except IOError:
        tmp_file = '%s.~%d' % (target_file, os.getpid())
        with open(tmp_file, 'w') as f1:
            f1.write(output)
        try:
            os.rename(tmp_file, target_file)
        except OSError:
            os.unlink(target_file)
            os.rename(tmp_file, target_file)
        return True

def make_c_source(ffi, module_name, preamble, target_c_file):
    assert preamble is not None
    return _make_c_or_py_source(ffi, module_name, preamble, target_c_file)

def make_py_source(ffi, module_name, target_py_file):
    return _make_c_or_py_source(ffi, module_name, None, target_py_file)

def _modname_to_file(outputdir, modname, extension):
    parts = modname.split('.')
    try:
        os.makedirs(os.path.join(outputdir, *parts[:-1]))
    except OSError:
        pass
    parts[-1] += extension
    return os.path.join(outputdir, *parts), parts

def recompile(ffi, module_name, preamble, tmpdir='.', call_c_compiler=True,
              c_file=None, source_extension='.c', extradir=None, **kwds):
    if not isinstance(module_name, str):
        module_name = module_name.encode('ascii')
    if ffi._windows_unicode:
        ffi._apply_windows_unicode(kwds)
    if preamble is not None:
        if c_file is None:
            c_file, parts = _modname_to_file(tmpdir, module_name,
                                             source_extension)
            if extradir:
                parts = [extradir] + parts
            ext_c_file = os.path.join(*parts)
        else:
            ext_c_file = c_file
        ext = ffiplatform.get_extension(ext_c_file, module_name, **kwds)
        updated = make_c_source(ffi, module_name, preamble, c_file)
        if call_c_compiler:
            cwd = os.getcwd()
            try:
                os.chdir(tmpdir)
                outputfilename = ffiplatform.compile('.', ext)
            finally:
                os.chdir(cwd)
            return outputfilename
        else:
            return ext, updated
    else:
        if c_file is None:
            c_file, _ = _modname_to_file(tmpdir, module_name, '.py')
        updated = make_py_source(ffi, module_name, c_file)
        if call_c_compiler:
            return c_file
        else:
            return None, updated

def _verify(ffi, module_name, preamble, *args, **kwds):
    # FOR TESTS ONLY
    from testing.udir import udir
    import imp
    assert module_name not in sys.modules, "module name conflict: %r" % (
        module_name,)
    kwds.setdefault('tmpdir', str(udir))
    outputfilename = recompile(ffi, module_name, preamble, *args, **kwds)
    module = imp.load_dynamic(module_name, outputfilename)
    #
    # hack hack hack: copy all *bound methods* from module.ffi back to the
    # ffi instance.  Then calls like ffi.new() will invoke module.ffi.new().
    for name in dir(module.ffi):
        if not name.startswith('_'):
            attr = getattr(module.ffi, name)
            if attr is not getattr(ffi, name, object()):
                setattr(ffi, name, attr)
    def typeof_disabled(*args, **kwds):
        raise NotImplementedError
    ffi._typeof = typeof_disabled
    return module.lib

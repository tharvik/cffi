import sys, os, hashlib, imp, shutil
from . import model, ffiplatform
from . import __version__


_TMPDIR = '__pycache__'

def set_tmpdir(dirname):
    """Set the temporary directory to use instead of __pycache__."""
    global _TMPDIR
    _TMPDIR = dirname

def cleanup_tmpdir(keep_so=False):
    """Clean up the temporary directory by removing all files in it
    called `_cffi_*.{c,so}` as well as the `build` subdirectory."""
    try:
        filelist = os.listdir(_TMPDIR)
    except OSError:
        return
    if keep_so:
        suffix = '.c'   # only remove .c files
    else:
        suffix = _get_so_suffix().lower()
    for fn in filelist:
        if fn.lower().startswith('_cffi_') and (
                fn.lower().endswith(suffix) or fn.lower().endswith('.c')):
            try:
                os.unlink(os.path.join(_TMPDIR, fn))
            except OSError:
                pass
    shutil.rmtree(os.path.join(_TMPDIR, 'build'), ignore_errors=True)

def _get_so_suffix():
    for suffix, mode, type in imp.get_suffixes():
        if type == imp.C_EXTENSION:
            return suffix
    raise ffiplatform.VerificationError("no C_EXTENSION available")

def _ensure_dir(filename):
    try:
        os.makedirs(os.path.dirname(filename))
    except OSError:
        pass

# ____________________________________________________________

class Verifier(object):
    _status = '?'

    def __init__(self, ffi, preamble, **kwds):
        import _cffi_backend
        if ffi._backend is not _cffi_backend:
            raise NotImplementedError(
                "verify() is only available for the _cffi_backend")
        #
        self.ffi = ffi
        self.preamble = preamble
        self.kwds = kwds
        #
        m = hashlib.md5('\x00'.join([sys.version[:3], __version__, preamble] +
                                    ffi._cdefsources))
        modulename = '_cffi_%s' % m.hexdigest()
        suffix = _get_so_suffix()
        self.sourcefilename = os.path.join(_TMPDIR, modulename + '.c')
        self.modulefilename = os.path.join(_TMPDIR, modulename + suffix)
        self._status = 'init'

    def write_source(self, file=None):
        """Write the C source code.  It is produced in 'self.sourcefilename',
        which can be tweaked beforehand."""
        if self._status == 'init':
            self._write_source(file)
        else:
            raise ffiplatform.VerificationError("source code already written")

    def compile_module(self):
        """Write the C source code (if not done already) and compile it.
        This produces a dynamic link library in 'self.modulefilename'."""
        if self._status == 'init':
            self._write_source()
        if self._status == 'source':
            self._compile_module()
        else:
            raise ffiplatform.VerificationError("module already compiled")

    def load_library(self):
        """Get a C module from this Verifier instance.
        Returns an instance of a FFILibrary class that behaves like the
        objects returned by ffi.dlopen(), but that delegates all
        operations to the C module.  If necessary, the C code is written
        and compiled first.
        """
        if self._status == 'init':       # source code not written yet
            self._locate_module()
        if self._status == 'init':
            self._write_source()
        if self._status == 'source':
            self._compile_module()
        assert self._status == 'module'
        return self._load_library()

    def get_module_name(self):
        return os.path.splitext(os.path.basename(self.modulefilename))[0]

    def get_extension(self):
        if self._status == 'init':
            self._write_source()
        sourcename = os.path.abspath(self.sourcefilename)
        modname = self.get_module_name()
        return ffiplatform.get_extension(sourcename, modname, **self.kwds)

    # ----------

    def _locate_module(self):
        if not os.path.isfile(self.modulefilename):
            try:
                f, filename, descr = imp.find_module(self.get_module_name())
            except ImportError:
                return
            if f is not None:
                f.close()
            self.modulefilename = filename
        self._collect_types()
        self._status = 'module'

    def _prnt(self, what=''):
        print >> self._f, what

    def _gettypenum(self, type):
        # a KeyError here is a bug.  please report it! :-)
        return self._typesdict[type]

    def _collect_types(self):
        self._typesdict = {}
        self._need_size = []
        self._generate("collecttype")

    def _do_collect_type(self, tp):
        if (not isinstance(tp, model.PrimitiveType) and
                tp not in self._typesdict):
            num = len(self._typesdict)
            self._typesdict[tp] = num
            if isinstance(tp, model.StructOrUnion):
                self._need_size.append(tp)

    def _write_source(self, file=None):
        must_close = (file is None)
        if must_close:
            _ensure_dir(self.sourcefilename)
            file = open(self.sourcefilename, 'w')
        self._f = file
        try:
            self._write_source_to_f()
        finally:
            del self._f
            if must_close:
                file.close()
        self._status = 'source'

    def _write_source_to_f(self):
        self._collect_types()
        #
        # The new module will have a _cffi_setup() function that receives
        # objects from the ffi world, and that calls some setup code in
        # the module.  This setup code is split in several independent
        # functions, e.g. one per constant.  The functions are "chained"
        # by ending in a tail call to each other.
        #
        # This is further split in two chained lists, depending on if we
        # can do it at import-time or if we must wait for _cffi_setup() to
        # provide us with the <ctype> objects.  This is needed because we
        # need the values of the enum constants in order to build the
        # <ctype 'enum'> that we may have to pass to _cffi_setup().
        #
        # The following two 'chained_list_constants' items contains
        # the head of these two chained lists, as a string that gives the
        # call to do, if any.
        self._chained_list_constants = ['0', '0']
        #
        prnt = self._prnt
        # first paste some standard set of lines that are mostly '#define'
        prnt(cffimod_header)
        prnt()
        # then paste the C source given by the user, verbatim.
        prnt(self.preamble)
        prnt()
        #
        # call generate_cpy_xxx_decl(), for every xxx found from
        # ffi._parser._declarations.  This generates all the functions.
        self._generate("decl")
        #
        # implement the function _cffi_setup_custom() as calling the
        # head of the chained list.
        self._generate_setup_custom()
        prnt()
        #
        # produce the method table, including the entries for the
        # generated Python->C function wrappers, which are done
        # by generate_cpy_function_method().
        prnt('static PyMethodDef _cffi_methods[] = {')
        self._generate("method")
        prnt('  {"_cffi_setup", _cffi_setup, METH_VARARGS},')
        prnt('  {NULL, NULL}    /* Sentinel */')
        prnt('};')
        prnt()
        #
        # standard init.
        modname = self.get_module_name()
        prnt('PyMODINIT_FUNC')
        prnt('init%s(void)' % modname)
        prnt('{')
        prnt('  PyObject *lib;')
        prnt('  lib = Py_InitModule("%s", _cffi_methods);' % modname)
        prnt('  if (lib == NULL || %s < 0)' % (
            self._chained_list_constants[False],))
        prnt('    return;')
        prnt('  _cffi_init();')
        prnt('}')

    def _compile_module(self):
        # compile this C source
        tmpdir = os.path.dirname(self.sourcefilename)
        outputfilename = ffiplatform.compile(tmpdir, self.get_extension())
        try:
            same = os.path.samefile(outputfilename, self.modulefilename)
        except OSError:
            same = False
        if not same:
            _ensure_dir(self.modulefilename)
            shutil.move(outputfilename, self.modulefilename)
        self._status = 'module'

    def _load_library(self):
        # XXX review all usages of 'self' here!
        # import it as a new extension module
        try:
            module = imp.load_dynamic(self.get_module_name(),
                                      self.modulefilename)
        except ImportError, e:
            error = "importing %r: %s" % (self.modulefilename, e)
            raise ffiplatform.VerificationError(error)
        #
        # call loading_cpy_struct() to get the struct layout inferred by
        # the C compiler
        self._load(module, 'loading')
        #
        # the C code will need the <ctype> objects.  Collect them in
        # order in a list.
        revmapping = dict([(value, key)
                           for (key, value) in self._typesdict.items()])
        lst = [revmapping[i] for i in range(len(revmapping))]
        lst = map(self.ffi._get_cached_btype, lst)
        #
        # build the FFILibrary class and instance and call _cffi_setup().
        # this will set up some fields like '_cffi_types', and only then
        # it will invoke the chained list of functions that will really
        # build (notably) the constant objects, as <cdata> if they are
        # pointers, and store them as attributes on the 'library' object.
        class FFILibrary(object):
            pass
        library = FFILibrary()
        sz = module._cffi_setup(lst, ffiplatform.VerificationError, library)
        #
        # adjust the size of some structs based on what 'sz' returns
        if self._need_size:
            assert len(sz) == 2 * len(self._need_size)
            for i, tp in enumerate(self._need_size):
                size, alignment = sz[i*2], sz[i*2+1]
                BType = self.ffi._get_cached_btype(tp)
                if tp.fldtypes is None:
                    # an opaque struct: give it now a size and alignment
                    self.ffi._backend.complete_struct_or_union(BType, [], None,
                                                               size, alignment)
                else:
                    assert size == self.ffi.sizeof(BType)
                    assert alignment == self.ffi.alignof(BType)
        #
        # finally, call the loaded_cpy_xxx() functions.  This will perform
        # the final adjustments, like copying the Python->C wrapper
        # functions from the module to the 'library' object, and setting
        # up the FFILibrary class with properties for the global C variables.
        self._load(module, 'loaded', library=library)
        return library

    def _generate(self, step_name):
        for name, tp in self.ffi._parser._declarations.iteritems():
            kind, realname = name.split(' ', 1)
            try:
                method = getattr(self, '_generate_cpy_%s_%s' % (kind,
                                                                step_name))
            except AttributeError:
                raise ffiplatform.VerificationError(
                    "not implemented in verify(): %r" % name)
            method(tp, realname)

    def _load(self, module, step_name, **kwds):
        for name, tp in self.ffi._parser._declarations.iteritems():
            kind, realname = name.split(' ', 1)
            method = getattr(self, '_%s_cpy_%s' % (step_name, kind))
            method(tp, realname, module, **kwds)

    def _generate_nothing(self, tp, name):
        pass

    def _loaded_noop(self, tp, name, module, **kwds):
        pass

    # ----------

    def _convert_funcarg_to_c(self, tp, fromvar, tovar, errcode):
        extraarg = ''
        if isinstance(tp, model.PrimitiveType):
            converter = '_cffi_to_c_%s' % (tp.name.replace(' ', '_'),)
            errvalue = '-1'
        #
        elif isinstance(tp, model.PointerType):
            if (isinstance(tp.totype, model.PrimitiveType) and
                    tp.totype.name == 'char'):
                converter = '_cffi_to_c_char_p'
            else:
                converter = '(%s)_cffi_to_c_pointer' % tp.get_c_name('')
                extraarg = ', _cffi_type(%d)' % self._gettypenum(tp)
            errvalue = 'NULL'
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

    def _convert_expr_from_c(self, tp, var):
        if isinstance(tp, model.PrimitiveType):
            return '_cffi_from_c_%s(%s)' % (tp.name.replace(' ', '_'), var)
        elif isinstance(tp, (model.PointerType, model.FunctionPtrType)):
            return '_cffi_from_c_pointer((char *)%s, _cffi_type(%d))' % (
                var, self._gettypenum(tp))
        elif isinstance(tp, model.ArrayType):
            return '_cffi_from_c_deref((char *)%s, _cffi_type(%d))' % (
                var, self._gettypenum(tp))
        elif isinstance(tp, model.StructType):
            return '_cffi_from_c_struct((char *)&%s, _cffi_type(%d))' % (
                var, self._gettypenum(tp))
        elif isinstance(tp, model.EnumType):
            return '_cffi_from_c_deref((char *)&%s, _cffi_type(%d))' % (
                var, self._gettypenum(tp))
        else:
            raise NotImplementedError(tp)

    # ----------
    # typedefs: generates no code so far

    _generate_cpy_typedef_collecttype = _generate_nothing
    _generate_cpy_typedef_decl   = _generate_nothing
    _generate_cpy_typedef_method = _generate_nothing
    _loading_cpy_typedef         = _loaded_noop
    _loaded_cpy_typedef          = _loaded_noop

    # ----------
    # function declarations

    def _generate_cpy_function_collecttype(self, tp, name):
        assert isinstance(tp, model.FunctionPtrType)
        if tp.ellipsis:
            self._do_collect_type(tp)
        else:
            for type in tp.args:
                self._do_collect_type(type)
            self._do_collect_type(tp.result)

    def _generate_cpy_function_decl(self, tp, name):
        assert isinstance(tp, model.FunctionPtrType)
        if tp.ellipsis:
            # cannot support vararg functions better than this: check for its
            # exact type (including the fixed arguments), and build it as a
            # constant function pointer (no CPython wrapper)
            self._generate_cpy_const(False, name, tp)
            return
        prnt = self._prnt
        numargs = len(tp.args)
        if numargs == 0:
            argname = 'no_arg'
        elif numargs == 1:
            argname = 'arg0'
        else:
            argname = 'args'
        prnt('static PyObject *')
        prnt('_cffi_f_%s(PyObject *self, PyObject *%s)' % (name, argname))
        prnt('{')
        #
        for i, type in enumerate(tp.args):
            prnt('  %s;' % type.get_c_name(' x%d' % i))
        if not isinstance(tp.result, model.VoidType):
            result_code = 'result = '
            prnt('  %s;' % tp.result.get_c_name(' result'))
        else:
            result_code = ''
        #
        if len(tp.args) > 1:
            rng = range(len(tp.args))
            for i in rng:
                prnt('  PyObject *arg%d;' % i)
            prnt()
            prnt('  if (!PyArg_ParseTuple(args, "%s:%s", %s))' % (
                'O' * numargs, name, ', '.join(['&arg%d' % i for i in rng])))
            prnt('    return NULL;')
        prnt()
        #
        for i, type in enumerate(tp.args):
            self._convert_funcarg_to_c(type, 'arg%d' % i, 'x%d' % i,
                                       'return NULL')
            prnt()
        #
        prnt('  _cffi_restore_errno();')
        prnt('  { %s%s(%s); }' % (
            result_code, name,
            ', '.join(['x%d' % i for i in range(len(tp.args))])))
        prnt('  _cffi_save_errno();')
        prnt()
        #
        if result_code:
            prnt('  return %s;' %
                 self._convert_expr_from_c(tp.result, 'result'))
        else:
            prnt('  Py_INCREF(Py_None);')
            prnt('  return Py_None;')
        prnt('}')
        prnt()

    def _generate_cpy_function_method(self, tp, name):
        if tp.ellipsis:
            return
        numargs = len(tp.args)
        if numargs == 0:
            meth = 'METH_NOARGS'
        elif numargs == 1:
            meth = 'METH_O'
        else:
            meth = 'METH_VARARGS'
        self._prnt('  {"%s", _cffi_f_%s, %s},' % (name, name, meth))

    _loading_cpy_function = _loaded_noop

    def _loaded_cpy_function(self, tp, name, module, library):
        if tp.ellipsis:
            return
        setattr(library, name, getattr(module, name))

    # ----------
    # named structs

    _generate_cpy_struct_collecttype = _generate_nothing

    def _generate_cpy_struct_decl(self, tp, name):
        assert name == tp.name
        self._generate_struct_or_union_decl(tp, 'struct', name)

    def _generate_cpy_struct_method(self, tp, name):
        self._generate_struct_or_union_method(tp, 'struct', name)

    def _loading_cpy_struct(self, tp, name, module):
        self._loading_struct_or_union(tp, 'struct', name, module)

    def _loaded_cpy_struct(self, tp, name, module, **kwds):
        self._loaded_struct_or_union(tp)

    def _generate_struct_or_union_decl(self, tp, prefix, name):
        if tp.fldnames is None:
            return     # nothing to do with opaque structs
        checkfuncname = '_cffi_check_%s_%s' % (prefix, name)
        layoutfuncname = '_cffi_layout_%s_%s' % (prefix, name)
        cname = ('%s %s' % (prefix, name)).strip()
        #
        prnt = self._prnt
        prnt('static void %s(%s *p)' % (checkfuncname, cname))
        prnt('{')
        prnt('  /* only to generate compile-time warnings or errors */')
        for i in range(len(tp.fldnames)):
            fname = tp.fldnames[i]
            ftype = tp.fldtypes[i]
            if (isinstance(ftype, model.PrimitiveType)
                and ftype.is_integer_type()):
                # accept all integers, but complain on float or double
                prnt('  (void)((p->%s) << 1);' % fname)
            else:
                # only accept exactly the type declared.  Note the parentheses
                # around the '*tmp' below.  In most cases they are not needed
                # but don't hurt --- except test_struct_array_field.
                prnt('  { %s = &p->%s; (void)tmp; }' % (
                    ftype.get_c_name('(*tmp)'), fname))
        prnt('}')
        prnt('static PyObject *')
        prnt('%s(PyObject *self, PyObject *noarg)' % (layoutfuncname,))
        prnt('{')
        prnt('  struct _cffi_aligncheck { char x; %s y; };' % cname)
        if tp.partial:
            prnt('  static Py_ssize_t nums[] = {')
            prnt('    sizeof(%s),' % cname)
            prnt('    offsetof(struct _cffi_aligncheck, y),')
            for fname in tp.fldnames:
                prnt('    offsetof(%s, %s),' % (cname, fname))
                prnt('    sizeof(((%s *)0)->%s),' % (cname, fname))
            prnt('    -1')
            prnt('  };')
            prnt('  return _cffi_get_struct_layout(nums);')
        else:
            ffi = self.ffi
            BStruct = ffi._get_cached_btype(tp)
            conditions = [
                'sizeof(%s) != %d' % (cname, ffi.sizeof(BStruct)),
                'offsetof(struct _cffi_aligncheck, y) != %d' % (
                    ffi.alignof(BStruct),)]
            for fname, ftype in zip(tp.fldnames, tp.fldtypes):
                BField = ffi._get_cached_btype(ftype)
                conditions += [
                    'offsetof(%s, %s) != %d' % (
                        cname, fname, ffi.offsetof(BStruct, fname)),
                    'sizeof(((%s *)0)->%s) != %d' % (
                        cname, fname, ffi.sizeof(BField))]
            prnt('  if (%s ||' % conditions[0])
            for i in range(1, len(conditions)-1):
                prnt('      %s ||' % conditions[i])
            prnt('      %s) {' % conditions[-1])
            prnt('    Py_INCREF(Py_False);')
            prnt('    return Py_False;')
            prnt('  }')
            prnt('  else {')
            prnt('    Py_INCREF(Py_True);')
            prnt('    return Py_True;')
            prnt('  }')
        prnt('  /* the next line is not executed, but compiled */')
        prnt('  %s(0);' % (checkfuncname,))
        prnt('}')
        prnt()

    def _generate_struct_or_union_method(self, tp, prefix, name):
        if tp.fldnames is None:
            return     # nothing to do with opaque structs
        layoutfuncname = '_cffi_layout_%s_%s' % (prefix, name)
        self._prnt('  {"%s", %s, METH_NOARGS},' % (layoutfuncname,
                                                   layoutfuncname))

    def _loading_struct_or_union(self, tp, prefix, name, module):
        if tp.fldnames is None:
            return     # nothing to do with opaque structs
        layoutfuncname = '_cffi_layout_%s_%s' % (prefix, name)
        cname = ('%s %s' % (prefix, name)).strip()
        #
        function = getattr(module, layoutfuncname)
        layout = function()
        if layout is False:
            raise ffiplatform.VerificationError(
                "incompatible layout for %s" % cname)
        elif layout is True:
            assert not tp.partial
        else:
            totalsize = layout[0]
            totalalignment = layout[1]
            fieldofs = layout[2::2]
            fieldsize = layout[3::2]
            assert len(fieldofs) == len(fieldsize) == len(tp.fldnames)
            tp.fixedlayout = fieldofs, fieldsize, totalsize, totalalignment

    def _loaded_struct_or_union(self, tp):
        if tp.fldnames is None:
            return     # nothing to do with opaque structs
        self.ffi._get_cached_btype(tp)   # force 'fixedlayout' to be considered

    # ----------
    # 'anonymous' declarations.  These are produced for anonymous structs
    # or unions; the 'name' is obtained by a typedef.

    _generate_cpy_anonymous_collecttype = _generate_nothing

    def _generate_cpy_anonymous_decl(self, tp, name):
        self._generate_struct_or_union_decl(tp, '', name)

    def _generate_cpy_anonymous_method(self, tp, name):
        self._generate_struct_or_union_method(tp, '', name)

    def _loading_cpy_anonymous(self, tp, name, module):
        self._loading_struct_or_union(tp, '', name, module)

    def _loaded_cpy_anonymous(self, tp, name, module, **kwds):
        self._loaded_struct_or_union(tp)

    # ----------
    # constants, likely declared with '#define'

    def _generate_cpy_const(self, is_int, name, tp=None, category='const',
                            vartp=None, delayed=True):
        prnt = self._prnt
        funcname = '_cffi_%s_%s' % (category, name)
        prnt('static int %s(PyObject *lib)' % funcname)
        prnt('{')
        prnt('  PyObject *o;')
        prnt('  int res;')
        if not is_int:
            prnt('  %s;' % (vartp or tp).get_c_name(' i'))
        else:
            assert category == 'const'
        #
        if not is_int:
            if category == 'var':
                realexpr = '&' + name
            else:
                realexpr = name
            prnt('  i = (%s);' % (realexpr,))
            prnt('  o = %s;' % (self._convert_expr_from_c(tp, 'i'),))
            assert delayed
        else:
            prnt('  if (LONG_MIN <= (%s) && (%s) <= LONG_MAX)' % (name, name))
            prnt('    o = PyInt_FromLong((long)(%s));' % (name,))
            prnt('  else if ((%s) <= 0)' % (name,))
            prnt('    o = PyLong_FromLongLong((long long)(%s));' % (name,))
            prnt('  else')
            prnt('    o = PyLong_FromUnsignedLongLong('
                 '(unsigned long long)(%s));' % (name,))
        prnt('  if (o == NULL)')
        prnt('    return -1;')
        prnt('  res = PyObject_SetAttrString(lib, "%s", o);' % name)
        prnt('  Py_DECREF(o);')
        prnt('  if (res < 0)')
        prnt('    return -1;')
        prnt('  return %s;' % self._chained_list_constants[delayed])
        self._chained_list_constants[delayed] = funcname + '(lib)'
        prnt('}')
        prnt()

    def _generate_cpy_constant_collecttype(self, tp, name):
        is_int = isinstance(tp, model.PrimitiveType) and tp.is_integer_type()
        if not is_int:
            self._do_collect_type(tp)

    def _generate_cpy_constant_decl(self, tp, name):
        is_int = isinstance(tp, model.PrimitiveType) and tp.is_integer_type()
        self._generate_cpy_const(is_int, name, tp)

    _generate_cpy_constant_method = _generate_nothing
    _loading_cpy_constant = _loaded_noop
    _loaded_cpy_constant  = _loaded_noop

    # ----------
    # enums

    def _generate_cpy_enum_decl(self, tp, name):
        if tp.partial:
            for enumerator in tp.enumerators:
                self._generate_cpy_const(True, enumerator, delayed=False)
            return
        #
        funcname = '_cffi_enum_%s' % name
        prnt = self._prnt
        prnt('static int %s(PyObject *lib)' % funcname)
        prnt('{')
        for enumerator, enumvalue in zip(tp.enumerators, tp.enumvalues):
            prnt('  if (%s != %d) {' % (enumerator, enumvalue))
            prnt('    PyErr_Format(_cffi_VerificationError,')
            prnt('                 "in enum %s: %s has the real value %d, '
                 'not %d",')
            prnt('                 "%s", "%s", (int)%s, %d);' % (
                name, enumerator, enumerator, enumvalue))
            prnt('    return -1;')
            prnt('  }')
        prnt('  return %s;' % self._chained_list_constants[True])
        self._chained_list_constants[True] = funcname + '(lib)'
        prnt('}')
        prnt()

    _generate_cpy_enum_collecttype = _generate_nothing
    _generate_cpy_enum_method = _generate_nothing
    _loading_cpy_enum = _loaded_noop

    def _loading_cpy_enum(self, tp, name, module):
        if tp.partial:
            enumvalues = [getattr(module, enumerator)
                          for enumerator in tp.enumerators]
            tp.enumvalues = tuple(enumvalues)
            tp.partial = False

    def _loaded_cpy_enum(self, tp, name, module, library):
        for enumerator, enumvalue in zip(tp.enumerators, tp.enumvalues):
            setattr(library, enumerator, enumvalue)

    # ----------
    # macros: for now only for integers

    def _generate_cpy_macro_decl(self, tp, name):
        assert tp == '...'
        self._generate_cpy_const(True, name)

    _generate_cpy_macro_collecttype = _generate_nothing
    _generate_cpy_macro_method = _generate_nothing
    _loading_cpy_macro = _loaded_noop
    _loaded_cpy_macro  = _loaded_noop

    # ----------
    # global variables

    def _generate_cpy_variable_collecttype(self, tp, name):
        if isinstance(tp, model.ArrayType):
            self._do_collect_type(tp)
        else:
            tp_ptr = model.PointerType(tp)
            self._do_collect_type(tp_ptr)

    def _generate_cpy_variable_decl(self, tp, name):
        if isinstance(tp, model.ArrayType):
            tp_ptr = model.PointerType(tp.item)
            self._generate_cpy_const(False, name, tp, vartp=tp_ptr)
        else:
            tp_ptr = model.PointerType(tp)
            self._generate_cpy_const(False, name, tp_ptr, category='var')

    _generate_cpy_variable_method = _generate_nothing
    _loading_cpy_variable = _loaded_noop

    def _loaded_cpy_variable(self, tp, name, module, library):
        if isinstance(tp, model.ArrayType):   # int a[5] is "constant" in the
            return                            # sense that "a=..." is forbidden
        # remove ptr=<cdata 'int *'> from the library instance, and replace
        # it by a property on the class, which reads/writes into ptr[0].
        ptr = getattr(library, name)
        delattr(library, name)
        def getter(library):
            return ptr[0]
        def setter(library, value):
            ptr[0] = value
        setattr(library.__class__, name, property(getter, setter))

    # ----------

    def _generate_setup_custom(self):
        prnt = self._prnt
        prnt('static PyObject *_cffi_setup_custom(PyObject *lib)')
        prnt('{')
        prnt('  if (%s < 0)' % self._chained_list_constants[True])
        prnt('    return NULL;')
        # produce the size of the opaque structures that need it.
        # So far, limited to the structures used as function arguments
        # or results.  (These might not be real structures at all, but
        # instead just some integer handles; but it works anyway)
        if self._need_size:
            N = len(self._need_size)
            prnt('  else {')
            for i, tp in enumerate(self._need_size):
                prnt('    struct _cffi_aligncheck%d { char x; %s; };' % (
                    i, tp.get_c_name(' y')))
            prnt('    static Py_ssize_t content[] = {')
            for i, tp in enumerate(self._need_size):
                prnt('      sizeof(%s),' % tp.get_c_name())
                prnt('      offsetof(struct _cffi_aligncheck%d, y),' % i)
            prnt('    };')
            prnt('    int i;')
            prnt('    PyObject *o, *lst = PyList_New(%d);' % (2*N,))
            prnt('    if (lst == NULL)')
            prnt('      return NULL;')
            prnt('    for (i=0; i<%d; i++) {' % (2*N,))
            prnt('      o = PyInt_FromSsize_t(content[i]);')
            prnt('      if (o == NULL) {')
            prnt('        Py_DECREF(lst);')
            prnt('        return NULL;')
            prnt('      }')
            prnt('      PyList_SET_ITEM(lst, i, o);')
            prnt('    }')
            prnt('    return lst;')
            prnt('  }')
        else:
            prnt('  Py_INCREF(Py_None);')
            prnt('  return Py_None;')
        prnt('}')

cffimod_header = r'''
#include <Python.h>
#include <stddef.h>

#define _cffi_from_c_double PyFloat_FromDouble
#define _cffi_from_c_float PyFloat_FromDouble
#define _cffi_from_c_signed_char PyInt_FromLong
#define _cffi_from_c_short PyInt_FromLong
#define _cffi_from_c_int PyInt_FromLong
#define _cffi_from_c_long PyInt_FromLong
#define _cffi_from_c_unsigned_char PyInt_FromLong
#define _cffi_from_c_unsigned_short PyInt_FromLong
#define _cffi_from_c_unsigned_long PyLong_FromUnsignedLong
#define _cffi_from_c_unsigned_long_long PyLong_FromUnsignedLongLong

#if SIZEOF_INT < SIZEOF_LONG
#  define _cffi_from_c_unsigned_int PyInt_FromLong
#else
#  define _cffi_from_c_unsigned_int PyLong_FromUnsignedLong
#endif

#if SIZEOF_LONG < SIZEOF_LONG_LONG
#  define _cffi_from_c_long_long PyLong_FromLongLong
#else
#  define _cffi_from_c_long_long PyInt_FromLong
#endif

#define _cffi_to_c_long PyInt_AsLong
#define _cffi_to_c_double PyFloat_AsDouble
#define _cffi_to_c_float PyFloat_AsDouble

#define _cffi_to_c_char_p                                                \
                 ((char *(*)(PyObject *))_cffi_exports[0])
#define _cffi_to_c_signed_char                                           \
                 ((signed char(*)(PyObject *))_cffi_exports[1])
#define _cffi_to_c_unsigned_char                                         \
                 ((unsigned char(*)(PyObject *))_cffi_exports[2])
#define _cffi_to_c_short                                                 \
                 ((short(*)(PyObject *))_cffi_exports[3])
#define _cffi_to_c_unsigned_short                                        \
                 ((unsigned short(*)(PyObject *))_cffi_exports[4])

#if SIZEOF_INT < SIZEOF_LONG
#  define _cffi_to_c_int                                                 \
                   ((int(*)(PyObject *))_cffi_exports[5])
#  define _cffi_to_c_unsigned_int                                        \
                   ((unsigned int(*)(PyObject *))_cffi_exports[6])
#else
#  define _cffi_to_c_int          _cffi_to_c_long
#  define _cffi_to_c_unsigned_int _cffi_to_c_unsigned_long
#endif

#define _cffi_to_c_unsigned_long                                         \
                 ((unsigned long(*)(PyObject *))_cffi_exports[7])
#define _cffi_to_c_unsigned_long_long                                    \
                 ((unsigned long long(*)(PyObject *))_cffi_exports[8])
#define _cffi_to_c_char                                                  \
                 ((char(*)(PyObject *))_cffi_exports[9])
#define _cffi_from_c_pointer                                             \
    ((PyObject *(*)(char *, CTypeDescrObject *))_cffi_exports[10])
#define _cffi_to_c_pointer                                               \
    ((char *(*)(PyObject *, CTypeDescrObject *))_cffi_exports[11])
#define _cffi_get_struct_layout                                          \
    ((PyObject *(*)(Py_ssize_t[]))_cffi_exports[12])
#define _cffi_restore_errno                                              \
    ((void(*)(void))_cffi_exports[13])
#define _cffi_save_errno                                                 \
    ((void(*)(void))_cffi_exports[14])
#define _cffi_from_c_char                                                \
    ((PyObject *(*)(char))_cffi_exports[15])
#define _cffi_from_c_deref                                               \
    ((PyObject *(*)(char *, CTypeDescrObject *))_cffi_exports[16])
#define _cffi_to_c                                                       \
    ((int(*)(char *, CTypeDescrObject *, PyObject *))_cffi_exports[17])
#define _cffi_from_c_struct                                              \
    ((PyObject *(*)(char *, CTypeDescrObject *))_cffi_exports[18])
#define _cffi_to_c_wchar_t                                               \
                 ((wchar_t(*)(PyObject *))_cffi_exports[19])
#define _cffi_from_c_wchar_t                                             \
    ((PyObject *(*)(wchar_t))_cffi_exports[20])
#define _CFFI_NUM_EXPORTS 21

#if SIZEOF_LONG < SIZEOF_LONG_LONG
#  define _cffi_to_c_long_long PyLong_AsLongLong
#else
#  define _cffi_to_c_long_long _cffi_to_c_long
#endif

typedef struct _ctypedescr CTypeDescrObject;

static void *_cffi_exports[_CFFI_NUM_EXPORTS];
static PyObject *_cffi_types, *_cffi_VerificationError;

static PyObject *_cffi_setup_custom(PyObject *lib);   /* forward */

static PyObject *_cffi_setup(PyObject *self, PyObject *args)
{
    PyObject *library;
    if (!PyArg_ParseTuple(args, "OOO", &_cffi_types, &_cffi_VerificationError,
                                       &library))
        return NULL;
    Py_INCREF(_cffi_types);
    Py_INCREF(_cffi_VerificationError);
    return _cffi_setup_custom(library);
}

static void _cffi_init(void)
{
    PyObject *module = PyImport_ImportModule("_cffi_backend");
    PyObject *c_api_object;

    if (module == NULL)
        return;

    c_api_object = PyObject_GetAttrString(module, "_C_API");
    if (c_api_object == NULL)
        return;
    if (!PyCObject_Check(c_api_object)) {
        PyErr_SetNone(PyExc_ImportError);
        return;
    }
    memcpy(_cffi_exports, PyCObject_AsVoidPtr(c_api_object),
           _CFFI_NUM_EXPORTS * sizeof(void *));
}

#define _cffi_type(num) ((CTypeDescrObject *)PyList_GET_ITEM(_cffi_types, num))

/**********/
'''

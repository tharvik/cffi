import new

class FFIError(Exception):
    pass

class CDefError(Exception):
    def __str__(self):
        try:
            line = 'line %d: ' % (self.args[1].coord.line,)
        except (AttributeError, TypeError, IndexError):
            line = ''
        return '%s%s' % (line, self.args[0])


class FFI(object):
    r'''
    The main top-level class that you instantiate once, or once per module.

    Example usage:

        ffi = FFI()
        ffi.cdef("""
            int printf(const char *, ...);
        """)

        C = ffi.dlopen(None)   # standard library
        -or-
        C = ffi.verify()  # use a C compiler: verify the decl above is right

        C.printf("hello, %s!\n", ffi.new("char[]", "world"))
    '''

    def __init__(self, backend=None):
        """Create an FFI instance.  The 'backend' argument is used to
        select a non-default backend, mostly for tests.
        """
        from . import cparser
        if backend is None:
            try:
                import _ffi_backend as backend
            except ImportError, e:
                import warnings
                warnings.warn("ImportError: %s\n"
                              "Falling back to the ctypes backend." % (e,))
                from . import backend_ctypes
                backend = backend_ctypes.CTypesBackend()
        self._backend = backend
        self._parser = cparser.Parser()
        self._cached_btypes = {}
        self._parsed_types = new.module('parsed_types').__dict__
        self._new_types = new.module('new_types').__dict__
        if hasattr(backend, 'set_ffi'):
            backend.set_ffi(self)
        #
        lines = []
        by_size = {}
        for cname in ['long long', 'long', 'int', 'short', 'char']:
            by_size[self.sizeof(cname)] = cname
        for name, size in self._backend.nonstandard_integer_types().items():
            if size & 0x1000:   # unsigned
                equiv = 'unsigned %s'
                size &= ~0x1000
            else:
                equiv = 'signed %s'
            lines.append('typedef %s %s;' % (equiv % by_size[size], name))
        self.cdef('\n'.join(lines))
        #
        self.NULL = self.cast("void *", 0)

    def cdef(self, csource):
        """Parse the given C source.  This registers all declared functions,
        types, and global variables.  The functions and global variables can
        then be accessed via either 'ffi.dlopen()' or 'ffi.verify()'.
        The types can be used in 'ffi.new()' and other functions.
        """
        self._parser.parse(csource)

    def dlopen(self, name):
        """Load and return a dynamic library identified by 'name'.
        The standard C library can be loaded by passing None.
        Note that functions and types declared by 'ffi.cdef()' are not
        linked to a particular library, just like C headers; in the
        library we only look for the actual (untyped) symbols.
        """
        assert isinstance(name, str) or name is None
        return _make_ffi_library(self, name)

    def typeof(self, cdecl, consider_function_as_funcptr=False):
        """Parse the C type given as a string and return the
        corresponding Python type: <class 'ffi.CData<...>'>.
        It can also be used on 'cdata' instance to get its C type.
        """
        if isinstance(cdecl, basestring):
            try:
                btype, cfaf = self._parsed_types[cdecl]
                if consider_function_as_funcptr and not cfaf:
                    raise KeyError
            except KeyError:
                cfaf = consider_function_as_funcptr
                type = self._parser.parse_type(cdecl,
                           consider_function_as_funcptr=cfaf)
                btype = self._get_cached_btype(type)
                self._parsed_types[cdecl] = btype, cfaf
            return btype
        else:
            return self._backend.typeof(cdecl)

    def sizeof(self, cdecl):
        """Return the size in bytes of the argument.  It can be a
        string naming a C type, or a 'cdata' instance.
        """
        if isinstance(cdecl, basestring):
            BType = self.typeof(cdecl)
            return self._backend.sizeof(BType)
        else:
            return self._backend.sizeof(cdecl)

    def alignof(self, cdecl):
        """Return the natural alignment size in bytes of the C type
        given as a string.
        """
        if isinstance(cdecl, basestring):
            cdecl = self.typeof(cdecl)
        return self._backend.alignof(cdecl)

    def offsetof(self, cdecl, fieldname):
        """Return the offset of the named field inside the given
        structure, which must be given as a C type name.
        """
        if isinstance(cdecl, basestring):
            cdecl = self.typeof(cdecl)
        return self._backend.offsetof(cdecl, fieldname)

    def new(self, cdecl, init=None):
        """Allocate an instance 'x' of the named C type, and return a
        <cdata 'cdecl *'> object representing '&x'.  Such an object
        behaves like a pointer to the allocated memory.  When the
        <cdata> object goes out of scope, the memory is freed.

        The memory is initialized following the rules of declaring a
        global variable in C: by default it is zero-initialized, but
        an explicit initializer can be given which can be used to
        fill all or part of the memory.

        The returned <cdata> object has ownership of the value of
        type 'cdecl' that it points to.  This means that the raw data
        can be used as long as this object is kept alive, but must
        not be used for a longer time.  Be careful about that when
        copying the pointer to the memory somewhere else, e.g. into
        another structure.
        """
        try:
            BType = self._new_types[cdecl]
        except KeyError:
            type = self._parser.parse_type(cdecl, force_pointer=True)
            BType = self._get_cached_btype(type)
            self._new_types[cdecl] = BType
        #
        return self._backend.newp(BType, init)

    def cast(self, cdecl, source):
        """Similar to a C cast: returns an instance of the named C
        type initialized with the given 'source'.  The source is
        casted between integers or pointers of any type.
        """
        BType = self.typeof(cdecl)
        return self._backend.cast(BType, source)

    def buffer(self, cdata, size=-1):
        """Return a read-write buffer object that references the raw C data
        pointed to by the given 'cdata'.  The 'cdata' must be a pointer or
        an array.  To get a copy of it in a regular string, call str() on
        the result.
        """
        return self._backend.buffer(cdata, size)

    def callback(self, cdecl, python_callable, error=None):
        """Return a callback object.  'cdecl' must name a C function pointer
        type.  The callback invokes the specified 'python_callable'.
        Important: the callback object must be manually kept alive for as
        long as the callback may be invoked from the C level.
        """
        if not callable(python_callable):
            raise TypeError("the 'python_callable' argument is not callable")
        BFunc = self.typeof(cdecl, consider_function_as_funcptr=True)
        return self._backend.callback(BFunc, python_callable, error)

    def getctype(self, cdecl, replace_with=''):
        """Return a string giving the C type 'cdecl', which may be itself
        a string or a <ctype> object.  If 'replace_with' is given, it gives
        extra text to append (or insert for more complicated C types), like
        a variable name, or '*' to get actually the C type 'pointer-to-cdecl'.
        """
        if isinstance(cdecl, basestring):
            cdecl = self.typeof(cdecl)
        replace_with = replace_with.strip()
        if (replace_with.startswith('*')
                and '&[' in self._backend.getcname(cdecl, '&')):
            replace_with = '(%s)' % replace_with
        elif replace_with and not replace_with[0] in '[(':
            replace_with = ' ' + replace_with
        return self._backend.getcname(cdecl, replace_with)

    def _get_cached_btype(self, type):
        try:
            BType = self._cached_btypes[type]
        except KeyError:
            args = type.prepare_backend_type(self)
            if args is None:
                args = ()
            BType = type.finish_backend_type(self, *args)
            self._cached_btypes[type] = BType
        return BType

    def verify(self, source='', **kwargs):
        """Verify that the current ffi signatures compile on this
        machine, and return a dynamic library object.  The dynamic
        library can be used to call functions and access global
        variables declared in this 'ffi'.  The library is compiled
        by the C compiler: it gives you C-level API compatibility
        (including calling macros).  This is unlike 'ffi.dlopen()',
        which requires binary compatibility in the signatures.
        """
        from .verifier import Verifier
        return Verifier(self).verify(source, **kwargs)

    def _get_errno(self):
        return self._backend.get_errno()
    def _set_errno(self, errno):
        self._backend.set_errno(errno)
    errno = property(_get_errno, _set_errno, None,
                     "the value of 'errno' from/to the C calls")

def _make_ffi_library(ffi, libname):
    name = libname
    if name is None:
        name = 'c'    # on Posix only
    if '/' in name:
        path = name
    else:
        import ctypes.util
        path = ctypes.util.find_library(name)
        if path is None:
            raise OSError("library not found: %r" % (name,))
    #
    backend = ffi._backend
    backendlib = backend.load_library(path)
    function_cache = {}
    #
    class FFILibrary(object):
        def __getattribute__(self, name):
            try:
                return function_cache[name]
            except KeyError:
                pass
            #
            key = 'function ' + name
            if key in ffi._parser._declarations:
                tp = ffi._parser._declarations[key]
                BType = ffi._get_cached_btype(tp)
                value = backendlib.load_function(BType, name)
                function_cache[name] = value
                return value
            #
            key = 'variable ' + name
            if key in ffi._parser._declarations:
                tp = ffi._parser._declarations[key]
                BType = ffi._get_cached_btype(tp)
                return backendlib.read_variable(BType, name)
            #
            raise AttributeError(name)

        def __setattr__(self, name, value):
            key = 'variable ' + name
            if key in ffi._parser._declarations:
                tp = ffi._parser._declarations[key]
                BType = ffi._get_cached_btype(tp)
                backendlib.write_variable(BType, name, value)
                return
            #
            raise AttributeError(name)
    #
    if libname is not None:
        FFILibrary.__name__ = 'FFILibrary_%s' % libname
    return FFILibrary()

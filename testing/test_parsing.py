import py, sys, re
from cffi import FFI, FFIError, CDefError, VerificationError

class FakeBackend(object):

    def nonstandard_integer_types(self):
        return {}

    def sizeof(self, name):
        return 1

    def load_library(self, name):
        if sys.platform == 'win32':
            assert "msvcr" in name
        else:
            assert "libc" in name or "libm" in name
        return FakeLibrary()

    def new_function_type(self, args, result, has_varargs):
        args = [arg.cdecl for arg in args]
        result = result.cdecl
        return FakeType(
            '<func (%s), %s, %s>' % (', '.join(args), result, has_varargs))

    def new_primitive_type(self, name):
        assert name == name.lower()
        return FakeType('<%s>' % name)

    def new_pointer_type(self, itemtype):
        return FakeType('<pointer to %s>' % (itemtype,))

    def new_struct_type(self, name):
        return FakeStruct(name)

    def complete_struct_or_union(self, s, fields, tp=None):
        assert isinstance(s, FakeStruct)
        s.fields = fields
    
    def new_array_type(self, ptrtype, length):
        return FakeType('<array %s x %s>' % (ptrtype, length))

    def new_void_type(self):
        return FakeType("<void>")
    def cast(self, x, y):
        return 'casted!'

class FakeType(object):
    def __init__(self, cdecl):
        self.cdecl = cdecl
    def __str__(self):
        return self.cdecl

class FakeStruct(object):
    def __init__(self, name):
        self.name = name
    def __str__(self):
        return ', '.join([str(y) + str(x) for x, y, z in self.fields])

class FakeLibrary(object):
    
    def load_function(self, BType, name):
        return FakeFunction(BType, name)

class FakeFunction(object):

    def __init__(self, BType, name):
        self.BType = str(BType)
        self.name = name


def test_simple():
    ffi = FFI(backend=FakeBackend())
    ffi.cdef("double sin(double x);")
    m = ffi.dlopen("m")
    func = m.sin    # should be a callable on real backends
    assert func.name == 'sin'
    assert func.BType == '<func (<double>), <double>, False>'

def test_pipe():
    ffi = FFI(backend=FakeBackend())
    ffi.cdef("int pipe(int pipefd[2]);")
    C = ffi.dlopen(None)
    func = C.pipe
    assert func.name == 'pipe'
    assert func.BType == '<func (<pointer to <int>>), <int>, False>'

def test_vararg():
    ffi = FFI(backend=FakeBackend())
    ffi.cdef("short foo(int, ...);")
    C = ffi.dlopen(None)
    func = C.foo
    assert func.name == 'foo'
    assert func.BType == '<func (<int>), <short>, True>'

def test_no_args():
    ffi = FFI(backend=FakeBackend())
    ffi.cdef("""
        int foo(void);
        """)
    C = ffi.dlopen(None)
    assert C.foo.BType == '<func (), <int>, False>'

def test_typedef():
    ffi = FFI(backend=FakeBackend())
    ffi.cdef("""
        typedef unsigned int UInt;
        typedef UInt UIntReally;
        UInt foo(void);
        """)
    C = ffi.dlopen(None)
    assert str(ffi.typeof("UIntReally")) == '<unsigned int>'
    assert C.foo.BType == '<func (), <unsigned int>, False>'

def test_typedef_more_complex():
    ffi = FFI(backend=FakeBackend())
    ffi.cdef("""
        typedef struct { int a, b; } foo_t, *foo_p;
        int foo(foo_p[]);
        """)
    C = ffi.dlopen(None)
    assert str(ffi.typeof("foo_t")) == '<int>a, <int>b'
    assert str(ffi.typeof("foo_p")) == '<pointer to <int>a, <int>b>'
    assert C.foo.BType == ('<func (<pointer to <pointer to '
                           '<int>a, <int>b>>), <int>, False>')

def test_typedef_array_convert_array_to_pointer():
    ffi = FFI(backend=FakeBackend())
    ffi.cdef("""
        typedef int (*fn_t)(int[5]);
        """)
    type = ffi._parser.parse_type("fn_t")
    BType = ffi._get_cached_btype(type)
    assert str(BType) == '<func (<pointer to <int>>), <int>, False>'

def test_remove_comments():
    ffi = FFI(backend=FakeBackend())
    ffi.cdef("""
        double /*comment here*/ sin   // blah blah
        /* multi-
           line-
           //comment */  (
        // foo
        double // bar      /* <- ignored, because it's in a comment itself
        x, double/*several*//*comment*/y) /*on the same line*/
        ;
    """)
    m = ffi.dlopen("m")
    func = m.sin
    assert func.name == 'sin'
    assert func.BType == '<func (<double>, <double>), <double>, False>'

def test_define_not_supported_for_now():
    ffi = FFI(backend=FakeBackend())
    e = py.test.raises(CDefError, ffi.cdef, "#define FOO 42")
    assert str(e.value) == \
           'only supports the syntax "#define FOO ..." for now (literally)'

def test_unnamed_struct():
    ffi = FFI(backend=FakeBackend())
    ffi.cdef("typedef struct { int x; } foo_t;\n"
             "typedef struct { int y; } *bar_p;\n")
    assert 'typedef foo_t' in ffi._parser._declarations
    assert 'typedef bar_p' in ffi._parser._declarations
    assert 'anonymous foo_t' in ffi._parser._declarations
    type_foo = ffi._parser.parse_type("foo_t")
    type_bar = ffi._parser.parse_type("bar_p").totype
    assert repr(type_foo) == "<foo_t>"
    assert repr(type_bar) == "<struct $1>"
    py.test.raises(VerificationError, type_bar.get_c_name)
    assert type_foo.get_c_name() == "foo_t"

def test_override():
    ffi = FFI(backend=FakeBackend())
    C = ffi.dlopen(None)
    ffi.cdef("int foo(void);")
    py.test.raises(FFIError, ffi.cdef, "long foo(void);")
    assert C.foo.BType == '<func (), <int>, False>'
    ffi.cdef("long foo(void);", override=True)
    assert C.foo.BType == '<func (), <long>, False>'

def test_cannot_have_only_variadic_part():
    # this checks that we get a sensible error if we try "int foo(...);"
    ffi = FFI()
    e = py.test.raises(CDefError, ffi.cdef, "int foo(...);")
    assert str(e.value) == \
           "foo: a function with only '(...)' as argument is not correct C"

def test_parse_error():
    ffi = FFI()
    e = py.test.raises(CDefError, ffi.cdef, " x y z ")
    assert re.match(r'cannot parse " x y z "\n:\d+:', str(e.value))

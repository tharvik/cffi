import py, sys, re, textwrap
from cffi import FFI, FFIError, CDefError, VerificationError
from cffi.cparser import Parser

class FakeBackend(object):

    def nonstandard_integer_types(self):
        return {}

    def sizeof(self, name):
        return 1

    def load_library(self, name, flags):
        if sys.platform == 'win32':
            assert name is None or "msvcr" in name
        else:
            assert name is None or "libc" in name or "libm" in name
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

    def complete_struct_or_union(self, s, fields, tp=None,
                                 totalsize=-1, totalalignment=-1, sflags=0):
        assert isinstance(s, FakeStruct)
        s.fields = fields

    def new_array_type(self, ptrtype, length):
        return FakeType('<array %s x %s>' % (ptrtype, length))

    def new_void_type(self):
        return FakeType("<void>")
    def cast(self, x, y):
        return 'casted!'
    def _get_types(self):
        return "CData", "CType"

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

lib_m = "m"
if sys.platform == 'win32':
    #there is a small chance this fails on Mingw via environ $CC
    import distutils.ccompiler
    if distutils.ccompiler.get_default_compiler() == 'msvc':
        lib_m = 'msvcrt'

def test_simple():
    ffi = FFI(backend=FakeBackend())
    ffi.cdef("double sin(double x);")
    m = ffi.dlopen(lib_m)
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
    with ffi._lock:
        type = ffi._parser.parse_type("fn_t")
        BType = ffi._get_cached_btype(type)
    assert str(BType) == '<func (<pointer to <int>>), <int>, False>'

def test_extract_ifdefs_err():
    parser = Parser()
    py.test.raises(CDefError, parser._extract_ifdefs, "#if ABC")  # unbalanced
    py.test.raises(CDefError, parser._extract_ifdefs, "#else")    # unexpected
    py.test.raises(CDefError, parser._extract_ifdefs, "#endif")   # unexpected

def test_extract_ifdefs_1():
    parser = Parser()

    _, _, macros = parser._extract_ifdefs("""
    #ifdef FOO
    int q;
    #endif
    #ifndef BAR
    int b;
    #endif
    """)

    assert macros == [
        '',
        None,
        'defined(FOO)',
        None,
        None,
        '!defined(BAR)',
        None,
        ''
    ]

def test_extract_ifdefs_2():
    parser = Parser()

    _, _, macros = parser._extract_ifdefs("""
    #if FOO
    int q;
    #else
    int x;
    #if BAR
    int y;
    #endif
    #endif
    int z;
    """)

    assert macros == [
        '',
        None,
        'FOO',
        None,
        '!(FOO)',
        None,
        '(!(FOO)) && (BAR)',
        None,
        None,
        '',
        ''
    ]

def test_extract_ifdefs_3():
    parser = Parser()

    _, _, macros = parser._extract_ifdefs("""
    #if FOO
    int q;
    #elif BAR
    int x;
    #elif BAZ
    int y;
    #else
    int z;
    #endif
    """)

    assert macros == [
        '',
        None,
        'FOO',
        None,
        '!(FOO) && (BAR)',
        None,
        '!(FOO) && !((BAR)) && (BAZ)',
        None,
        '!(FOO) && !((BAR)) && !((BAZ))',
        None,
        ''
    ]

def test_extract_ifdefs_4():
    parser = Parser()

    _, _, macros = parser._extract_ifdefs("""
    #ifdef ABC
    #ifdef BCD
    int q;
    #elif BAR
    int x;
    #else
    int y;
    #endif
    int z;
    #endif
    """)

    assert macros == [
        '',
        None,
        None,
        '(defined(ABC)) && (defined(BCD))',
        None,
        '(defined(ABC)) && (!(defined(BCD)) && (BAR))',
        None,
        '(defined(ABC)) && (!(defined(BCD)) && !((BAR)))',
        None,
        'defined(ABC)',
        None,
        ''
    ]

def test_extract_ifdefs_continuation():
    parser = Parser()

    clean, _, macros = parser._extract_ifdefs(r"""   // <= note the 'r' here
    #if FOO \
 FO\\O2
    int q;
    #elif BAR\
BAR2
    int x;
    #endif
    """)

    assert macros == [
        '',
        None,
        None,
        r'FOO FO\\O2',
        None,
        None,
        r'!(FOO FO\\O2) && (BARBAR2)',
        None,
        ''
    ]
    assert clean == r"""   // <= note the 'r' here


    int q;


    int x;

    """

def test_clean_ifdefs():
    parser = Parser()
    clean, _, _ = parser._extract_ifdefs("""
    #if FOO
    int q;
    #else
    int x;
    #if BAR
    int y;
    #endif
    #endif
    int z;
    """)

    assert clean == """

    int q;

    int x;

    int y;


    int z;
    """

def test_defines_with_ifdefs():
    parser = Parser()
    _, defines, macros = parser._extract_ifdefs("""
    #if FOO
    #  define ABC 42
    #else
    #  define BCD 4\\
3
    #endif
    """)

    assert macros == [
        '',
        None,
        None,
        None,
        None,
        None,
        None,
        '']
    assert defines == [('FOO', 'ABC', '42'), ('!(FOO)', 'BCD', '43')]

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
    m = ffi.dlopen(lib_m)
    func = m.sin
    assert func.name == 'sin'
    assert func.BType == '<func (<double>, <double>), <double>, False>'

def test_remove_line_continuation_comments():
    ffi = FFI(backend=FakeBackend())
    ffi.cdef("""
        double // blah \\
                  more comments
        x(void);
        double // blah\\\\
        y(void);
        double // blah\\ \
                  etc
        z(void);
    """)
    m = ffi.dlopen(lib_m)
    m.x
    m.y
    m.z

def test_line_continuation_in_defines():
    ffi = FFI(backend=FakeBackend())
    ffi.cdef("""
        #define ABC\\
            42
        #define BCD   \\
            43
        #define CDE  3\\
9
    """)
    m = ffi.dlopen(lib_m)
    assert m.ABC == 42
    assert m.BCD == 43
    assert m.CDE == 39

def test_ifdef_partial_unsupported():
    ffi = FFI(backend=FakeBackend())
    ffi.cdef("""
        int foo(int
        #ifdef ABC
                , long
        #endif
                );
    """)
    should_crash

def test_conditional_typedef_1():
    ffi = FFI(backend=FakeBackend())
    ffi.cdef("""
        #ifdef ABC
        typedef int foo_t;
        #endif
    """)
    case = ffi._parser._declarations['typedef foo_t']
    assert isinstance(case, ConditionalCase)
    assert case.condition == 'defined(ABC)'
    assert str(case.iftrue) == '<int>'
    assert case.iffalse is None

def test_conditional_typedef_2():
    ffi = FFI(backend=FakeBackend())
    ffi.cdef("""
        #ifdef ABC
        typedef int foo_t;
        #else
        typedef long foo_t;
        #endif
    """)
    case = ffi._parser._declarations['typedef foo_t']
    assert isinstance(case, ConditionalCase)
    assert case.condition == 'defined(ABC)'
    assert str(case.iftrue) == '<int>'
    assert str(case.iffalse) == '<long>'

def test_conditional_typedef_3():
    ffi = FFI(backend=FakeBackend())
    ffi.cdef("""
        #ifdef ABC
        #else
        typedef long foo_t;
        #endif
    """)
    case = ffi._parser._declarations['typedef foo_t']
    assert isinstance(case, ConditionalCase)
    assert case.condition == 'defined(ABC)'
    assert case.iftrue is None
    assert str(case.iffalse) == '<long>'

def test_conditional_typedef_4():
    ffi = FFI(backend=FakeBackend())
    ffi.cdef("""
        #ifndef ABC
        typedef long foo_t;
        #endif
    """)
    case = ffi._parser._declarations['typedef foo_t']
    assert isinstance(case, ConditionalCase)
    assert case.condition == 'defined(ABC)'
    assert case.iftrue is None
    assert str(case.iffalse) == '<long>'

def test_conditional_func():
    ffi = FFI(backend=FakeBackend())
    ffi.cdef("""
        #ifndef ABC
        int foo(int);
        #endif
    """)
    case = ffi._parser._declarations['function foo']
    assert isinstance(case, ConditionalCase)
    assert case.condition == 'defined(ABC)'
    assert case.iftrue is None
    assert str(case.iffalse) == '<func (<int>), <int>, False>'

def test_conditional_typedef_used_by_typedef():
    ffi = FFI(backend=FakeBackend())
    ffi.cdef("""
        #ifdef ABC
        typedef int foo_t;
        #else
        typedef long foo_t;
        #endif
        typedef foo_t bar_t[2];
    """)
    case = ffi._parser._declarations['typedef bar_t']
    assert isinstance(case, ConditionalCase)
    assert case.condition == 'defined(ABC)'
    assert str(case.iftrue) == '<array <int> x 2>'
    assert str(case.iffalse) == '<array <long> x 2>'

def test_conditional_typedef_used_by_func_1():
    ffi = FFI(backend=FakeBackend())
    ffi.cdef("""
        #ifdef ABC
        typedef int foo_t;
        #else
        typedef long foo_t;
        #endif
        char foo(foo_t);
    """)
    case = ffi._parser._declarations['function foo']
    assert isinstance(case, ConditionalCase)
    assert case.condition == 'defined(ABC)'
    assert str(case.iftrue) == '<func (<int>), <char>, False>'
    assert str(case.iffalse) == '<func (<long>), <char>, False>'

def test_conditional_typedef_used_by_func_2():
    ffi = FFI(backend=FakeBackend())
    ffi.cdef("""
        #ifdef ABC
        typedef int foo_t;
        #else
        typedef long foo_t;
        #endif
        foo_t foo(char);
    """)
    case = ffi._parser._declarations['function foo']
    assert isinstance(case, ConditionalCase)
    assert case.condition == 'defined(ABC)'
    assert str(case.iftrue) == '<func (<char>), <int>, False>'
    assert str(case.iffalse) == '<func (<char>), <long>, False>'

def test_conditional_typedef_not_used_by_func():
    ffi = FFI(backend=FakeBackend())
    ffi.cdef("""
        #ifdef ABC
        typedef int foo_t;
        #else
        typedef long foo_t;
        #endif
        char foo(char);
    """)
    case = ffi._parser._declarations['function foo']
    assert str(case) == '<func (<char>), <char>, False>'

def test_conditional_nested():
    ffi = FFI(backend=FakeBackend())
    ffi.cdef("""
        #ifdef ABC
        # if D > E
        typedef int foo_t;
        # else
        typedef unsigned int foo_t;
        # endif
        #else
        typedef long foo_t;
        #endif
        foo_t foo(char);
    """)
    case = ffi._parser._declarations['function foo']
    assert isinstance(case, ConditionalCase)
    assert case.condition == 'defined(ABC)'
    assert case.iftrue.condition == '(D > E)'
    assert str(case.iftrue.iftrue) == '<func (<char>), <int>, False>'
    assert str(case.iftrue.iffalse) == '<func (<char>), <unsigned int>, False>'
    assert str(case.iffalse) == '<func (<char>), <long>, False>'

def test_conditional_reuse():
    ffi = FFI(backend=FakeBackend())
    ffi.cdef("""
        #ifdef ABC
        typedef int foo_t;
        #endif

        #ifdef ABC
        foo_t foo(char);
        #endif
    """)
    case = ffi._parser._declarations['function foo']
    assert isinstance(case, ConditionalCase)
    assert case.condition == 'defined(ABC)'
    assert str(case.iftrue) == '<func (<char>), <int>, False>'
    assert case.iffalse is None

def test_conditional_reuse_nesting():
    ffi = FFI(backend=FakeBackend())
    ffi.cdef("""
        #ifdef ABC
        # if D > E
        typedef int foo_t;
        # else
        typedef unsigned int foo_t;
        # endif
        #endif

        #ifdef ABC
        foo_t foo(char);
        #endif
    """)
    case = ffi._parser._declarations['function foo']
    assert isinstance(case, ConditionalCase)
    assert case.condition == 'defined(ABC)'
    assert case.iftrue.condition == '(D > E)'
    assert str(case.iftrue.iftrue) == '<func (<char>), <int>, False>'
    assert str(case.iftrue.iffalse) == '<func (<char>), <unsigned int>, False>'
    assert case.iffalse is None

def test_conditional_different_condition():
    ffi = FFI(backend=FakeBackend())
    ffi.cdef("""
        #ifdef ABC
        typedef int foo_t;
        #else
        typedef long foo_t;
        #endif

        #if D > E
        foo_t foo(char);
        #endif
    """)
    case = ffi._parser._declarations['function foo']
    assert isinstance(case, ConditionalCase)
    assert case.condition == '(D > E)'
    assert case.iftrue.condition == 'defined(ABC)'
    assert str(case.iftrue.iftrue) == '<func (<char>), <int>, False>'
    assert str(case.iftrue.iffalse) == '<func (<char>), <unsigned int>, False>'
    assert case.iffalse is None

def test_conditional_reuse_reversed_nesting():
    ffi = FFI(backend=FakeBackend())
    ffi.cdef("""
        #ifdef ABC
        # if D > E
        typedef int foo_t;
        # else
        typedef unsigned int foo_t;
        # endif
        #else
        typedef long foo_t;
        #endif

        #if D > E
        foo_t foo(char);
        #endif
    """)
    case = ffi._parser._declarations['function foo']
    assert isinstance(case, ConditionalCase)
    assert case.condition == '(D > E)'
    assert case.iftrue.condition == 'defined(ABC)'
    assert str(case.iftrue.iftrue) == '<func (<char>), <int>, False>'
    assert str(case.iftrue.iffalse) == '<func (<char>), <long>, False>'
    assert case.iffalse is None

def test_define_not_supported_for_now():
    ffi = FFI(backend=FakeBackend())
    e = py.test.raises(CDefError, ffi.cdef, '#define FOO "blah"')
    assert str(e.value) == (
        'only supports one of the following syntax:\n'
        '  #define FOO ...     (literally dot-dot-dot)\n'
        '  #define FOO NUMBER  (with NUMBER an integer'
                                    ' constant, decimal/hex/octal)\n'
        'got:\n'
        '  #define FOO "blah"')

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
    assert re.match(r'cannot parse "x y z"\n:\d+:', str(e.value))

def test_cannot_declare_enum_later():
    ffi = FFI()
    e = py.test.raises(NotImplementedError, ffi.cdef,
                       "typedef enum foo_e foo_t; enum foo_e { AA, BB };")
    assert str(e.value) == (
           "enum foo_e: the '{}' declaration should appear on the "
           "first time the enum is mentioned, not later")

def test_unknown_name():
    ffi = FFI()
    e = py.test.raises(CDefError, ffi.cast, "foobarbazunknown", 0)
    assert str(e.value) == "unknown identifier 'foobarbazunknown'"
    e = py.test.raises(CDefError, ffi.cast, "foobarbazunknown*", 0)
    assert str(e.value).startswith('cannot parse "foobarbazunknown*"')
    e = py.test.raises(CDefError, ffi.cast, "int(*)(foobarbazunknown)", 0)
    assert str(e.value).startswith('cannot parse "int(*)(foobarbazunknown)"')

def test_redefine_common_type():
    prefix = "" if sys.version_info < (3,) else "b"
    ffi = FFI()
    ffi.cdef("typedef char FILE;")
    assert repr(ffi.cast("FILE", 123)) == "<cdata 'char' %s'{'>" % prefix
    ffi.cdef("typedef char int32_t;")
    assert repr(ffi.cast("int32_t", 123)) == "<cdata 'char' %s'{'>" % prefix

def test_bool():
    ffi = FFI()
    ffi.cdef("void f(bool);")
    #
    ffi = FFI()
    ffi.cdef("typedef _Bool bool; void f(bool);")

def test_void_renamed_as_only_arg():
    ffi = FFI()
    ffi.cdef("typedef void void_t1;"
             "typedef void_t1 void_t;"
             "typedef int (*func_t)(void_t);")
    assert ffi.typeof("func_t").args == ()

def test_win_common_types():
    from cffi.commontypes import COMMON_TYPES, _CACHE
    from cffi.commontypes import win_common_types, resolve_common_type
    #
    def clear_all(extra={}, old_dict=COMMON_TYPES.copy()):
        COMMON_TYPES.clear()
        COMMON_TYPES.update(old_dict)
        COMMON_TYPES.update(extra)
        _CACHE.clear()
    #
    for maxsize in [2**32-1, 2**64-1]:
        ct = win_common_types(maxsize)
        clear_all(ct)
        for key in sorted(ct):
            if ct[key] != 'set-unicode-needed':
                resolve_common_type(key)
    # assert did not crash
    # now try to use e.g. WPARAM (-> UINT_PTR -> unsigned 32/64-bit)
    for maxsize in [2**32-1, 2**64-1]:
        ct = win_common_types(maxsize)
        clear_all(ct)
        ffi = FFI()
        value = int(ffi.cast("WPARAM", -1))
        assert value == maxsize
    #
    clear_all()

def test_WPARAM_on_windows():
    if sys.platform != 'win32':
        py.test.skip("Only for Windows")
    ffi = FFI()
    ffi.cdef("void f(WPARAM);")

def test__is_constant_globalvar():
    from cffi.cparser import Parser, _get_parser
    for input, expected_output in [
        ("int a;",          False),
        ("const int a;",    True),
        ("int *a;",         False),
        ("const int *a;",   False),
        ("int const *a;",   False),
        ("int *const a;",   True),
        ("int a[5];",       False),
        ("const int a[5];", False),
        ("int *a[5];",      False),
        ("const int *a[5];", False),
        ("int const *a[5];", False),
        ("int *const a[5];", False),
        ("int a[5][6];",       False),
        ("const int a[5][6];", False),
        ]:
        p = Parser()
        ast = _get_parser().parse(input)
        decl = ast.children()[0][1]
        node = decl.type
        assert p._is_constant_globalvar(node) == expected_output

def test_enum():
    ffi = FFI()
    ffi.cdef("""
        enum Enum { POS = +1, TWO = 2, NIL = 0, NEG = -1};
        """)
    C = ffi.dlopen(None)
    assert C.POS == 1
    assert C.TWO == 2
    assert C.NIL == 0
    assert C.NEG == -1

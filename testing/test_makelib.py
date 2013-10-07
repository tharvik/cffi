import math
import sys
from cffi import FFIBuilder
from cffi.verifier import _get_so_suffix


def _clean_modules(tmpdir, module_name):
    sys.path.remove(str(tmpdir))
    for name in list(sys.modules.keys()):
        if name and name.endswith(module_name):
            sys.modules.pop(name)


def test_ffibuilder_makelib(tmpdir):
    builder = FFIBuilder("foo_ffi", str(tmpdir))
    builder.cdef("""
        double sin(double x);
    """)
    builder.makelib('foo', '#include <math.h>')
    builder.write_ffi_module()

    assert builder.list_built_files() == [
        'foo_ffi_foo' + _get_so_suffix(),
        'foo_ffi.py',
    ]

    sys.path.append(str(tmpdir))
    try:
        import foo_ffi
    finally:
        _clean_modules(tmpdir, 'foo_ffi')

    lib = foo_ffi.load_foo()
    assert lib.sin(12.3) == math.sin(12.3)


def test_ffibuilder_dlopen(tmpdir):
    builder = FFIBuilder("foo_ffi", str(tmpdir))
    builder.cdef("""
        double sin(double x);
    """)
    builder.add_dlopen('foo', "m")
    builder.write_ffi_module()

    assert builder.list_built_files() == [
        'foo_ffi.py',
    ]

    sys.path.append(str(tmpdir))
    try:
        import foo_ffi
    finally:
        _clean_modules(tmpdir, 'foo_ffi')

    lib = foo_ffi.load_foo()
    assert lib.sin(12.3) == math.sin(12.3)


def test_ffibuilder_makelib_and_dlopen(tmpdir):
    builder = FFIBuilder("foo_ffi", str(tmpdir))
    builder.cdef("""
        double sin(double x);
    """)
    builder.makelib('foo', '#include <math.h>')
    builder.add_dlopen('bar', "m")
    builder.write_ffi_module()

    assert builder.list_built_files() == [
        'foo_ffi_foo' + _get_so_suffix(),
        'foo_ffi.py',
    ]

    sys.path.append(str(tmpdir))
    try:
        import foo_ffi
    finally:
        _clean_modules(tmpdir, 'foo_ffi')

    lib_foo = foo_ffi.load_foo()
    assert lib_foo.sin(12.3) == math.sin(12.3)
    lib_bar = foo_ffi.load_bar()
    assert lib_bar.sin(12.3) == math.sin(12.3)


def test_ffi_module_functions(tmpdir):
    builder = FFIBuilder("foo_ffi", str(tmpdir))
    builder.cdef("""
        double sin(double x);
    """)
    builder.makelib('foo', '#include <math.h>')
    builder.write_ffi_module()

    sys.path.append(str(tmpdir))
    try:
        import foo_ffi
    finally:
        _clean_modules(tmpdir, 'foo_ffi')

    assert foo_ffi.typeof == foo_ffi._ffi.typeof
    assert foo_ffi.sizeof == foo_ffi._ffi.sizeof
    assert foo_ffi.alignof == foo_ffi._ffi.alignof
    assert foo_ffi.offsetof == foo_ffi._ffi.offsetof
    assert foo_ffi.new == foo_ffi._ffi.new
    assert foo_ffi.cast == foo_ffi._ffi.cast
    assert foo_ffi.string == foo_ffi._ffi.string
    assert foo_ffi.buffer == foo_ffi._ffi.buffer
    assert foo_ffi.callback == foo_ffi._ffi.callback
    assert foo_ffi.getctype == foo_ffi._ffi.getctype
    assert foo_ffi.gc == foo_ffi._ffi.gc

    foo_ffi.set_errno(7)
    assert foo_ffi.get_errno() == 7

    assert foo_ffi.addressof == foo_ffi._ffi.addressof
    assert foo_ffi.new_handle == foo_ffi._ffi.new_handle
    assert foo_ffi.from_handle == foo_ffi._ffi.from_handle


def test_ffi_do_some_stuff(tmpdir):
    builder = FFIBuilder("foo_ffi", str(tmpdir))
    builder.cdef("""
        enum ee { EE1, EE2, EE3, ... };
        struct foo_s { int x; int y; };
        int grid_distance(struct foo_s offset);
    """)
    builder.makelib('foo', """
        enum ee { EE1=10, EE2, EE3=-10, EE4 };
        struct foo_s { int x; int y; };
        int grid_distance(struct foo_s offset) {
            return offset.x + offset.y;
        }
    """)
    builder.write_ffi_module()

    sys.path.append(str(tmpdir))
    try:
        import foo_ffi
    finally:
        _clean_modules(tmpdir, 'foo_ffi')

    my_struct = foo_ffi.new('struct foo_s *', {'x': 1, 'y': 2})
    assert foo_ffi.typeof(my_struct) == foo_ffi.typeof("struct foo_s *")
    assert foo_ffi.sizeof('struct foo_s') == 2 * foo_ffi.sizeof('int')
    assert foo_ffi.alignof('struct foo_s') == foo_ffi.sizeof('int')
    assert foo_ffi.typeof(foo_ffi.cast('long', 42)) == foo_ffi.typeof('long')
    assert foo_ffi.string(foo_ffi.new('char *', b"\x00")) == b""
    assert foo_ffi.string(foo_ffi.cast('enum ee', 11)) == "EE2"
    assert foo_ffi.string(foo_ffi.cast('enum ee', -10)) == "EE3"

    def cb(n):
        return n + 1
    f = foo_ffi.callback("int(*)(int)", cb)
    assert f(1) == 2

    lib = foo_ffi.load_foo()
    assert lib.grid_distance(my_struct[0]) == 3

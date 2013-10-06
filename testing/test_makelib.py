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
        str(tmpdir.join('foo_ffi_foo' + _get_so_suffix())),
        str(tmpdir.join('foo_ffi.py')),
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
        str(tmpdir.join('foo_ffi.py')),
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
        str(tmpdir.join('foo_ffi_foo' + _get_so_suffix())),
        str(tmpdir.join('foo_ffi.py')),
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

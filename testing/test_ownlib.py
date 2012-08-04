import py, sys
import subprocess
from cffi import FFI
from cffi.backend_ctypes import CTypesBackend


SOURCE = """\
#include <errno.h>

int test_getting_errno(void) {
    errno = 123;
    return -1;
}

int test_setting_errno(void) {
    return errno;
}

int my_array[7] = {0, 1, 2, 3, 4, 5, 6};
"""

class TestOwnLib(object):
    Backend = CTypesBackend

    def setup_class(cls):
        if sys.platform == 'win32':
            return
        from testing.udir import udir
        udir.join('testownlib.c').write(SOURCE)
        subprocess.check_call(
            'gcc testownlib.c -shared -fPIC -o testownlib.so',
            cwd=str(udir), shell=True)
        cls.module = str(udir.join('testownlib.so'))

    def setup_method(self, meth):
        if sys.platform == 'win32':
            py.test.skip("fix the auto-generation of the tiny test lib")

    def test_getting_errno(self):
        ffi = FFI(backend=self.Backend())
        ffi.cdef("""
            int test_getting_errno(void);
        """)
        ownlib = ffi.dlopen(self.module)
        res = ownlib.test_getting_errno()
        assert res == -1
        assert ffi.errno == 123

    def test_setting_errno(self):
        if self.Backend is CTypesBackend and '__pypy__' in sys.modules:
            py.test.skip("XXX errno issue with ctypes on pypy?")
        ffi = FFI(backend=self.Backend())
        ffi.cdef("""
            int test_setting_errno(void);
        """)
        ownlib = ffi.dlopen(self.module)
        ffi.errno = 42
        res = ownlib.test_setting_errno()
        assert res == 42
        assert ffi.errno == 42

    def test_my_array_7(self):
        ffi = FFI(backend=self.Backend())
        ffi.cdef("""
            int my_array[7];
        """)
        ownlib = ffi.dlopen(self.module)
        for i in range(7):
            assert ownlib.my_array[i] == i
        assert len(ownlib.my_array) == 7
        if self.Backend is CTypesBackend:
            py.test.skip("not supported by the ctypes backend")
        ownlib.my_array = range(10, 17)
        for i in range(7):
            assert ownlib.my_array[i] == 10 + i
        ownlib.my_array = range(7)
        for i in range(7):
            assert ownlib.my_array[i] == i

    def test_my_array_no_length(self):
        if self.Backend is CTypesBackend:
            py.test.skip("not supported by the ctypes backend")
        ffi = FFI(backend=self.Backend())
        ffi.cdef("""
            int my_array[];
        """)
        ownlib = ffi.dlopen(self.module)
        for i in range(7):
            assert ownlib.my_array[i] == i
        py.test.raises(TypeError, len, ownlib.my_array)
        ownlib.my_array = range(10, 17)
        for i in range(7):
            assert ownlib.my_array[i] == 10 + i
        ownlib.my_array = range(7)
        for i in range(7):
            assert ownlib.my_array[i] == i

import os, py
import cffi
from testing.udir import udir


def chdir_to_tmp(f):
    f.chdir_to_tmp = True
    return f

def from_outside(f):
    f.chdir_to_tmp = False
    return f


class TestDist(object):

    def setup_method(self, meth):
        self.udir = udir.join(meth.__name__)
        os.mkdir(str(self.udir))
        if meth.chdir_to_tmp:
            self.saved_cwd = os.getcwd()
            os.chdir(str(self.udir))

    def teardown_method(self, meth):
        if hasattr(self, 'saved_cwd'):
            os.chdir(self.saved_cwd)

    def check_produced_files(self, content, curdir=None):
        if curdir is None:
            curdir = str(self.udir)
        found_so = None
        for name in os.listdir(curdir):
            if (name.endswith('.so') or name.endswith('.pyd') or
                name.endswith('.dylib')):
                found_so = os.path.join(curdir, name)
                name = os.path.splitext(name)[0] + '.SO'
            assert name in content, "found unexpected file %r" % (
                os.path.join(curdir, name),)
            value = content.pop(name)
            if value is None:
                assert name.endswith('.SO') or (
                    os.path.isfile(os.path.join(curdir, name)))
            else:
                subdir = os.path.join(curdir, name)
                assert os.path.isdir(subdir)
                found_so = self.check_produced_files(value, subdir) or found_so
        assert content == {}, "files or dirs not produced in %r: %r" % (
            curdir, content.keys())
        return found_so

    @chdir_to_tmp
    def test_empty(self):
        self.check_produced_files({})

    @chdir_to_tmp
    def test_abi_emit_python_code_1(self):
        ffi = cffi.FFI()
        ffi.set_source("package_name_1.mymod", None)
        ffi.emit_python_code('xyz.py')
        self.check_produced_files({'xyz.py': None})

    @chdir_to_tmp
    def test_abi_emit_python_code_2(self):
        ffi = cffi.FFI()
        ffi.set_source("package_name_1.mymod", None)
        py.test.raises(IOError, ffi.emit_python_code, 'unexisting/xyz.py')

    @from_outside
    def test_abi_emit_python_code_3(self):
        ffi = cffi.FFI()
        ffi.set_source("package_name_1.mymod", None)
        ffi.emit_python_code(str(self.udir.join('xyt.py')))
        self.check_produced_files({'xyt.py': None})

    @chdir_to_tmp
    def test_abi_compile_1(self):
        ffi = cffi.FFI()
        ffi.set_source("mod_name_in_package.mymod", None)
        x = ffi.compile()
        self.check_produced_files({'mod_name_in_package': {'mymod.py': None}})
        assert x == os.path.join('.', 'mod_name_in_package', 'mymod.py')

    @chdir_to_tmp
    def test_abi_compile_2(self):
        ffi = cffi.FFI()
        ffi.set_source("mod_name_in_package.mymod", None)
        x = ffi.compile('build2')
        self.check_produced_files({'build2': {
            'mod_name_in_package': {'mymod.py': None}}})
        assert x == os.path.join('build2', 'mod_name_in_package', 'mymod.py')

    @from_outside
    def test_abi_compile_3(self):
        ffi = cffi.FFI()
        ffi.set_source("mod_name_in_package.mymod", None)
        tmpdir = str(self.udir.join('build3'))
        x = ffi.compile(tmpdir)
        self.check_produced_files({'build3': {
            'mod_name_in_package': {'mymod.py': None}}})
        assert x == os.path.join(tmpdir, 'mod_name_in_package', 'mymod.py')

    @chdir_to_tmp
    def test_api_emit_c_code_1(self):
        ffi = cffi.FFI()
        ffi.set_source("package_name_1.mymod", "/*code would be here*/")
        ffi.emit_c_code('xyz.c')
        self.check_produced_files({'xyz.c': None})

    @chdir_to_tmp
    def test_api_emit_c_code_2(self):
        ffi = cffi.FFI()
        ffi.set_source("package_name_1.mymod", "/*code would be here*/")
        py.test.raises(IOError, ffi.emit_c_code, 'unexisting/xyz.c')

    @from_outside
    def test_api_emit_c_code_3(self):
        ffi = cffi.FFI()
        ffi.set_source("package_name_1.mymod", "/*code would be here*/")
        ffi.emit_c_code(str(self.udir.join('xyu.c')))
        self.check_produced_files({'xyu.c': None})

    @chdir_to_tmp
    def test_api_compile_1(self):
        ffi = cffi.FFI()
        ffi.set_source("mod_name_in_package.mymod", "/*code would be here*/")
        x = ffi.compile()
        sofile = self.check_produced_files({
            'mod_name_in_package': {'mymod.SO': None,
                                    'mymod.c': None,
                                    'mymod.o': None}})
        assert os.path.isabs(x) and os.path.samefile(x, sofile)

    @chdir_to_tmp
    def test_api_compile_2(self):
        ffi = cffi.FFI()
        ffi.set_source("mod_name_in_package.mymod", "/*code would be here*/")
        x = ffi.compile('output')
        sofile = self.check_produced_files({
            'output': {'mod_name_in_package': {'mymod.SO': None,
                                               'mymod.c': None,
                                               'mymod.o': None}}})
        assert os.path.isabs(x) and os.path.samefile(x, sofile)

    @from_outside
    def test_api_compile_3(self):
        ffi = cffi.FFI()
        ffi.set_source("mod_name_in_package.mymod", "/*code would be here*/")
        x = ffi.compile(str(self.udir.join('foo')))
        sofile = self.check_produced_files({
            'foo': {'mod_name_in_package': {'mymod.SO': None,
                                            'mymod.c': None,
                                            'mymod.o': None}}})
        assert os.path.isabs(x) and os.path.samefile(x, sofile)

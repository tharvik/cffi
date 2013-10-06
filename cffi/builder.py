from .api import FFI


class FFIBuilder(object):
    def __init__(self, module_name, module_path, backend=None):
        self._module_name = module_name
        self._module_path = module_path
        self.ffi = FFI(backend=backend)
        self._built_files = []
        self._module_source = "\n".join([
            "from cffi import FFI",
            "",
            "ffi = FFI()",
            "",
        ])

    def cdef(self, csource, override=False):
        self.ffi.cdef(csource, override=override)
        self._module_source += "ffi.cdef(%r, override=%r)\n" % (
            csource, override)

    def add_dlopen(self, libname, name, flags=0):
        lib = self.ffi.dlopen(name, flags=flags)
        self._module_source += '\n'.join([
            "def load_%s():",
            "    return ffi.dlopen(%r, flags=%r)",
            "",
        ]) % (libname, name, flags)
        return lib

    def makelib(self, libname, source='', **kwargs):
        # XXX: We use force_generic_engine here because vengine_cpy collects
        #      types when it writes the source.
        import os.path
        from .verifier import Verifier, _get_so_suffix
        self.ffi.verifier = Verifier(
            self.ffi, source, force_generic_engine=True, **kwargs)
        libfilename = '_'.join([self._module_name, libname])
        libfilepath = os.path.join(
            self._module_path, libfilename + _get_so_suffix())
        self.ffi.verifier.make_library(libfilepath)
        self._module_source += '\n'.join([
            "def load_%s():",
            "    from cffi.verifier import Verifier",
            "    import os.path",
            "    module_path = os.path.dirname(__file__)",
            "    verifier = Verifier(",
            "        ffi, None, module_path, %r, force_generic_engine=True)",
            "    verifier._has_module = True",
            "    return verifier._load_library()",
            "",
        ]) % (libname, libfilename)
        self._built_files.append(libfilepath)

    def write_ffi_module(self):
        import os
        try:
            os.makedirs(self._module_path)
        except OSError:
            pass

        module_filepath = os.path.join(
            self._module_path, self._module_name + '.py')
        file = open(module_filepath, 'w')
        try:
            file.write(self._module_source)
        finally:
            file.close()
        self._built_files.append(module_filepath)

    def list_built_files(self):
        return self._built_files

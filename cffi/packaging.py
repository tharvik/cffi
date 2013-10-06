from distutils.command.build_ext import build_ext as _build_ext
from distutils.core import Extension
import os


class FFIExtension(Extension):
    def __init__(self, ffi_builder):
        self.ffi_builder = ffi_builder
        Extension.__init__(self, '<cffi extension>', [])


class build_ext(_build_ext):
    def build_extension(self, ext):
        if isinstance(ext, FFIExtension):
            pkg = self.package.split('.') if self.package else []
            temp = os.path.join(self.build_temp, *pkg)
            lib = os.path.join(self.build_lib, *pkg)

            files = ext.ffi_builder(temp)
            if not os.path.isdir(lib):
                os.makedirs(lib)
            for name in files:
                self.copy_file(os.path.join(temp, name),
                               os.path.join(lib, name))
        else:
            super(build_ext, self).build_extension(ext)

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
            files = ext.ffi_builder(self.build_temp)
            for name in files:
                self.copy_file(
                    os.path.join(self.build_temp, name),
                    os.path.join(self.build_lib, name))
        else:
            super(build_ext, self).build_extension(ext)

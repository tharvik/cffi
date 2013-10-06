from distutils.core import setup

from cffi.packaging import FFIExtension, build_ext

import snip_basic_module1.ffibuilder


setup(
    packages=['snip_basic_module1'],
    ext_modules=[FFIExtension(snip_basic_module1.ffibuilder.build_ffi)],
    cmdclass={'build_ext': build_ext},
)

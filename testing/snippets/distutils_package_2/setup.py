from distutils.core import setup

from cffi.packaging import FFIExtension, build_ext

import snip_basic_module2.ffibuilder


setup(
    packages=['snip_basic_module2'],
    ext_package='snip_basic_module2',
    ext_modules=[FFIExtension(snip_basic_module2.ffibuilder.build_ffi)],
    cmdclass={'build_ext': build_ext},
)

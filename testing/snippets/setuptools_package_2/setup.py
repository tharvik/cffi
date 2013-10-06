from setuptools import setup

from cffi.packaging import FFIExtension, build_ext

import snip_setuptools_module2.ffibuilder


setup(
    packages=['snip_setuptools_module2'],
    ext_package='snip_setuptools_module2',
    ext_modules=[FFIExtension(snip_setuptools_module2.ffibuilder.build_ffi)],
    cmdclass={'build_ext': build_ext},
)

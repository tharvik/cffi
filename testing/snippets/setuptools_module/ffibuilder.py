import sys

from cffi import FFIBuilder


def build_ffi(path):
    builder = FFIBuilder('snip_setuptools_module', path)
    builder.cdef("""     // some declarations from the man page
    struct passwd {
        char *pw_name;
        ...;
    };
    struct passwd *getpwuid(int uid);
    """)
    builder.makelib('passwd', """   // passed to the real C compiler
    #include <sys/types.h>
    #include <pwd.h>
    """, libraries=[],  # or a list of libraries to link with
         force_generic_engine=hasattr(sys, '_force_generic_engine_'))
    builder.write_ffi_module()
    return builder.list_built_files()

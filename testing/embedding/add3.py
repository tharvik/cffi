import cffi

ffi = cffi.FFI()

ffi.cdef("""
    extern "Python" int add3(int, int, int, int);
""", dllexport=True)

ffi.embedding_init_code(r"""
    import sys

    @ffi.def_extern()
    def add3(x, y, z, t):
        sys.stdout.write("adding %d, %d, %d, %d\n" % (x, y, z, t))
        return x + y + z + t
""")

ffi.set_source("_add3_cffi", """
""")

ffi.compile()

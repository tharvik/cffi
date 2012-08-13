# A Linux-only demo
#
# This combines the ffi.ctypesdef() interface with the ffi.verify()
# interface.  The main differences with a pure ctypes interface are
# highlighted with "# <--".
import sys
import cffi
from cffi import ctypes

if not sys.platform.startswith('linux'):
    raise Exception("Linux-only demo")


DIR = ctypes.OPAQUE          # <--
DIR_p = ctypes.POINTER(DIR)

class DIRENT(ctypes.PartialStructure):    # <--
    _fields_ = [
        ('d_type', ctypes.c_ubyte),       # type of file; not supported
                                          #   by all file system types
        ('d_name', ctypes.c_char * Ellipsis),  # filename
        ]
DIRENT_p = ctypes.POINTER(DIRENT)
DIRENT_pp = ctypes.POINTER(DIRENT_p)

ffi = cffi.FFI()           # <--
C = ffi.ctypesdef()        # <--

readdir_r = C.readdir_r
readdir_r.argtypes = [DIR_p, DIRENT_p, DIRENT_pp]
readdir_r.restype = ctypes.c_int

openat = C.openat
openat.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int]
openat.restype = ctypes.c_int

fdopendir = C.fdopendir
fdopendir.argtypes = [ctypes.c_int]
fdopendir.restype = DIR_p

closedir = C.closedir
closedir.argtypes = [DIR_p]
closedir.restype = ctypes.c_int

ffi.verify("""
#ifndef _ATFILE_SOURCE
#  define _ATFILE_SOURCE
#endif
#ifndef _BSD_SOURCE
#  define _BSD_SOURCE
#endif
#include <fcntl.h>
#include <sys/types.h>
#include <dirent.h>
""")         # <-- the whole verify() is not in ctypes, but gives API compat


def walk(basefd, path):
    print '{', path
    dirfd = openat(basefd, path, 0)
    if dirfd < 0:
        # error in openat()
        return
    dir = fdopendir(dirfd)
    dirent = ffi.new(DIRENT_p)       # <-- in the actual code, must use
    result = ffi.new(DIRENT_pp)      # <-- the CFFI way, not the ctypes one
    while True:
        if readdir_r(dir, dirent, result):
            # error in readdir_r()
            break
        if not result:
            break
        name = ffi.string(dirent.d_name)    # <-- CFFI way
        print '%3d %s' % (dirent.d_type, name)
        if dirent.d_type == 4 and name != '.' and name != '..':
            walk(dirfd, name)
    closedir(dir)
    print '}'


walk(-1, "/tmp")

import os

try:
    basestring
except NameError:
    # Python 3.x
    basestring = str

def error(msg):
    from distutils.errors import DistutilsSetupError
    raise DistutilsSetupError(msg)


def execfile(filename, glob):
    # We use execfile() (here rewritten for Python 3) instead of
    # __import__() to load the build script.  The problem with
    # a normal import is that in some packages, the intermediate
    # __init__.py files may already try to import the file that
    # we are generating.
    with open(filename) as f:
        code = compile(f.read(), filename, 'exec')
    exec(code, glob, glob)


def add_cffi_module(dist, mod_spec):
    from cffi.api import FFI

    if not isinstance(mod_spec, basestring):
        error("argument to 'cffi_modules=...' must be a str or a list of str,"
              " not %r" % (type(mod_spec).__name__,))
    mod_spec = str(mod_spec)
    try:
        build_file_name, ffi_var_name = mod_spec.split(':')
    except ValueError:
        error("%r must be of the form 'path/build.py:ffi_variable'" %
              (mod_spec,))
    if not os.path.exists(build_file_name):
        ext = ''
        rewritten = build_file_name.replace('.', '/') + '.py'
        if os.path.exists(rewritten):
            ext = ' (rewrite cffi_modules to [%r])' % (
                rewritten + ':' + ffi_var_name,)
        error("%r does not name an existing file%s" % (build_file_name, ext))

    mod_vars = {'__name__': '__cffi__', '__file__': build_file_name}
    execfile(build_file_name, mod_vars)

    try:
        ffi = mod_vars[ffi_var_name]
    except KeyError:
        error("%r: object %r not found in module" % (mod_spec,
                                                     ffi_var_name))
    if not isinstance(ffi, FFI):
        ffi = ffi()      # maybe it's a function instead of directly an ffi
    if not isinstance(ffi, FFI):
        error("%r is not an FFI instance (got %r)" % (mod_spec,
                                                      type(ffi).__name__))
    if not hasattr(ffi, '_assigned_source'):
        error("%r: the set_source() method was not called" % (mod_spec,))
    module_name, source, source_extension, kwds = ffi._assigned_source
    if ffi._windows_unicode:
        kwds = kwds.copy()
        ffi._apply_windows_unicode(kwds)

    if source is None:
        _add_py_module(dist, ffi, module_name)
    else:
        _add_c_module(dist, ffi, module_name, source, source_extension, kwds)


def _add_c_module(dist, ffi, module_name, source, source_extension, kwds):
    from distutils.core import Extension
    from distutils.command.build_ext import build_ext
    from distutils.dir_util import mkpath
    from distutils import log
    from cffi import recompiler

    allsources = ['$PLACEHOLDER']
    allsources.extend(kwds.pop('sources', []))
    ext = Extension(name=module_name, sources=allsources, **kwds)

    def make_mod(tmpdir):
        c_file = os.path.join(tmpdir, module_name + source_extension)
        log.info("generating cffi module %r" % c_file)
        mkpath(tmpdir)
        updated = recompiler.make_c_source(ffi, module_name, source, c_file)
        if not updated:
            log.info("already up-to-date")
        return c_file

    if dist.ext_modules is None:
        dist.ext_modules = []
    dist.ext_modules.append(ext)

    base_class = dist.cmdclass.get('build_ext', build_ext)
    class build_ext_make_mod(base_class):
        def run(self):
            if ext.sources[0] == '$PLACEHOLDER':
                ext.sources[0] = make_mod(self.build_temp)
            base_class.run(self)
    dist.cmdclass['build_ext'] = build_ext_make_mod
    # NB. multiple runs here will create multiple 'build_ext_make_mod'
    # classes.  Even in this case the 'build_ext' command should be
    # run once; but just in case, the logic above does nothing if
    # called again.


def _add_py_module(dist, ffi, module_name):
    from distutils.dir_util import mkpath
    from distutils.command.build_py import build_py
    from distutils import log
    from cffi import recompiler

    def make_mod(tmpdir):
        module_path = module_name.split('.')
        module_path[-1] += '.py'
        py_file = os.path.join(tmpdir, *module_path)
        log.info("generating cffi module %r" % py_file)
        mkpath(os.path.dirname(py_file))
        updated = recompiler.make_py_source(ffi, module_name, py_file)
        if not updated:
            log.info("already up-to-date")

    base_class = dist.cmdclass.get('build_py', build_py)
    class build_py_make_mod(base_class):
        def run(self):
            base_class.run(self)
            make_mod(self.build_lib)
    dist.cmdclass['build_py'] = build_py_make_mod


def cffi_modules(dist, attr, value):
    assert attr == 'cffi_modules'
    if isinstance(value, basestring):
        value = [value]

    for cffi_module in value:
        add_cffi_module(dist, cffi_module)

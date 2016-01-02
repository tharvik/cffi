import sys, os
import shutil, subprocess
from testing.udir import udir

local_dir = os.path.dirname(os.path.abspath(__file__))


class EmbeddingTests:
    _compiled_modules = set()

    def get_path(self):
        return str(udir.ensure('embedding', dir=True))

    def _run(self, args, env=None):
        print(args)
        popen = subprocess.Popen(args, env=env, cwd=self.get_path())
        err = popen.wait()
        if err:
            raise OSError("popen failed with exit code %r: %r" % (
                err, args))

    def prepare_module(self, name):
        if name not in self._compiled_modules:
            path = self.get_path()
            filename = '%s.py' % name
            # NOTE: if you have an .egg globally installed with an older
            # version of cffi, this will not work, because sys.path ends
            # up with the .egg before the PYTHONPATH entries.  I didn't
            # find a solution to that: we can hack sys.path inside the
            # script run here, but we can't hack it in the same way in
            # execute().
            env = os.environ.copy()
            env['PYTHONPATH'] = os.path.dirname(os.path.dirname(local_dir))
            self._run([sys.executable, os.path.join(local_dir, filename)],
                      env=env)
            self._compiled_modules.add(name)

    def compile(self, name, modules, extra=[]):
        path = self.get_path()
        filename = '%s.c' % name
        shutil.copy(os.path.join(local_dir, filename), path)
        if '__pypy__' in sys.builtin_module_names:
            # xxx a bit hackish, maybe ffi.compile() should do a better job
            executable = os.path.abspath(sys.executable)
            libpypy_c = os.path.join(os.path.dirname(executable),
                                     'libpypy-c.so')
            try:
                os.symlink(libpypy_c, os.path.join(path, 'libpypy-c.so'))
            except OSError:
                pass
            self._run(['gcc', '-g', filename, '-o', name, '-L.'] +
                      ['%s.pypy-26.so' % modname for modname in modules] +
                      ['-lpypy-c', '-Wl,-rpath=$ORIGIN/'] + extra)
        else:
            self._run(['gcc', '-g', filename, '-o', name, '-L.'] +
                      ['%s.so' % modname for modname in modules] +
                      ['-lpython2.7', '-Wl,-rpath=$ORIGIN/'] + extra)

    def execute(self, name):
        path = self.get_path()
        env = os.environ.copy()
        env['PYTHONPATH'] = os.path.dirname(os.path.dirname(local_dir))
        popen = subprocess.Popen([name], cwd=path, env=env,
                                 stdout=subprocess.PIPE)
        result = popen.stdout.read()
        err = popen.wait()
        if err:
            raise OSError("%r failed with exit code %r" % (name, err))
        return result


class TestBasic(EmbeddingTests):
    def test_basic(self):
        self.prepare_module('add1')
        self.compile('add1-test', ['_add1_cffi'])
        output = self.execute('add1-test')
        assert output == ("preparing...\n"
                          "adding 40 and 2\n"
                          "adding 100 and -5\n"
                          "got: 42 95\n")

    def test_two_modules(self):
        self.prepare_module('add1')
        self.prepare_module('add2')
        self.compile('add2-test', ['_add1_cffi', '_add2_cffi'])
        output = self.execute('add2-test')
        assert output == ("preparing...\n"
                          "adding 40 and 2\n"
                          "prepADD2\n"
                          "adding 100 and -5 and -20\n"
                          "got: 42 75\n")

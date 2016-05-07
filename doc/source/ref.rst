================================
CFFI Reference
================================

.. contents::


FFI Interface
-------------


ffi.NULL
++++++++

**ffi.NULL**: a constant NULL of type ``<cdata 'void *'>``.


ffi.error
+++++++++

**ffi.error**: the Python exception raised in various cases.  (Don't
confuse it with ``ffi.errno``.)


ffi.new()
+++++++++

**ffi.new(cdecl, init=None)**:
allocate an instance according to the specified C type and return a
pointer to it.  The specified C type must be either a pointer or an
array: ``new('X *')`` allocates an X and returns a pointer to it,
whereas ``new('X[n]')`` allocates an array of n X'es and returns an
array referencing it (which works mostly like a pointer, like in C).
You can also use ``new('X[]', n)`` to allocate an array of a
non-constant length n.  See the `detailed documentation`__ for other
valid initializers.

.. __: using.html#working

When the returned ``<cdata>`` object goes out of scope, the memory is
freed.  In other words the returned ``<cdata>`` object has ownership of
the value of type ``cdecl`` that it points to.  This means that the raw
data can be used as long as this object is kept alive, but must not be
used for a longer time.  Be careful about that when copying the
pointer to the memory somewhere else, e.g. into another structure.


ffi.cast()
++++++++++

**ffi.cast("C type", value)**: similar to a C cast: returns an
instance of the named C type initialized with the given value.  The
value is casted between integers or pointers of any type.


.. _ffi-errno:
.. _ffi-getwinerror:

ffi.errno, ffi.getwinerror()
++++++++++++++++++++++++++++

**ffi.errno**: the value of ``errno`` received from the most recent C call
in this thread, and passed to the following C call.  (This is a read-write
property.)

**ffi.getwinerror(code=-1)**: on Windows, in addition to ``errno`` we
also save and restore the ``GetLastError()`` value across function
calls.  This function returns this error code as a tuple ``(code,
message)``, adding a readable message like Python does when raising
WindowsError.  If the argument ``code`` is given, format that code into
a message instead of using ``GetLastError()``.
(Note that it is also possible to declare and call the ``GetLastError()``
function as usual.)


.. _ffi-string:
.. _ffi-unpack:

ffi.string(), ffi.unpack()
++++++++++++++++++++++++++

**ffi.string(cdata, [maxlen])**: return a Python string (or unicode
string) from the 'cdata'.

- If 'cdata' is a pointer or array of characters or bytes, returns the
  null-terminated string.  The returned string extends until the first
  null character.  The 'maxlen' argument limits how far we look for a
  null character.  If 'cdata' is an
  array then 'maxlen' defaults to its length.  See ``ffi.unpack()`` below
  for a way to continue past the first null character.  *Python 3:* this
  returns a ``bytes``, not a ``str``.

- If 'cdata' is a pointer or array of wchar_t, returns a unicode string
  following the same rules.

- If 'cdata' is a single character or byte or a wchar_t, returns it as a
  byte string or unicode string.  (Note that in some situation a single
  wchar_t may require a Python unicode string of length 2.)

- If 'cdata' is an enum, returns the value of the enumerator as a string.
  If the value is out of range, it is simply returned as the stringified
  integer.

**ffi.unpack(cdata, length)**: unpacks an array of C data of the given
length, returning a Python string/unicode/list.  The 'cdata' should be
a pointer; if it is an array it is first converted to the pointer
type.  *New in version 1.6.*

- If 'cdata' is a pointer to 'char', returns a byte string.  It does
  not stop at the first null.  (An equivalent way to do that is
  ``ffi.buffer(cdata, length)[:]``.)

- If 'cdata' is a pointer to 'wchar_t', returns a unicode string.
  ('length' is measured in number of wchar_t; it is not the size in
  bytes.)

- If 'cdata' is a pointer to anything else, returns a list, of the
  given 'length'.  (A slower way to do that is ``[cdata[i] for i in
  range(length)]``.)


.. _ffi-buffer:
.. _ffi-from-buffer:

ffi.buffer(), ffi.from_buffer()
+++++++++++++++++++++++++++++++

**ffi.buffer(cdata, [size])**: return a buffer object that references
the raw C data pointed to by the given 'cdata', of 'size' bytes.  The
'cdata' must be a pointer or an array.  If unspecified, the size of the
buffer is either the size of what ``cdata`` points to, or the whole size
of the array.  Getting a buffer is useful because you can read from it
without an extra copy, or write into it to change the original value.

Here are a few examples of where buffer() would be useful:

-  use ``file.write()`` and ``file.readinto()`` with
   such a buffer (for files opened in binary mode)

-  use ``ffi.buffer(mystruct[0])[:] = socket.recv(len(buffer))`` to read
   into a struct over a socket, rewriting the contents of mystruct[0]

Remember that like in C, you can use ``array + index`` to get the pointer
to the index'th item of an array.

The returned object is not a built-in buffer nor memoryview object,
because these objects' API changes too much across Python versions.
Instead it has the following Python API (a subset of Python 2's
``buffer``):

- ``buf[:]`` or ``bytes(buf)``: fetch a copy as a regular byte string (or
  ``buf[start:end]`` for a part)

- ``buf[:] = newstr``: change the original content (or ``buf[start:end]
  = newstr``)

- ``len(buf), buf[index], buf[index] = newchar``: access as a sequence
  of characters.

The buffer object returned by ``ffi.buffer(cdata)`` keeps alive the
``cdata`` object: if it was originally an owning cdata, then its
owned memory will not be freed as long as the buffer is alive.

Python 2/3 compatibility note: you should avoid using ``str(buf)``,
because it gives inconsistent results between Python 2 and Python 3.
(This is similar to how ``str()`` gives inconsistent results on regular
byte strings).  Use ``buf[:]`` instead.

**ffi.from_buffer(python_buffer)**: return a ``<cdata 'char[]'>`` that
points to the data of the given Python object, which must support the
buffer interface.  This is the opposite of ``ffi.buffer()``.  It gives
a reference to the existing data, not a copy; for this
reason, and for PyPy compatibility, it does not work with the built-in
types str or unicode or bytearray (or buffers/memoryviews on them).
It is meant to be used on objects
containing large quantities of raw data, like ``array.array`` or numpy
arrays.  It supports both the old buffer API (in Python 2.x) and the
new memoryview API.  Note that if you pass a read-only buffer object,
you still get a regular ``<cdata 'char[]'>``; it is your responsibility
not to write there if the original buffer doesn't expect you to.
The original object is kept alive (and, in case
of memoryview, locked) as long as the cdata object returned by
``ffi.from_buffer()`` is alive.  *New in version 0.9.*


ffi.memmove()
+++++++++++++

**ffi.memmove(dest, src, n)**: copy ``n`` bytes from memory area
``src`` to memory area ``dest``.  See examples below.  Inspired by the
C functions ``memcpy()`` and ``memmove()``---like the latter, the
areas can overlap.  Each of ``dest`` and ``src`` can be either a cdata
pointer or a Python object supporting the buffer/memoryview interface.
In the case of ``dest``, the buffer/memoryview must be writable.
Unlike ``ffi.from_buffer()``, there are no restrictions on the type of
buffer.  *New in version 1.3.*  Examples:

* ``ffi.memmove(myptr, b"hello", 5)`` copies the 5 bytes of
  ``b"hello"`` to the area that ``myptr`` points to.

* ``ba = bytearray(100); ffi.memmove(ba, myptr, 100)`` copies 100
  bytes from ``myptr`` into the bytearray ``ba``.

* ``ffi.memmove(myptr + 1, myptr, 100)`` shifts 100 bytes from
  the memory at ``myptr`` to the memory at ``myptr + 1``.


.. _ffi-typeof:
.. _ffi-sizeof:
.. _ffi-alignof:

ffi.typeof(), ffi.sizeof(), ffi.alignof()
+++++++++++++++++++++++++++++++++++++++++

**ffi.typeof("C type" or cdata object)**: return an object of type
``<ctype>`` corresponding to the parsed string, or to the C type of the
cdata instance.  Usually you don't need to call this function or to
explicitly manipulate ``<ctype>`` objects in your code: any place that
accepts a C type can receive either a string or a pre-parsed ``ctype``
object (and because of caching of the string, there is no real
performance difference).  It can still be useful in writing typechecks,
e.g.:

.. code-block:: python
  
    def myfunction(ptr):
        assert ffi.typeof(ptr) is ffi.typeof("foo_t*")
        ...

Note also that the mapping from strings like ``"foo_t*"`` to the
``<ctype>`` objects is stored in some internal dictionary.  This
guarantees that there is only one ``<ctype 'foo_t *'>`` object, so you
can use the ``is`` operator to compare it.  The downside is that the
dictionary entries are immortal for now.  In the future, we may add
transparent reclamation of old, unused entries.  In the meantime, note
that using strings like ``"int[%d]" % length`` to name a type will
create many immortal cached entries if called with many different
lengths.

**ffi.sizeof("C type" or cdata object)**: return the size of the
argument in bytes.  The argument can be either a C type, or a cdata object,
like in the equivalent ``sizeof`` operator in C.

**ffi.alignof("C type")**: return the natural alignment size in bytes of
the argument.  Corresponds to the ``__alignof__`` operator in GCC.


.. _ffi-offsetof:
.. _ffi-addressof:

ffi.offsetof(), ffi.addressof()
+++++++++++++++++++++++++++++++

**ffi.offsetof("C struct or array type", \*fields_or_indexes)**: return the
offset within the struct of the given field.  Corresponds to ``offsetof()``
in C.

*New in version 0.9:*
You can give several field names in case of nested structures.  You
can also give numeric values which correspond to array items, in case
of a pointer or array type.  For example, ``ffi.offsetof("int[5]", 2)``
is equal to the size of two integers, as is ``ffi.offsetof("int *", 2)``.


**ffi.addressof(cdata, \*fields_or_indexes)**: limited equivalent to
the '&' operator in C:

1. ``ffi.addressof(<cdata 'struct-or-union'>)`` returns a cdata that
is a pointer to this struct or union.  The returned pointer is only
valid as long as the original ``cdata`` object is; be sure to keep it
alive if it was obtained directly from ``ffi.new()``.

2. ``ffi.addressof(<cdata>, field-or-index...)`` returns the address
of a field or array item inside the given structure or array.  In case
of nested structures or arrays, you can give more than one field or
index to look recursively.  Note that ``ffi.addressof(array, index)``
can also be expressed as ``array + index``: this is true both in CFFI
and in C, where ``&array[index]`` is just ``array + index``.

3. ``ffi.addressof(<library>, "name")`` returns the address of the
named function or global variable from the given library object.
*New in version 1.1:* for functions, it returns a regular cdata
object containing a pointer to the function.

Note that the case 1. cannot be used to take the address of a
primitive or pointer, but only a struct or union.  It would be
difficult to implement because only structs and unions are internally
stored as an indirect pointer to the data.  If you need a C int whose
address can be taken, use ``ffi.new("int[1]")`` in the first place;
similarly, for a pointer, use ``ffi.new("foo_t *[1]")``.


.. _ffi-cdata:
.. _ffi-ctype:

ffi.CData, ffi.CType
++++++++++++++++++++

**ffi.CData, ffi.CType**: the Python type of the objects referred to
as ``<cdata>`` and ``<ctype>`` in the rest of this document.  Note
that some cdata objects may be actually of a subclass of
``ffi.CData``, and similarly with ctype, so you should check with
``if isinstance(x, ffi.CData)``.  Also, ``<ctype>`` objects have
a number of attributes for introspection: ``kind`` and ``cname`` are
always present, and depending on the kind they may also have
``item``, ``length``, ``fields``, ``args``, ``result``, ``ellipsis``,
``abi``, ``elements`` and ``relements``.


ffi.gc()
++++++++

**ffi.gc(cdata, destructor)**: return a new cdata object that points to the
same data.  Later, when this new cdata object is garbage-collected,
``destructor(old_cdata_object)`` will be called.  Example of usage:
``ptr = ffi.gc(lib.malloc(42), lib.free)``.  Note that like objects
returned by ``ffi.new()``, the returned pointer objects have *ownership*,
which means the destructor is called as soon as *this* exact returned
object is garbage-collected.

**ffi.gc(ptr, None)**: removes the ownership on a object returned by a
regular call to ``ffi.gc``, and no destructor will be called when it
is garbage-collected.  The object is modified in-place, and the
function returns ``None``.  *New in version 1.7: ffi.gc(ptr, None)*

Note that this should be avoided for large memory allocations or
for limited resources.  This is particularly true on PyPy: its GC does
not know how much memory or how many resources the returned ``ptr``
holds.  It will only run its GC when enough memory it knows about has
been allocated (and thus run the destructor possibly later than you
would expect).  Moreover, the destructor is called in whatever thread
PyPy is at that moment, which might be a problem for some C libraries.
In these cases, consider writing a wrapper class with custom ``__enter__()``
and ``__exit__()`` methods, allocating and freeing the C data at known
points in time, and using it in a ``with`` statement.


.. _ffi-new-handle:
.. _ffi-from-handle:

ffi.new_handle(), ffi.from_handle()
+++++++++++++++++++++++++++++++++++

**ffi.new_handle(python_object)**: return a non-NULL cdata of type
``void *`` that contains an opaque reference to ``python_object``.  You
can pass it around to C functions or store it into C structures.  Later,
you can use **ffi.from_handle(p)** to retrieve the original
``python_object`` from a value with the same ``void *`` pointer.
*Calling ffi.from_handle(p) is invalid and will likely crash if
the cdata object returned by new_handle() is not kept alive!*

(In case you are wondering, this ``void *`` is not the ``PyObject *``
pointer.  This wouldn't make sense on PyPy anyway.)

The ``ffi.new_handle()/from_handle()`` functions *conceptually* work
like this:

* ``new_handle()`` returns cdata objects that contains references to
  the Python objects; we call them collectively the "handle" cdata
  objects.  The ``void *`` value in these handle cdata objects are
  random but unique.

* ``from_handle(p)`` searches all live "handle" cdata objects for the
  one that has the same value ``p`` as its ``void *`` value.  It then
  returns the Python object referenced by that handle cdata object.
  If none is found, you get "undefined behavior" (i.e. crashes).

The "handle" cdata object keeps the Python object alive, similar to
how ``ffi.new()`` returns a cdata object that keeps a piece of memory
alive.  If the handle cdata object *itself* is not alive any more,
then the association ``void * -> python_object`` is dead and
``from_handle()`` will crash.

*New in version 1.4:* two calls to ``new_handle(x)`` are guaranteed to
return cdata objects with different ``void *`` values, even with the
same ``x``.  This is a useful feature that avoids issues with unexpected
duplicates in the following trick: if you need to keep alive the
"handle" until explicitly asked to free it, but don't have a natural
Python-side place to attach it to, then the easiest is to ``add()`` it
to a global set.  It can later be removed from the set by
``global_set.discard(p)``, with ``p`` any cdata object whose ``void *``
value compares equal.


.. _ffi-dlopen:
.. _ffi-dlclose:

ffi.dlopen(), ffi.dlclose()
+++++++++++++++++++++++++++

**ffi.dlopen(libpath, [flags])**: opens and returns a "handle" to a
dynamic library, as a ``<lib>`` object.  See `Preparing and
Distributing modules`_.

**ffi.dlclose(lib)**: explicitly closes a ``<lib>`` object returned
by ``ffi.dlopen()``.

**ffi.RLTD_...**: constants: flags for ``ffi.dlopen()``.


ffi.new_allocator()
+++++++++++++++++++

**ffi.new_allocator(alloc=None, free=None, should_clear_after_alloc=True)**:
returns a new allocator.  An "allocator" is a callable that behaves like
``ffi.new()`` but uses the provided low-level ``alloc`` and ``free``
functions.  *New in version 1.2.*

``alloc()`` is invoked with the size as sole argument.  If it returns
NULL, a MemoryError is raised.  Later, if ``free`` is not None, it will
be called with the result of ``alloc()`` as argument.  Both can be either
Python function or directly C functions.  If only ``free`` is None, then no
free function is called.  If both ``alloc`` and ``free`` are None, the
default alloc/free combination is used.  (In other words, the call
``ffi.new(*args)`` is equivalent to ``ffi.new_allocator()(*args)``.)

If ``should_clear_after_alloc`` is set to False, then the memory
returned by ``alloc()`` is assumed to be already cleared (or you are
fine with garbage); otherwise CFFI will clear it.


ffi.init_once()
+++++++++++++++

**ffi.init_once(function, tag)**: run ``function()`` once.  The
``tag`` should be a primitive object, like a string, that identifies
the function: ``function()`` is only called the first time we see the
``tag``.  The return value of ``function()`` is remembered and
returned by the current and all future ``init_once()`` with the same
tag.  If ``init_once()`` is called from multiple threads in parallel,
all calls block until the execution of ``function()`` is done.  If
``function()`` raises an exception, it is propagated and nothing is
cached (i.e. ``function()`` will be called again, in case we catch the
exception and try ``init_once()`` again).  *New in version 1.4.*

Example::

    from _xyz_cffi import ffi, lib

    def initlib():
        lib.init_my_library()

    def make_new_foo():
        ffi.init_once(initlib, "init")
        return lib.make_foo()

``init_once()`` is optimized to run very quickly if ``function()`` has
already been called.  (On PyPy, the cost is zero---the JIT usually
removes everything in the machine code it produces.)

*Note:* one motivation__ for ``init_once()`` is the CPython notion of
"subinterpreters" in the embedded case.  If you are using the
out-of-line API mode, ``function()`` is called only once even in the
presence of multiple subinterpreters, and its return value is shared
among all subinterpreters.  The goal is to mimic the way traditional
CPython C extension modules have their init code executed only once in
total even if there are subinterpreters.  In the example above, the C
function ``init_my_library()`` is called once in total, not once per
subinterpreter.  For this reason, avoid Python-level side-effects in
``function()`` (as they will only be applied in the first
subinterpreter to run); instead, return a value, as in the following
example::

   def init_get_max():
       return lib.initialize_once_and_get_some_maximum_number()

   def process(i):
       if i > ffi.init_once(init_get_max, "max"):
           raise IndexError("index too large!")
       ...

.. __: https://bitbucket.org/cffi/cffi/issues/233/


.. _ffi-getctype:
.. _ffi-list-types:

ffi.getctype(), ffi.list_types()
++++++++++++++++++++++++++++++++

**ffi.getctype("C type" or <ctype>, extra="")**: return the string
representation of the given C type.  If non-empty, the "extra" string is
appended (or inserted at the right place in more complicated cases); it
can be the name of a variable to declare, or an extra part of the type
like ``"*"`` or ``"[5]"``.  For example
``ffi.getctype(ffi.typeof(x), "*")`` returns the string representation
of the C type "pointer to the same type than x"; and
``ffi.getctype("char[80]", "a") == "char a[80]"``.

**ffi.list_types()**: Returns the user type names known to this FFI
instance.  This returns a tuple containing three lists of names:
``(typedef_names, names_of_structs, names_of_unions)``.  *New in
version 1.6.*


.. _`Preparing and Distributing modules`: cdef.html#loading-libraries


Conversions
-----------

This section documents all the conversions that are allowed when
*writing into* a C data structure (or passing arguments to a function
call), and *reading from* a C data structure (or getting the result of a
function call).  The last column gives the type-specific operations
allowed.

+---------------+------------------------+------------------+----------------+
|    C type     |   writing into         | reading from     |other operations|
+===============+========================+==================+================+
|   integers    | an integer or anything | a Python int or  | int()          |
|   and enums   | on which int() works   | long, depending  |                |
|   `(*****)`   | (but not a float!).    | on the type      |                |
|               | Must be within range.  |                  |                |
+---------------+------------------------+------------------+----------------+
|   ``char``    | a string of length 1   | a string of      | int()          |
|               | or another <cdata char>| length 1         |                |
+---------------+------------------------+------------------+----------------+
|  ``wchar_t``  | a unicode of length 1  | a unicode of     |                |
|               | (or maybe 2 if         | length 1         | int()          |
|               | surrogates) or         | (or maybe 2 if   |                |
|               | another <cdata wchar_t>| surrogates)      |                |
+---------------+------------------------+------------------+----------------+
|  ``float``,   | a float or anything on | a Python float   | float(), int() |
|  ``double``   | which float() works    |                  |                |
+---------------+------------------------+------------------+----------------+
|``long double``| another <cdata> with   | a <cdata>, to    | float(), int() |
|               | a ``long double``, or  | avoid loosing    |                |
|               | anything on which      | precision `(***)`|                |
|               | float() works          |                  |                |
+---------------+------------------------+------------------+----------------+
|  pointers     | another <cdata> with   | a <cdata>        |``[]`` `(****)`,|
|               | a compatible type (i.e.|                  |``+``, ``-``,   |
|               | same type or ``char*`` |                  |bool()          |
|               | or ``void*``, or as an |                  |                |
|               | array instead) `(*)`   |                  |                |
+---------------+------------------------+                  |                |
|  ``void *``,  | another <cdata> with   |                  |                |
|  ``char *``   | any pointer or array   |                  |                |
|               | type                   |                  |                |
+---------------+------------------------+                  +----------------+
|  pointers to  | same as pointers       |                  | ``[]``, ``+``, |
|  structure or |                        |                  | ``-``, bool(), |
|  union        |                        |                  | and read/write |
|               |                        |                  | struct fields  |
+---------------+------------------------+                  +----------------+
| function      | same as pointers       |                  | bool(),        |
| pointers      |                        |                  | call `(**)`    |
+---------------+------------------------+------------------+----------------+
|  arrays       | a list or tuple of     | a <cdata>        |len(), iter(),  |
|               | items                  |                  |``[]`` `(****)`,|
|               |                        |                  |``+``, ``-``    |
+---------------+------------------------+                  +----------------+
|  ``char[]``   | same as arrays, or a   |                  | len(), iter(), |
|               | Python string          |                  | ``[]``, ``+``, |
|               |                        |                  | ``-``          |
+---------------+------------------------+                  +----------------+
| ``wchar_t[]`` | same as arrays, or a   |                  | len(), iter(), |
|               | Python unicode         |                  | ``[]``,        |
|               |                        |                  | ``+``, ``-``   |
|               |                        |                  |                |
+---------------+------------------------+------------------+----------------+
| structure     | a list or tuple or     | a <cdata>        | read/write     |
|               | dict of the field      |                  | fields         |
|               | values, or a same-type |                  |                |
|               | <cdata>                |                  |                |
+---------------+------------------------+                  +----------------+
| union         | same as struct, but    |                  | read/write     |
|               | with at most one field |                  | fields         |
+---------------+------------------------+------------------+----------------+

`(*)` ``item *`` is ``item[]`` in function arguments:

   In a function declaration, as per the C standard, a ``item *``
   argument is identical to a ``item[]`` argument (and ``ffi.cdef()``
   doesn't record the difference).  So when you call such a function,
   you can pass an argument that is accepted by either C type, like
   for example passing a Python string to a ``char *`` argument
   (because it works for ``char[]`` arguments) or a list of integers
   to a ``int *`` argument (it works for ``int[]`` arguments).  Note
   that even if you want to pass a single ``item``, you need to
   specify it in a list of length 1; for example, a ``struct point_s
   *`` argument might be passed as ``[[x, y]]`` or ``[{'x': 5, 'y':
   10}]``.

   As an optimization, the CPython version of CFFI assumes that a
   function with a ``char *`` argument to which you pass a Python
   string will not actually modify the array of characters passed in,
   and so passes directly a pointer inside the Python string object.
   (PyPy might in the future do the same, but it is harder because
   strings are not naturally zero-terminated in PyPy.)

`(**)` C function calls are done with the GIL released.

   Note that we assume that the called functions are *not* using the
   Python API from Python.h.  For example, we don't check afterwards
   if they set a Python exception.  You may work around it, but mixing
   CFFI with ``Python.h`` is not recommended.  (If you do that, on
   PyPy and on some platforms like Windows, you may need to explicitly
   link to ``libpypy-c.dll`` to access the CPython C API compatibility
   layer; indeed, CFFI-generated modules on PyPy don't link to
   ``libpypy-c.dll`` on their own.  But really, don't do that in the
   first place.)

`(***)` ``long double`` support:

   We keep ``long double`` values inside a cdata object to avoid
   loosing precision.  Normal Python floating-point numbers only
   contain enough precision for a ``double``.  If you really want to
   convert such an object to a regular Python float (i.e. a C
   ``double``), call ``float()``.  If you need to do arithmetic on
   such numbers without any precision loss, you need instead to define
   and use a family of C functions like ``long double add(long double
   a, long double b);``.

`(****)` Slicing with ``x[start:stop]``:

   Slicing is allowed, as long as you specify explicitly both ``start``
   and ``stop`` (and don't give any ``step``).  It gives a cdata
   object that is a "view" of all items from ``start`` to ``stop``.
   It is a cdata of type "array" (so e.g. passing it as an argument to a
   C function would just convert it to a pointer to the ``start`` item).
   As with indexing, negative bounds mean really negative indices, like in
   C.  As for slice assignment, it accepts any iterable, including a list
   of items or another array-like cdata object, but the length must match.
   (Note that this behavior differs from initialization: e.g. you can
   say ``chararray[10:15] = "hello"``, but the assigned string must be of
   exactly the correct length; no implicit null character is added.)

`(*****)` Enums are handled like ints:

   Like C, enum types are mostly int types (unsigned or signed, int or
   long; note that GCC's first choice is unsigned).  Reading an enum
   field of a structure, for example, returns you an integer.  To
   compare their value symbolically, use code like ``if x.field ==
   lib.FOO``.  If you really want to get their value as a string, use
   ``ffi.string(ffi.cast("the_enum_type", x.field))``.

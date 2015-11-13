
static PyObject *_ffi_call_python_decorator(PyObject *outer_args, PyObject *fn)
{
#if PY_MAJOR_VERSION >= 3
#  error review!
#endif
    char *s;
    PyObject *error, *onerror, *infotuple, *x;
    int index;
    const struct _cffi_global_s *g;
    struct _cffi_callpy_s *callpy;
    CTypeDescrObject *ct;
    FFIObject *ffi;
    builder_c_t *types_builder;
    PyObject *name = NULL;

    if (!PyArg_ParseTuple(outer_args, "OzOO", &ffi, &s, &error, &onerror))
        return NULL;

    if (s == NULL) {
        PyObject *name = PyObject_GetAttrString(fn, "__name__");
        if (name == NULL)
            return NULL;
        s = PyString_AsString(name);
        if (s == NULL) {
            Py_DECREF(name);
            return NULL;
        }
    }

    types_builder = &ffi->types_builder;
    index = search_in_globals(&types_builder->ctx, s, strlen(s));
    if (index < 0)
        goto not_found;
    g = &types_builder->ctx.globals[index];
    if (_CFFI_GETOP(g->type_op) != _CFFI_OP_CALL_PYTHON)
        goto not_found;
    Py_XDECREF(name);

    ct = realize_c_type(types_builder, types_builder->ctx.types,
                        _CFFI_GETARG(g->type_op));
    if (ct == NULL)
        return NULL;

    infotuple = prepare_callback_info_tuple(ct, fn, error, onerror, 0);
    if (infotuple == NULL) {
        Py_DECREF(ct);
        return NULL;
    }

    /* attach infotuple to reserved1, where it will stay forever
       unless a new version is attached later */
    callpy = (struct _cffi_callpy_s *)g->address;
    x = (PyObject *)callpy->reserved1;
    callpy->reserved1 = (void *)infotuple;
    Py_XDECREF(x);

    /* return a cdata of type function-pointer, equal to the one
       obtained by reading 'lib.bar' (see lib_obj.c) */
    x = convert_to_object((char *)&g->size_or_direct_fn, ct);
    Py_DECREF(ct);
    return x;

 not_found:
    PyErr_Format(FFIError, "ffi.call_python('%s'): name not found as a "
                           "CFFI_CALL_PYTHON line from the cdef", s);
    Py_XDECREF(name);
    return NULL;
}


static void _cffi_call_python(struct _cffi_callpy_s *callpy, char *args)
{
    /* Invoked by the helpers generated from CFFI_CALL_PYTHON in the cdef.

       'callpy' is a static structure that describes which of the
       CFFI_CALL_PYTHON is called.  It has got fields 'name' and
       'type_index' describing the function, and more reserved fields
       that are initially zero.  These reserved fields are set up by
       ffi.call_python(), which invokes init_call_python() below.

       'args' is a pointer to an array of 8-byte entries.  Each entry
       contains an argument.  If an argument is less than 8 bytes, only
       the part at the beginning of the entry is initialized.  If an
       argument is 'long double' or a struct/union, then it is passed
       by reference.

       'args' is also used as the place to write the result to.  In all
       cases, 'args' is at least 8 bytes in size.
    */
    save_errno();
    {
#ifdef WITH_THREAD
    PyGILState_STATE state = PyGILState_Ensure();
#endif

    if (callpy->reserved1 == NULL) {
        /* not initialized! */
        PyObject *f = PySys_GetObject("stderr");
        if (f != NULL) {
            PyFile_WriteString("CFFI_CALL_PYTHON: function ", f);
            PyFile_WriteString(callpy->name, f);
            PyFile_WriteString("() called, but no code was attached "
                               "to it yet with ffi.call_python('", f);
            PyFile_WriteString(callpy->name, f);
            PyFile_WriteString("').  Returning 0.\n", f);
        }
        memset(args, 0, callpy->size_of_result);
    }
    else {
        general_invoke_callback(0, args, args, callpy->reserved1);
    }

#ifdef WITH_THREAD
    PyGILState_Release(state);
#endif
    }
    restore_errno();
}

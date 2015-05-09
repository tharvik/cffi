
#include "parse_c_type.c"
#include "realize_c_type.c"

typedef struct FFIObject_s FFIObject;
typedef struct LibObject_s LibObject;

static PyTypeObject FFI_Type;   /* forward */
static PyTypeObject Lib_Type;   /* forward */

#include "ffi_obj.c"
#include "cglob.c"
#include "cgc.c"
#include "lib_obj.c"


static int init_ffi_lib(PyObject *m)
{
    PyObject *x;

    if (PyType_Ready(&FFI_Type) < 0)
        return -1;
    if (PyType_Ready(&Lib_Type) < 0)
        return -1;
    if (init_global_types_dict(FFI_Type.tp_dict) < 0)
        return -1;

    FFIError = PyErr_NewException("ffi.error", NULL, NULL);
    if (FFIError == NULL)
        return -1;
    if (PyDict_SetItemString(FFI_Type.tp_dict, "error", FFIError) < 0)
        return -1;
    if (PyDict_SetItemString(FFI_Type.tp_dict, "CType",
                             (PyObject *)&CTypeDescr_Type) < 0)
        return -1;
    if (PyDict_SetItemString(FFI_Type.tp_dict, "CData",
                             (PyObject *)&CData_Type) < 0)
        return -1;

    x = (PyObject *)&FFI_Type;
    Py_INCREF(x);
    if (PyModule_AddObject(m, "FFI", x) < 0)
        return -1;
    x = (PyObject *)&Lib_Type;
    Py_INCREF(x);
    if (PyModule_AddObject(m, "Lib", x) < 0)
        return -1;

    return 0;
}

static int make_included_tuples(char *module_name,
                                const char *const *ctx_includes,
                                PyObject **included_ffis,
                                PyObject **included_libs)
{
    Py_ssize_t num = 0;
    const char *const *p_include;

    if (ctx_includes == NULL)
        return 0;

    for (p_include = ctx_includes; *p_include; p_include++) {
        num++;
    }
    *included_ffis = PyTuple_New(num);
    *included_libs = PyTuple_New(num);
    if (*included_ffis == NULL || *included_libs == NULL)
        goto error;

    num = 0;
    for (p_include = ctx_includes; *p_include; p_include++) {
        PyObject *included_ffi, *included_lib;
        PyObject *m = PyImport_ImportModule(*p_include);
        if (m == NULL)
            goto import_error;

        included_ffi = PyObject_GetAttrString(m, "ffi");
        PyTuple_SET_ITEM(*included_ffis, num, included_ffi);

        included_lib = (included_ffi == NULL) ? NULL :
                       PyObject_GetAttrString(m, "lib");
        PyTuple_SET_ITEM(*included_libs, num, included_lib);

        Py_DECREF(m);
        if (included_lib == NULL)
            goto import_error;

        if (!FFIObject_Check(included_ffi) ||
            !LibObject_Check(included_lib))
            goto import_error;
        num++;
    }
    return 0;

 import_error:
    PyErr_Format(PyExc_ImportError,
                 "while loading %.200s: failed to import ffi, lib from %.200s",
                 module_name, *p_include);
 error:
    Py_XDECREF(*included_ffis); *included_ffis = NULL;
    Py_XDECREF(*included_libs); *included_libs = NULL;
    return -1;
}

static PyObject *_cffi_init_module(char *module_name,
                                   const struct _cffi_type_context_s *ctx)
{
    PyObject *m;
    FFIObject *ffi;
    LibObject *lib;

#if PY_MAJOR_VERSION >= 3
    /* note: the module_def leaks, but anyway the C extension module cannot
       be unloaded */
    struct PyModuleDef *module_def, local_module_def = {
        PyModuleDef_HEAD_INIT,
        module_name,
        NULL,
        -1,
        NULL, NULL, NULL, NULL, NULL
    };
    module_def = PyMem_Malloc(sizeof(struct PyModuleDef));
    if (module_def == NULL)
        return PyErr_NoMemory();
    *module_def = local_module_def;
    m = PyModule_Create(module_def);
#else
    m = Py_InitModule(module_name, NULL);
#endif
    if (m == NULL)
        return NULL;

    ffi = ffi_internal_new(&FFI_Type, ctx);
    Py_XINCREF(ffi);    /* make the ffi object really immortal */
    if (ffi == NULL || PyModule_AddObject(m, "ffi", (PyObject *)ffi) < 0)
        return NULL;

    lib = lib_internal_new(ffi->types_builder, module_name);
    if (lib == NULL || PyModule_AddObject(m, "lib", (PyObject *)lib) < 0)
        return NULL;

    if (make_included_tuples(module_name, ctx->includes,
                             &ffi->types_builder->included_ffis,
                             &lib->l_includes) < 0)
        return NULL;

    return m;
}

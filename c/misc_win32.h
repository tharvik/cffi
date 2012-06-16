
/************************************************************/
/* errno and GetLastError support */

struct cffi_errno_s {
    int saved_errno;
    int saved_lasterror;
};

static DWORD cffi_tls_index;

static void init_errno(void)
{
    cffi_tls_index = TlsAlloc();
    if (cffi_tls_index == TLS_OUT_OF_INDEXES)
        PyErr_SetString(PyExc_WindowsError, "TlsAlloc() failed");
}

static struct cffi_errno_s *_geterrno_object(void)
{
    LPVOID p = TlsGetValue(cffi_tls_index);

    if (p == NULL) {
        p = PyMem_Malloc(sizeof(struct cffi_errno_s));
        if (p == NULL)
            return NULL;
        memset(p, 0, sizeof(struct cffi_errno_s));
        TlsSetValue(cffi_tls_index, p);
    }
    return (struct cffi_errno_s *)p;
}

static void save_errno(void)
{
    int current_err = errno;
    int current_lasterr = GetLastError();
    struct cffi_errno_s *p;

    p = _geterrno_object();
    if (p != NULL) {
        p->saved_errno = current_err;
        p->saved_lasterror = current_lasterr;
    }
    /* else: cannot report the error */
}

static void restore_errno(void)
{
    struct cffi_errno_s *p;

    p = _geterrno_object();
    if (p != NULL) {
        SetLastError(p->saved_lasterror);
        errno = p->saved_errno;
    }
    /* else: cannot report the error */
}


/************************************************************/
/* Emulate dlopen()&co. from the Windows API */

#define RTLD_DEFAULT   NULL
#define RTLD_LAZY      0

static void *dlopen(const char *filename, int flag)
{
    return (void *)LoadLibrary(filename);
}

static void *dlsym(void *handle, const char *symbol)
{
    if (handle == RTLD_DEFAULT) {
        static const char *standard_dlls[] = {
            "kernel32.dll",
            "user32.dll",
            "gdi32.dll",
            NULL
        };
        const char **p;
        void *result;

        for (p = standard_dlls; *p != NULL; p++) {
            result = GetProcAddress(GetModuleHandle(*p), symbol);
            if (result)
                return result;
        }
        return NULL;
    }
    else {
        return GetProcAddress((HMODULE)handle, symbol);
    }
}

static void dlclose(void *handle)
{
    FreeLibrary((HMODULE)handle);
}


/************************************************************/
/* obscure */

#define ffi_prep_closure(a,b,c,d)  ffi_prep_closure_loc(a,b,c,d,a)

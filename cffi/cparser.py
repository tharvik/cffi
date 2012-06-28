
from . import api, model
import pycparser, weakref, re

_r_comment = re.compile(r"/\*.*?\*/|//.*?$", re.DOTALL | re.MULTILINE)
_r_define  = re.compile(r"^\s*#\s*define\s+([A-Za-z_][A-Za-z_0-9]*)\s+(.*?)$",
                        re.MULTILINE)
_r_partial_enum = re.compile(r"\.\.\.\s*\}")
_r_enum_dotdotdot = re.compile(r"__dotdotdot\d+__$")
_r_partial_array = re.compile(r"\[\s*\.\.\.\s*\]")
_parser_cache = None

def _get_parser():
    global _parser_cache
    if _parser_cache is None:
        _parser_cache = pycparser.CParser()
    return _parser_cache

def _preprocess(csource):
    # Remove comments.  NOTE: this only work because the cdef() section
    # should not contain any string literal!
    csource = _r_comment.sub(' ', csource)
    # Remove the "#define FOO x" lines
    macros = {}
    for match in _r_define.finditer(csource):
        macroname, macrovalue = match.groups()
        macros[macroname] = macrovalue
    csource = _r_define.sub('', csource)
    # Replace "[...]" with "[__dotdotdotarray__]"
    csource = _r_partial_array.sub('[__dotdotdotarray__]', csource)
    # Replace "...}" with "__dotdotdotNUM__}".  This construction should
    # occur only at the end of enums; at the end of structs we have "...;}"
    # and at the end of vararg functions "...);"
    matches = list(_r_partial_enum.finditer(csource))
    for number, match in enumerate(reversed(matches)):
        p = match.start()
        assert csource[p:p+3] == '...'
        csource = '%s __dotdotdot%d__ %s' % (csource[:p], number,
                                             csource[p+3:])
    # Replace all remaining "..." with the same name, "__dotdotdot__",
    # which is declared with a typedef for the purpose of C parsing.
    return csource.replace('...', ' __dotdotdot__ '), macros

class Parser(object):
    def __init__(self):
        self._declarations = {}
        self._anonymous_counter = 0
        self._structnode2type = weakref.WeakKeyDictionary()

    def _parse(self, csource):
        # XXX: for more efficiency we would need to poke into the
        # internals of CParser...  the following registers the
        # typedefs, because their presence or absence influences the
        # parsing itself (but what they are typedef'ed to plays no role)
        csourcelines = []
        for name in sorted(self._declarations):
            if name.startswith('typedef '):
                csourcelines.append('typedef int %s;' % (name[8:],))
        csourcelines.append('typedef int __dotdotdot__;')
        csource, macros = _preprocess(csource)
        csourcelines.append(csource)
        csource = '\n'.join(csourcelines)
        ast = _get_parser().parse(csource)
        return ast, macros

    def parse(self, csource):
        ast, macros = self._parse(csource)
        # add the macros
        for key, value in macros.items():
            value = value.strip()
            if value != '...':
                raise api.CDefError('only supports the syntax "#define '
                                    '%s ..." for now (literally)' % key)
            self._declare('macro ' + key, value)
        # find the first "__dotdotdot__" and use that as a separator
        # between the repeated typedefs and the real csource
        iterator = iter(ast.ext)
        for decl in iterator:
            if decl.name == '__dotdotdot__':
                break
        #
        for decl in iterator:
            if isinstance(decl, pycparser.c_ast.Decl):
                self._parse_decl(decl)
            elif isinstance(decl, pycparser.c_ast.Typedef):
                if not decl.name:
                    raise api.CDefError("typedef does not declare any name",
                                        decl)
                if (isinstance(decl.type.type, pycparser.c_ast.IdentifierType)
                        and decl.type.type.names == ['__dotdotdot__']):
                    realtype = model.unknown_type(decl.name)
                else:
                    realtype = self._get_type(decl.type, name=decl.name)
                self._declare('typedef ' + decl.name, realtype)
            else:
                raise api.CDefError("unrecognized construct", decl)

    def _parse_decl(self, decl):
        node = decl.type
        if isinstance(node, pycparser.c_ast.FuncDecl):
            tp = self._get_type(node, name=decl.name)
            assert isinstance(tp, model.RawFunctionType)
            tp = self._get_type_pointer(tp)
            self._declare('function ' + decl.name, tp)
        else:
            if isinstance(node, pycparser.c_ast.Struct):
                # XXX do we need self._declare in any of those?
                if node.decls is not None:
                    self._get_struct_or_union_type('struct', node)
            elif isinstance(node, pycparser.c_ast.Union):
                if node.decls is not None:
                    self._get_struct_or_union_type('union', node)
            elif isinstance(node, pycparser.c_ast.Enum):
                if node.values is not None:
                    self._get_enum_type(node)
            elif not decl.name:
                raise api.CDefError("construct does not declare any variable",
                                    decl)
            #
            if decl.name:
                tp = self._get_type(node)
                if self._is_constant_declaration(node):
                    self._declare('constant ' + decl.name, tp)
                else:
                    self._declare('variable ' + decl.name, tp)

    def parse_type(self, cdecl, force_pointer=False,
                   consider_function_as_funcptr=False):
        ast, macros = self._parse('void __dummy(%s);' % cdecl)
        assert not macros
        typenode = ast.ext[-1].type.args.params[0].type
        type = self._get_type(typenode, force_pointer=force_pointer)
        if consider_function_as_funcptr:
            if isinstance(type, model.RawFunctionType):
                type = self._get_type_pointer(type)
        return type

    def _declare(self, name, obj):
        if name in self._declarations:
            if self._declarations[name] is obj:
                return
            raise api.FFIError("multiple declarations of %s" % (name,))
        assert name != '__dotdotdot__'
        self._declarations[name] = obj

    def _get_type_pointer(self, type, const=False):
        if isinstance(type, model.RawFunctionType):
            return model.FunctionPtrType(type.args, type.result, type.ellipsis)
        if const:
            return model.ConstPointerType(type)
        return model.PointerType(type)

    def _get_type(self, typenode, convert_array_to_pointer=False,
                  force_pointer=False, name=None, partial_length_ok=False):
        # first, dereference typedefs, if we have it already parsed, we're good
        if (isinstance(typenode, pycparser.c_ast.TypeDecl) and
            isinstance(typenode.type, pycparser.c_ast.IdentifierType) and
            len(typenode.type.names) == 1 and
            ('typedef ' + typenode.type.names[0]) in self._declarations):
            type = self._declarations['typedef ' + typenode.type.names[0]]
            if isinstance(type, model.ArrayType):
                if convert_array_to_pointer:
                    return type.item
            else:
                if force_pointer:
                    return self._get_type_pointer(type)
            return type
        #
        if isinstance(typenode, pycparser.c_ast.ArrayDecl):
            # array type
            if convert_array_to_pointer:
                return self._get_type_pointer(self._get_type(typenode.type))
            if typenode.dim is None:
                length = None
            else:
                length = self._parse_constant(
                    typenode.dim, partial_length_ok=partial_length_ok)
            return model.ArrayType(self._get_type(typenode.type), length)
        #
        if force_pointer:
            return model.PointerType(self._get_type(typenode))
        #
        if isinstance(typenode, pycparser.c_ast.PtrDecl):
            # pointer type
            const = (isinstance(typenode.type, pycparser.c_ast.TypeDecl)
                     and 'const' in typenode.type.quals)
            return self._get_type_pointer(self._get_type(typenode.type), const)
        #
        if isinstance(typenode, pycparser.c_ast.TypeDecl):
            type = typenode.type
            if isinstance(type, pycparser.c_ast.IdentifierType):
                # assume a primitive type.  get it from .names, but reduce
                # synonyms to a single chosen combination
                names = list(type.names)
                if names == ['signed'] or names == ['unsigned']:
                    names.append('int')
                if names[0] == 'signed' and names != ['signed', 'char']:
                    names.pop(0)
                if (len(names) > 1 and names[-1] == 'int'
                        and names != ['unsigned', 'int']):
                    names.pop()
                ident = ' '.join(names)
                if ident == 'void':
                    return model.void_type
                if ident == '__dotdotdot__':
                    raise api.FFIError('bad usage of "..."')
                return model.PrimitiveType(ident)
            #
            if isinstance(type, pycparser.c_ast.Struct):
                # 'struct foobar'
                return self._get_struct_or_union_type('struct', type, name)
            #
            if isinstance(type, pycparser.c_ast.Union):
                # 'union foobar'
                return self._get_struct_or_union_type('union', type, name)
            #
            if isinstance(type, pycparser.c_ast.Enum):
                # 'enum foobar'
                return self._get_enum_type(type)
        #
        if isinstance(typenode, pycparser.c_ast.FuncDecl):
            # a function type
            return self._parse_function_type(typenode, name)
        #
        raise api.FFIError("bad or unsupported type declaration")

    def _parse_function_type(self, typenode, funcname=None):
        params = list(getattr(typenode.args, 'params', []))
        ellipsis = (
            len(params) > 0 and
            isinstance(params[-1].type, pycparser.c_ast.TypeDecl) and
            isinstance(params[-1].type.type,
                       pycparser.c_ast.IdentifierType) and
            params[-1].type.type.names == ['__dotdotdot__'])
        if ellipsis:
            params.pop()
        if (len(params) == 1 and
            isinstance(params[0].type, pycparser.c_ast.TypeDecl) and
            isinstance(params[0].type.type, pycparser.c_ast.IdentifierType)
                and list(params[0].type.type.names) == ['void']):
            del params[0]
        args = [self._get_type(argdeclnode.type,
                               convert_array_to_pointer=True)
                for argdeclnode in params]
        result = self._get_type(typenode.type)
        return model.RawFunctionType(tuple(args), result, ellipsis)

    def _is_constant_declaration(self, typenode, const=False):
        if isinstance(typenode, pycparser.c_ast.ArrayDecl):
            return self._is_constant_declaration(typenode.type)
        if isinstance(typenode, pycparser.c_ast.PtrDecl):
            const = 'const' in typenode.quals
            return self._is_constant_declaration(typenode.type, const)
        if isinstance(typenode, pycparser.c_ast.TypeDecl):
            return const or 'const' in typenode.quals
        return False

    def _get_struct_or_union_type(self, kind, type, name=None):
        # First, a level of caching on the exact 'type' node of the AST.
        # This is obscure, but needed because pycparser "unrolls" declarations
        # such as "typedef struct { } foo_t, *foo_p" and we end up with
        # an AST that is not a tree, but a DAG, with the "type" node of the
        # two branches foo_t and foo_p of the trees being the same node.
        # It's a bit silly but detecting "DAG-ness" in the AST tree seems
        # to be the only way to distinguish this case from two independent
        # structs.  See test_struct_with_two_usages.
        try:
            return self._structnode2type[type]
        except KeyError:
            pass
        #
        # Note that this must handle parsing "struct foo" any number of
        # times and always return the same StructType object.  Additionally,
        # one of these times (not necessarily the first), the fields of
        # the struct can be specified with "struct foo { ...fields... }".
        # If no name is given, then we have to create a new anonymous struct
        # with no caching; in this case, the fields are either specified
        # right now or never.
        #
        force_name = name
        name = type.name
        #
        # get the type or create it if needed
        if name is None:
            # 'force_name' is used to guess a more readable name for
            # anonymous structs, for the common case "typedef struct { } foo".
            if force_name is not None:
                explicit_name = '$%s' % force_name
            else:
                self._anonymous_counter += 1
                explicit_name = '$%d' % self._anonymous_counter
            tp = None
        else:
            explicit_name = name
            key = '%s %s' % (kind, name)
            tp = self._declarations.get(key, None)
        #
        if tp is None:
            if kind == 'struct':
                tp = model.StructType(explicit_name, None, None, None)
            elif kind == 'union':
                tp = model.UnionType(explicit_name, None, None, None)
            else:
                raise AssertionError("kind = %r" % (kind,))
            if name is not None:
                self._declare(key, tp)
        tp.forcename = tp.forcename or force_name
        if tp.forcename and '$' in tp.name:
            self._declare('anonymous %s' % tp.forcename, tp)
        #
        self._structnode2type[type] = tp
        #
        # is there a 'type.decls'?  If yes, then this is the place in the
        # C sources that declare the fields.  If no, then just return the
        # existing type, possibly still incomplete.
        if type.decls is None:
            return tp
        #
        if tp.fldnames is not None:
            raise api.CDefError("duplicate declaration of struct %s" % name)
        fldnames = []
        fldtypes = []
        fldbitsize = []
        for decl in type.decls:
            if (isinstance(decl.type, pycparser.c_ast.IdentifierType) and
                    ''.join(decl.type.names) == '__dotdotdot__'):
                # XXX pycparser is inconsistent: 'names' should be a list
                # of strings, but is sometimes just one string.  Use
                # str.join() as a way to cope with both.
                self._make_partial(tp)
                continue
            if decl.bitsize is None:
                bitsize = -1
            else:
                bitsize = self._parse_constant(decl.bitsize)
            self._partial_length = False
            type = self._get_type(decl.type, partial_length_ok=True)
            if self._partial_length:
                self._make_partial(tp)
            fldnames.append(decl.name)
            fldtypes.append(type)
            fldbitsize.append(bitsize)
        tp.fldnames = tuple(fldnames)
        tp.fldtypes = tuple(fldtypes)
        tp.fldbitsize = tuple(fldbitsize)
        return tp

    def _make_partial(self, tp):
        if not isinstance(tp, model.StructType):
            raise api.CDefError("%s cannot be partial" % (tp,))
        if not tp.has_c_name():
            raise api.CDefError("%s is partial but has no C name" % (tp,))
        tp.partial = True

    def _parse_constant(self, exprnode, partial_length_ok=False):
        # for now, limited to expressions that are an immediate number
        # or negative number
        if isinstance(exprnode, pycparser.c_ast.Constant):
            return int(exprnode.value)
        #
        if (isinstance(exprnode, pycparser.c_ast.UnaryOp) and
                exprnode.op == '-'):
            return -self._parse_constant(exprnode.expr)
        #
        if partial_length_ok:
            if (isinstance(exprnode, pycparser.c_ast.ID) and
                    exprnode.name == '__dotdotdotarray__'):
                self._partial_length = True
                return None
        #
        raise api.FFIError("unsupported non-constant or "
                           "not immediately constant expression")

    def _get_enum_type(self, type):
        name = type.name
        decls = type.values
        key = 'enum %s' % (name,)
        if key in self._declarations:
            return self._declarations[key]
        if decls is not None:
            enumerators = [enum.name for enum in decls.enumerators]
            partial = False
            if enumerators and _r_enum_dotdotdot.match(enumerators[-1]):
                enumerators.pop()
                partial = True
            enumerators = tuple(enumerators)
            enumvalues = []
            nextenumvalue = 0
            for enum in decls.enumerators[:len(enumerators)]:
                if enum.value is not None:
                    nextenumvalue = self._parse_constant(enum.value)
                enumvalues.append(nextenumvalue)
                nextenumvalue += 1
            enumvalues = tuple(enumvalues) 
            tp = model.EnumType(name, enumerators, enumvalues)
            tp.partial = partial
            self._declare(key, tp)
        else:   # opaque enum
            enumerators = ()
            enumvalues = ()
            tp = model.EnumType(name, (), ())
        return tp

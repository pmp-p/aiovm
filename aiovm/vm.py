#!#/usr/local/bin/python3.8_-u_-i_-B"

# A pure ** non standard ** cPython interpreter for ** standard ** cPython bytecode.
# Based on:

# pyvm2 by Paul Swartz (z3p), from http://www.twistedmatrix.com/users/z3p/
# byterun by Ned Batchelder https://github.com/nedbat/byterun
# x-python by R. Bernstein https://github.com/rocky/x-python
# python3+1 bidouillé par pmp-p https://github.com/pydk

# AUTHORS
# Ned Batchelder
# Allison Kaptur
# Laura Lindzey
# Rahul Gopinath
# Björn Mathis
# Darius Bacon
# Paul Peny
# etc...
#
#
#
#




import sys
import dis
import linecache  # for print_frames
import operator
import types
import collections
import inspect
import types


import builtins


class cpy:
    import inspect
    getcallargs = inspect.getcallargs



sys.path.append('.')


import asyncio


# add stdlib / wapy-lib / pycopy-lib / micropython-lib / etc ... to path
sys.path.append( __file__.rsplit('/',2)[0] )

#from pythons.pyobj import Frame, Block, Method, Function, Generator, Cell


byteint = lambda b: b




def make_cell(value):
    # Thanks to Alex Gaynor for help with this bit of twistiness.
    # Construct an actual cell object by creating a closure right here,
    # and grabbing the cell object out of the function we create.
    fn = (lambda x: lambda: x)(value)
    return fn.__closure__[0]


class Function(object):
    __slots__ = [
        'func_code', 'func_name', 'func_defaults', 'func_globals',
        'func_locals', 'func_dict', 'func_closure',
        '__name__', '__dict__', '__doc__',
        '_vm', '_func',
    ]

    def __init__(self, name, code, globs, defaults, kwdefaults, closure, vm):
        self._vm = vm
        self.func_code = code
        self.func_name = self.__name__ = name or code.co_name
        self.func_defaults = defaults
        self.func_globals = globs
        self.func_locals = self._vm.frame.f_locals
        self.__dict__ = {}
        self.func_closure = closure
        self.__doc__ = code.co_consts[0] if code.co_consts else None

        # Sometimes, we need a real Python function.  This is for that.
        kw = {
            'argdefs': self.func_defaults,
        }
        if closure:
            kw['closure'] = tuple(make_cell(0) for _ in closure)
        self._func = types.FunctionType(code, globs, **kw)

    def __repr__(self):         # pragma: no cover
        return '<Function %s at 0x%08x>' % (
            self.func_name, id(self)
        )

    def __get__(self, instance, owner):
        if instance is not None:
            return Method(instance, owner, self)
        return self

    def __call__(self, *argv, **kw):
        global MONITOR
        if MONITOR:
            print("103:",self.__name__,argv,kw)

        callargs = cpy.getcallargs(self._func, *argv, **kw)

        frame = self._vm.make_frame(
            self.func_code, callargs, self.func_globals, {}, self.func_closure
        )
        CO_GENERATOR = 32           # flag for "this code uses yield"
        if self.func_code.co_flags & CO_GENERATOR:
            gen = Generator(frame, self._vm)
            frame.generator = gen
            retval = gen
        else:
            retval = self._vm.run_frame(frame)

            if MONITOR:
                print(f"  ------ !!!!! new frame {self._func} !!! -------- ")

            if self._vm.AS:
                self._vm.AS_CALL.append( retval )
                return None

        return retval


class Native(object):
    def __init__(self, instance, func ):
        self._self = instance
        self._func = func

    def __call__(self,*argv,**kw):
        return self._func(self._self,*argv,**kw)


class Method(object):
    def __init__(self, obj, _class, func):
        self.im_self = obj
        self.im_class = _class
        self.im_func = func

    def __repr__(self):         # pragma: no cover
        vm = self.im_func._vm

        if vm.exporter:

            sid = str(id(self))
            vm.AS_RES[sid] = Native(self.im_self, self.im_func._func)
            return sid

        name = "%s.%s" % (self.im_class.__name__, self.im_func.func_name)
        if self.im_self is not None:
            #return '<Bound AS_Method %s of %s>' % (name, self.im_self)
            return '<Bound AS_Method(%s) of %s>' % (self.im_func._func, self.im_self)
        else:
            return '<Unbound AS_Method %s>' % (name,)

    def __call__(self, *argv, **kw):
        global MONITOR

        if self.im_func.__name__.find('update')>=0:
            MONITOR += 1

        if self.im_self is not None:
            retval= self.im_func(self.im_self, *argv, **kw)
        else:
            retval= self.im_func(*argv, **kw)

        if MONITOR:
            print("153:__call__", self.im_func.__name__, retval )
        return retval




class Cell(object):
    """A fake cell for closures.

    Closures keep names in scope by storing them not in a frame, but in a
    separate object called a cell.  Frames share references to cells, and
    the LOAD_DEREF and STORE_DEREF opcodes get and set the value from cells.

    This class acts as a cell, though it has to jump through two hoops to make
    the simulation complete:

        1. In order to create actual FunctionType functions, we have to have
           actual cell objects, which are difficult to make. See the twisty
           double-lambda in __init__.

        2. Actual cell objects can't be modified, so to implement STORE_DEREF,
           we store a one-element list in our cell, and then use [0] as the
           actual value.

    """
    def __init__(self, value):
        self.contents = value

    def get(self):
        return self.contents

    def set(self, value):
        self.contents = value


Block = collections.namedtuple("Block", "type, handler, level")


class Frame(object):
    def __init__(self, f_code, f_globals, f_locals, f_closure, f_back):
        self.f_code = f_code
        self.opcodes = list(dis.get_instructions(self.f_code))
        self.f_globals = f_globals
        self.f_locals = f_locals
        self.f_back = f_back
        self.stack = []
        if f_back and f_back.f_globals is f_globals:
            # If we share the globals, we share the builtins.
            self.f_builtins = f_back.f_builtins
        else:
            try:
                self.f_builtins = f_globals['__builtins__']
                if hasattr(self.f_builtins, '__dict__'):
                    self.f_builtins = self.f_builtins.__dict__
            except KeyError:
                # No builtins! Make up a minimal one with None.
                self.f_builtins = {'None': None}

        self.f_lineno = f_code.co_firstlineno
        self.f_lasti = 0

        self.cells = {} if f_code.co_cellvars or f_code.co_freevars else None
        for var in f_code.co_cellvars:
            # Make a cell for the variable in our locals, or None.
            self.cells[var] = Cell(self.f_locals.get(var))
        if f_code.co_freevars:
            assert len(f_code.co_freevars) == len(f_closure)
            self.cells.update(zip(f_code.co_freevars, f_closure))

        self.block_stack = []
        self.generator = None

    def __repr__(self):         # pragma: no cover
        return '<Frame at 0x%08x: %r @ %d>' % (
            id(self), self.f_code.co_filename, self.f_lineno
        )

    def line_number(self):
        """Get the current line number the frame is executing."""
        # We don't keep f_lineno up to date, so calculate it based on the
        # instruction address and the line number table.
        lnotab = self.f_code.co_lnotab
        byte_increments = iter(lnotab[0::2])
        line_increments = iter(lnotab[1::2])

        byte_num = 0
        line_num = self.f_code.co_firstlineno

        for byte_incr, line_incr in zip(byte_increments, line_increments):
            byte_num += byte_incr
            if byte_num > self.f_lasti:
                break
            line_num += line_incr

        return line_num


class Generator(object):
    def __init__(self, g_frame, vm):
        self.gi_frame = g_frame
        self.vm = vm
        self.started = False
        self.finished = False

    def __iter__(self):
        return self

    def next(self):
        return self.send(None)

    def send(self, value=None):
        if not self.started and value is not None:
            raise TypeError("Can't send non-None value to a just-started generator")
        self.gi_frame.stack.append(value)
        self.started = True
        val = self.vm.resume_frame(self.gi_frame)
        if self.finished:
            raise StopIteration(val)
        return val

    __next__ = next











#// ================================== VM =================================================





MONITOR = 0


if __debug__:
    # Create a repr that won't overflow.
    import logging
    log = logging.getLogger(__name__)

iop_func = {}
iop_keys = {}

for op in """
POWER.ipow
MULTIPLY.imul
DIVIDE.ifloordiv
FLOOR_DIVIDE.ifloordiv
TRUE_DIVIDE.itruediv
MODULO.imod
ADD.iadd
SUBTRACT.isub
LSHIFT.ilshift
RSHIFT.irshift
AND.iand
OR.ior
XOR.ixor
""".strip().split():
    key, value = op.split(".", 1)
    key = key.strip()
    value = value.strip()
    iop_func[key] = getattr(operator, value)
    iop_keys[key] = "__%s__" % value

del key
del value

pending = {}



def sync_metacell(meta, cell):
    meta = list(meta)
    metaclass = meta.pop(0)
    cls = metaclass(*meta)

    if isinstance(cell, Cell):
        cell.set(cls)
    print("      > as_build_func METACLASS:", cell, cls)
    return cls

async def build_metacell(meta, cell):
    meta = list(meta)
    metaclass = meta.pop(0)
    cls = metaclass(*meta)

    if isinstance(cell, Cell):
        cell.set(cls)
    print("      > as_build_func METACLASS:", cell, cls)
    return cls

def build_class( func, name, *bases, **kwds):
    global MONITOR
    print("      > build_class", func, bases, kwds)

    if not isinstance(func, Function):
        raise TypeError("func must be a function")

    if not isinstance(name, str):
        raise TypeError("name is not a string")

    metaclass = kwds.pop("metaclass", None)
    # (We don't just write 'metaclass=None' in the signature above
    # because that's a syntax error in Py2.)

    if metaclass is None:
        metaclass = type(bases[0]) if bases else type

    # calculate metaclass
    if isinstance(metaclass, type):
        for base in bases:
            t = type(base)
            if issubclass(t, metaclass):
                metaclass = t
            elif not issubclass(metaclass, t):
                raise TypeError("metaclass conflict", metaclass, t)

    try:
        prepare = metaclass.__prepare__
    except AttributeError:
        namespace = {}
    else:
        namespace = prepare(name, bases, **kwds)


    # Execute the body of func. This is the step that would go wrong if
    # we tried to use the built-in __build_class__, because __build_class__
    # does not call func, it magically executes its body directly, as we
    # do here (except we invoke our VirtualMachine instead of CPython's).
    frame = func._vm.make_frame(func.func_code, f_globals=func.func_globals, f_locals=namespace, f_closure=func.func_closure)

    meta = (metaclass, name, bases, namespace, )
    try:
        if VirtualMachine.ASYNC:
            retval = func._vm.run_frame_meta(frame, meta)
            VirtualMachine.AS_BUILD.append( retval )
        else:
            #sync
            #print('  +sync', frame, func, meta)
            cell = func._vm.run_frame(frame)
            retval = sync_metacell(meta, cell)

        return retval
    finally:
        print('      < build_class =', retval )
        #MONITOR -= 1


async def spin_res(vm, result):
    vm.lock()
    print(" -- aio_suspend --")
    while vm.spinlock > 0:
        await asyncio.sleep(0)
    return result



class vm_TRY_FINALLY(object):

    # https://bugs.python.org/issue33387

    # explain https://bugs.python.org/issue32949
    # PR https://github.com/python/cpython/pull/6641



    def byte_WITH_CLEANUP_START(self):
        u = self.top()
        v = None
        w = None
        if u is None:
            exit_method = self.pop(1)
        elif isinstance(u, str):
            if u in {"return", "continue"}:
                exit_method = self.pop(2)
            else:
                exit_method = self.pop(1)
        elif issubclass(u, BaseException):
            w, v, u = self.popn(3)
            tp, exc, tb = self.popn(3)
            exit_method = self.pop()
            self.push(tp, exc, tb)
            self.push(None)
            self.push(w, v, u)
            block = self.pop_block()
            assert block.type == "except-handler"
            self.push_block(block.type, block.handler, block.level - 1)

        res = exit_method(u, v, w)
        self.push(u)
        self.push(res)

    def byte_WITH_CLEANUP_FINISH(self):
        res = self.pop()
        u = self.pop()
        if type(u) is type and issubclass(u, BaseException) and res:
            self.push("silenced")

    def byte_END_FINALLY_37(self):
        v = self.pop()
        if isinstance(v, str):
            why = v
            if why in ("return", "continue"):
                self.return_value = self.pop()
            if why == "silenced":  # PY3
                block = self.pop_block()
                assert block.type == "except-handler"
                self.unwind_block(block)
                why = None
        elif v is None:
            why = None
        elif issubclass(v, BaseException):
            exctype = v
            val = self.pop()
            tb = self.pop()
            self.last_exception = (exctype, val, tb)
            why = "reraise"
        else:  # pragma: no cover
            raise VirtualMachineError("Confused END_FINALLY")
        return why

# 3.8
    def byte_BEGIN_FINALLY(self):
        """Pushes NULL onto the stack for using it in END_FINALLY, POP_FINALLY, WITH_CLEANUP_START and WITH_CLEANUP_FINISH. Starts the finally block."""
        self.push(None)

    def byte_SETUP_FINALLY(self, dest):
        self.push_block("finally", dest)


    def byte_END_FINALLY(self):
        """Terminates a finally clause. The interpreter recalls whether the
        exception has to be re-raised or execution has to be continued
        depending on the value of TOS.
        * If TOS is NULL (pushed by BEGIN_FINALLY) continue from the next instruction.
          TOS is popped.
        * If TOS is an integer (pushed by CALL_FINALLY), sets the bytecode counter to TOS.
          TOS is popped.
        * If TOS is an exception type (pushed when an exception has
          been raised) 6 values are popped from the stack, the first
          three popped values are used to re-raise the exception and
          the last three popped values are used to restore the
          exception state. An exception handler block is removed from
          the block stack.
        """
        v = self.pop()
        if v is None:
            why = None
        elif isinstance(v, int):
            self.jump(v)
            why = "return"
        elif issubclass(v, BaseException):
            # from trepan.api import debug; debug()
            exctype = v
            val = self.pop()
            tb = self.pop()
            self.last_exception = (exctype, val, tb)

            raise VirtualMachineError("END_FINALLY not finished yet")
            # FIXME: pop 3 more values
            why = "reraise"
        else:  # pragma: no cover
            raise VirtualMachineError("Confused END_FINALLY")
        return why


    def byte_CALL_FINALLY(self, delta):
        """Pushes the address of the next instruction onto the stack and
        increments bytecode counter by delta. Used for calling the
        finally block as a "subroutine".
        """
        # Is it f_lasti or the one after that
        self.push(self.frame.f_lasti)
        self.jump(delta)

    def byte_POP_FINALLY(self, preserve_tos):
        """Cleans up the value stack and the block stack. If preserve_tos is
        not 0 TOS first is popped from the stack and pushed on the stack after
        performing other stack operations:
        * If TOS is NULL or an integer (pushed by BEGIN_FINALLY or CALL_FINALLY) it is popped from the stack.
        * If TOS is an exception type (pushed when an exception has been raised) 6 values are popped from the
          stack, the last three popped values are used to restore the exception state. An exception handler
          block is removed from the block stack.
        It is similar to END_FINALLY, but doesn’t change the bytecode
        counter nor raise an exception. Used for implementing break,
        continue and return in the finally block.
        """
        v = self.pop()
        if v is None:
            why = None
        elif issubclass(v, BaseException):
            # from trepan.api import debug; debug()
            exctype = v
            val = self.pop()
            tb = self.pop()
            self.last_exception = (exctype, val, tb)

            # FIXME: pop 3 more values
            why = "reraise"
            raise VirtualMachineError("POP_FINALLY not finished yet")
        else:  # pragma: no cover
            raise VirtualMachineError("Confused POP_FINALLY")
        return why

# 3.9

    def byte_LOAD_ASSERTION_ERROR(self):
        """
        Pushes AssertionError onto the stack. Used by the `assert` statement.
        """
        self.push(AssertionError)

    def byte_LIST_TO_TUPLE(self):
        """
        Pops a list from the stack and pushes a tuple containing the same values.
        """
        self.push(tuple(self.pop()))

    def byte_IS_OP(self, invert: int):
        """Performs is comparison, or is not if invert is 1."""
        TOS1, TOS = self.popn(2)
        if invert:
            self.push(TOS1 is not TOS)
        else:
            self.push(TOS1 is TOS)


    def byte_CONTAINS_OP(self, invert: int):
        """Performs in comparison, or not in if invert is 1."""
        TOS1, TOS = self.popn(2)
        if invert:
            self.push(TOS1 not in TOS)
        else:
            self.push(TOS1 in TOS)
        return

    def byte_LIST_EXTEND(self, i):
        """Calls list.extend(TOS1[-i], TOS). Used to build lists."""
        TOS = self.pop()
        destination = self.peek(i)
        assert isinstance(destination, list)
        destination.extend(TOS)

    def byte_SET_UPDATE(self, i):
        """Calls set.update(TOS1[-i], TOS). Used to build sets."""
        TOS = self.pop()
        destination = self.peek(i)
        assert isinstance(destination, set)
        destination.update(TOS)

    def byte_DICT_MERGE(self, i):
        """Like DICT_UPDATE but raises an exception for duplicate keys."""
        TOS = self.pop()
        assert isinstance(TOS, dict)
        destination = self.peek(i)
        assert isinstance(destination, dict)
        dups = set(destination.keys()) & set(TOS.keys())
        if bool(dups):
            raise RuntimeError("Duplicate keys '%s' in DICT_MERGE" % dups)
        destination.update(TOS)

    def byte_DICT_UPDATE(self, i):
        """Calls dict.update(TOS1[-i], TOS). Used to build dicts."""
        TOS = self.pop()
        assert isinstance(TOS, dict)
        destination = self.peek(i)
        assert isinstance(destination, dict)
        destination.update(TOS)


#FIXME:


    def byte_END_ASYNC_FOR(self):
        """Terminates an `async for1 loop. Handles an exception raised when
        awaiting a next item. If TOS is StopAsyncIteration pop 7 values from
        the stack and restore the exception state using the second three of
        them. Otherwise re-raise the exception using the three values from the
        stack. An exception handler block is removed from the block stack."""

        raise VirtualMachineError("END_ASYNC_FOR not implemented yet")


    def byte_RERAISE(self):
        # FIXME
        raise RuntimeError("RERAISE not implemented yet")
        pass


    def byte_WITH_EXCEPT_START(self):
        # FIXME
        raise RuntimeError("WITH_EXCEPT_START not implemented yet")
        pass











class vm_STACK:


    ## Stack manipulation

    def byte_LOAD_CONST(self, const):
        self.push(const)

    def byte_POP_TOP(self):
        self.pop()

    def byte_DUP_TOP(self):
        self.push(self.top())

    def byte_DUP_TOPX(self, count):
        items = self.popn(count)
        self.push(*items)
        self.push(*items)

    def byte_DUP_TOP_TWO(self):
        # Py3 only
        a, b = self.popn(2)
        self.push(a, b, a, b)

    def byte_ROT_TWO(self):
        a, b = self.popn(2)
        self.push(b, a)

    def byte_ROT_THREE(self):
        a, b, c = self.popn(3)
        self.push(c, a, b)

    def byte_ROT_FOUR(self):
        a, b, c, d = self.popn(4)
        self.push(d, a, b, c)

    ## Names

    def byte_LOAD_NAME(self, name):
        frame = self.frame
        if name in frame.f_locals:
            val = frame.f_locals[name]
        elif name in frame.f_globals:
            val = frame.f_globals[name]
        elif name in frame.f_builtins:
            val = frame.f_builtins[name]
        else:
            raise NameError("name '%s' is not defined" % name)
        self.push(val)

    def byte_STORE_NAME(self, name):
        self.frame.f_locals[name] = self.pop()

    def byte_DELETE_NAME(self, name):
        del self.frame.f_locals[name]

    def byte_LOAD_FAST(self, name):
        if name in self.frame.f_locals:
            val = self.frame.f_locals[name]
        else:
            raise UnboundLocalError("local variable '%s' referenced before assignment" % name)
        self.push(val)

    def byte_STORE_FAST(self, name):
        self.frame.f_locals[name] = self.pop()

    def byte_DELETE_FAST(self, name):
        del self.frame.f_locals[name]

    def byte_LOAD_GLOBAL(self, name):
        f = self.frame
        if name in f.f_globals:
            val = f.f_globals[name]
        elif name in f.f_builtins:
            val = f.f_builtins[name]
        else:
            raise NameError("name '%s' is not defined" % name)
        self.push(val)

    def byte_STORE_GLOBAL(self, name):
        f = self.frame
        f.f_globals[name] = self.pop()

    def byte_LOAD_DEREF(self, name):
        self.push(self.frame.cells[name].get())

    def byte_STORE_DEREF(self, name):
        self.frame.cells[name].set(self.pop())

    def byte_LOAD_LOCALS(self):
        self.push(self.frame.f_locals)

    def byte_LOAD_METHOD(self, name):
        func = getattr(self.pop(), name)
        self.push(func)

    def byte_BUILD_STRING(self, count):
        """
        The version of BUILD_MAP specialized for constant keys. count
        values are consumed from the stack. The top element on the
        stack contains a tuple of keys.
        """
        self.push("".join( self.popn(count) ))


    def byte_FORMAT_VALUE(self, flags):
        """Used for implementing formatted literal strings (f-strings). Pops
        an optional fmt_spec from the stack, then a required value. flags is
        interpreted as follows:

        * (flags & 0x03) == 0x00: value is formatted as-is.
        * (flags & 0x03) == 0x01: call str() on value before formatting it.
        * (flags & 0x03) == 0x02: call repr() on value before formatting it.
        * (flags & 0x03) == 0x03: call ascii() on value before formatting it.
        * (flags & 0x04) == 0x04: pop fmt_spec from the stack and use it, else use an empty fmt_spec.

        Formatting is performed using PyObject_Format(). The result is
        pushed on the stack.
        """
        if flags & 0x04 == 0x04:
            format_spec = self.pop()
        else:
            format_spec = ''

        value = self.pop()
        attr_flags = flags & 0x03
        if attr_flags:
            value = FSTRING_CONVERSION_MAP.get(attr_flags, identity)(value)

        result = format(value, format_spec)
        self.push(result)



class vm_PRINT:
    ## Printing

    if 0:  # Only used in the interactive interpreter, not in modules.

        def byte_PRINT_EXPR(self):
            print(self.pop())

    def byte_PRINT_ITEM(self):
        item = self.pop()
        self.print_item(item)

    def byte_PRINT_ITEM_TO(self):
        to = self.pop()
        item = self.pop()
        self.print_item(item, to)

    def byte_PRINT_NEWLINE(self):
        self.print_newline()

    def byte_PRINT_NEWLINE_TO(self):
        to = self.pop()
        self.print_newline(to)

    def print_item(self, item, to=None):
        if to is None:
            to = sys.stdout
        if to.softspace:
            print(" ", end="", file=to)
            to.softspace = 0
        print(item, end="", file=to)
        if isinstance(item, str):
            if (not item) or (not item[-1].isspace()) or (item[-1] == " "):
                to.softspace = 1
        else:
            to.softspace = 1

    def print_newline(self, to=None):
        if to is None:
            to = sys.stdout
        print("", file=to)
        to.softspace = 0



class vm_JUMPS:

    def byte_JUMP_FORWARD(self, jump):
        self.jump(jump)

    def byte_JUMP_ABSOLUTE(self, jump):
        self.jump(jump)


    def byte_POP_JUMP_IF_TRUE(self, jump):
        val = self.pop()
        if val:
            self.jump(jump)

    def byte_POP_JUMP_IF_FALSE(self, jump):
        val = self.pop()
        if not val:
            self.jump(jump)

    def byte_JUMP_IF_TRUE_OR_POP(self, jump):
        val = self.top()
        if val:
            self.jump(jump)
        else:
            self.pop()

    def byte_JUMP_IF_FALSE_OR_POP(self, jump):
        val = self.top()
        if not val:
            self.jump(jump)
        else:
            self.pop()



class vm_BLOCKS:

    def byte_SETUP_LOOP(self, dest):
        self.push_block("loop", dest)

    def byte_GET_ITER(self):
        self.push(iter(self.pop()))

    def byte_GET_YIELD_FROM_ITER(self):
        tos = self.top()
        if isinstance(tos, types.GeneratorType) or isinstance(tos, types.CoroutineType):
            return
        tos = self.pop()
        self.push(iter(tos))

    def byte_FOR_ITER(self, jump):
        iterobj = self.top()
        try:
            v = next(iterobj)
            self.push(v)
        except StopIteration:
            self.pop()
            self.jump(jump)

    def byte_BREAK_LOOP(self):
        return "break"

    def byte_CONTINUE_LOOP(self, dest):
        # This is a trick with the return value.
        # While unrolling blocks, continue and return both have to preserve
        # state as the finally blocks are executed.  For continue, it's
        # where to jump to, for return, it's the value to return.  It gets
        # pushed on the stack for both, so continue puts the jump destination
        # into return_value.
        self.return_value = dest
        return "continue"

    def byte_SETUP_EXCEPT(self, dest):
        self.push_block("setup-except", dest)

    def byte_POP_BLOCK(self):
        self.pop_block()

    def byte_RAISE_VARARGS(self, argc):
        cause = exc = None
        if argc == 2:
            cause = self.pop()
            exc = self.pop()
        elif argc == 1:
            exc = self.pop()
        return self.do_raise(exc, cause)

    def byte_POP_EXCEPT(self):
        block = self.pop_block()
        if block.type != "except-handler":
            raise Exception("popped block is not an except handler")
        self.unwind_block(block)

    def byte_SETUP_WITH(self, dest):
        ctxmgr = self.pop()
        self.push(ctxmgr.__exit__)
        ctxmgr_obj = ctxmgr.__enter__()
        self.push_block("finally", dest)
        self.push(ctxmgr_obj)



    def byte_WITH_CLEANUP(self):
        # The code here does some weird stack manipulation: the exit function
        # is buried in the stack, and where depends on what's on top of it.
        # Pull out the exit function, and leave the rest in place.
        v = w = None
        u = self.top()
        if u is None:
            exit_func = self.pop(1)
        elif isinstance(u, str):
            if u in ("return", "continue"):
                exit_func = self.pop(2)
            else:
                exit_func = self.pop(1)
            u = None
        elif issubclass(u, BaseException):
            w, v, u = self.popn(3)
            tp, exc, tb = self.popn(3)
            exit_func = self.pop()
            self.push(tp, exc, tb)
            self.push(None)
            self.push(w, v, u)
            block = self.pop_block()
            assert block.type == "except-handler"
            self.push_block(block.type, block.handler, block.level - 1)
        else:  # pragma: no cover
            raise VirtualMachineError("Confused WITH_CLEANUP")
        exit_ret = exit_func(u, v, w)
        err = (u is not None) and bool(exit_ret)
        if err:
            # An error occurred, and was suppressed
            self.push("silenced")


if not 'sync' in sys.argv:
    class vm_MODE:

        ASYNC = True

        async def run_frame_meta(self, frame, meta):
            await self.run_frame(frame)
            async_result = self.return_value
            self.return_value = await build_metacell(meta, self.return_value)
            try:
                return self.return_value
            finally:
                print('    < async build_class/run_frame_meta =', self.return_value, async_result)

        async def run_frame(self, frame):
            global MONITOR
            #
            #await asyncio.sleep(0)
            #
            why = None

            self.push_frame(frame)

            while not aio.loop.is_closed():
                why = None
                byteName, arguments, opoffset = self.parse_byte_and_args()

                if byteName.startswith("UNARY_"):
                    self.unaryOperator(byteName[6:])
                    continue

                if byteName.startswith("BINARY_"):
                    self.binaryOperator(byteName[7:])
                    continue

                if byteName.startswith("INPLACE_"):
                    self.inplaceOperator(byteName[8:])
                    continue

                if "SLICE+" in byteName:
                    self.sliceOperator(byteName)
                    continue

                bytecode_fn = getattr(self, "byte_%s" % byteName, None)

                if bytecode_fn is None:
                    raise VirtualMachineError("unknown bytecode type: %s" % byteName)

                try:
                    # dispatch
                    #print("903:",byteName, arguments, opoffset)

                    if byteName=="IMPORT_NAME":
                        #print("1057: dispatch-async aio_suspend spin==", why)
                        if self.ASYNC and (arguments[0] == 'aio_suspend'):
                            why = await spin_res(self, bytecode_fn(*arguments))

                    elif byteName.startswith('CALL_'):
                        if MONITOR:
                            print("  ? a/sync", bytecode_fn.__name__, *arguments)
                        why = bytecode_fn(*arguments)

                    else:
                        why = bytecode_fn(*arguments)

                    if len(VirtualMachine.AS_BUILD):
                        coro = VirtualMachine.AS_BUILD.pop()
                        retval = await coro
                        self.push( retval )
                        print('    < async pushed', retval )
                        continue

                    if why is VirtualMachine.AS_DELAYED:
                        # maybe injected result
                        instance = VirtualMachine.AS_CALL.pop()

                        # late call_function
                        coro = VirtualMachine.AS_CALL.pop(0)

                        # if the underlying ctor is calling __init__ as a coro
                        # return None is expected here.

                        retval = await coro or instance
                        self.push(retval)

                        #print('  - async', coro, ' ==> ', retval)
                        continue

                except Exception as e:
                    print("VMERROR", frame, byteName,'(',*arguments,end=' )\n')
                    sys.print_exception(e)

                    # deal with exceptions encountered while executing the op.
                    self.last_exception = sys.exc_info()[:2] + (None,)
                    log.exception("Caught exception during execution")

                    # TODO: ceval calls PyTraceBack_Here, not sure what that does.
                    why = "exception"
                    break

                if why == "reraise":
                    why = "exception"
                    break

                if why != "yield":
                    while why and frame.block_stack:
                        # Deal with any block management we need to do.
                        why = self.manage_block_stack(why)

                if why:
                    break

            # TODO: handle generator exception state

            self.pop_frame()

            if why == "exception":
                print( "RERAISE :",*self.last_exception)
                #raise self.last_exception[1]
                aio.loop.stop()

            return self.return_value

if 'sync' in sys.argv:
    error()
    class vm_MODE:

        ASYNC = False

        def run_frame(self, frame):
            global MONITOR

            why = None
            self.push_frame(frame)


            while True:

                why = None

                byteName, arguments, opoffset = self.parse_byte_and_args()
                if log.isEnabledFor(logging.INFO):
                    self.log(byteName, arguments, opoffset)


                if byteName.startswith("UNARY_"):
                    self.unaryOperator(byteName[6:])
                    continue

                if byteName.startswith("BINARY_"):
                    self.binaryOperator(byteName[7:])
                    continue

                if byteName.startswith("INPLACE_"):
                    self.inplaceOperator(byteName[8:])
                    continue

                if "SLICE+" in byteName:
                    self.sliceOperator(byteName)
                    continue

                # When unwinding the block stack, we need to keep track of why we
                # are doing it.

                try:
                    # dispatch
                    bytecode_fn = getattr(self, "byte_%s" % byteName, None)
                    if not bytecode_fn:  # pragma: no cover
                        raise VirtualMachineError("unknown bytecode type: %s" % byteName)


                    if bytecode_fn is self.byte_IMPORT_NAME:
                        if arguments[0] == 'aio_suspend':
                            print("N/A dispatch-async aio_suspend spin==", why)

                    elif byteName.startswith('CALL_'):
                        if MONITOR:print("  ? a/sync", bytecode_fn.__name__, *arguments)

                    why = bytecode_fn(*arguments)


                except Exception as e:
                    print("VMERROR", self.frame, byteName,'(',*arguments,end=' )\n')
                    sys.print_exception(e)

                    # deal with exceptions encountered while executing the op.
                    self.last_exception = sys.exc_info()[:2] + (None,)
                    log.exception("Caught exception during execution")
                    why = "exception"


                if why == "exception":
                    # TODO: ceval calls PyTraceBack_Here, not sure what that does.
                    pass

                if why == "reraise":
                    why = "exception"

                if why != "yield":
                    while why and frame.block_stack:
                        # Deal with any block management we need to do.
                        why = self.manage_block_stack(why)

                if why:
                    break

            # TODO: handle generator exception state
            self.pop_frame()

            if why == "exception":
                raise self.last_exception[1]

            return self.return_value

        run_sub_frame = run_frame

        def run_code(self, code, f_globals=None, f_locals=None):
            global sync
            frame = self.make_frame(code, f_globals=f_globals, f_locals=f_locals)
            val = self.run_frame(frame)
            # Check some invariants
            if self.frames:  # pragma: no cover
                raise VirtualMachineError("Frames left over!")
            if self.frame and self.frame.stack:  # pragma: no cover
                raise VirtualMachineError("Data left on stack! %r" % self.frame.stack)

            return val


class vm_CORE:

    # https://rokups.github.io/#!pages/python3-asyncio-sync-async.md

    # asterpreter or not
    AS = 0



    AS_DELAYED = object()



    AS_BUILD = []

    AS_CALL = []

    AS_RES = {}





    def __init__(self):
        # The call stack of frames.
        self.frames = []
        # The current frame.
        self.frame = None
        self.return_value = None
        self.last_exception = None
        self.spinlock = 0




    def call_function(self, arg, args, kwargs):
        global MONITOR
        lenKw, lenPos = divmod(arg, 256)
        namedargs = {}
        for i in range(lenKw):
            key, val = self.popn(2)
            namedargs[key] = val
        namedargs.update(kwargs)
        posargs = self.popn(lenPos)
        posargs.extend(args)

        func = self.pop()

        if MONITOR:
            print('    +call_function', func, posargs, namedargs)

        is_as = func if func is build_class else None

        frame = self.frame
        if hasattr(func, "im_func"):
            # Methods get self as an implicit first parameter.
            if func.im_self:
                posargs.insert(0, func.im_self)
            # The first parameter must be the correct type.
            if not isinstance(posargs[0], func.im_class):
                raise TypeError(
                    "unbound method %s() must be called with %s instance "
                    "as first argument (got %s instance instead)"
                    % (func.im_func.func_name, func.im_class.__name__, type(posargs[0]).__name__,)
                )
            func = func.im_func

        retval =None

        if asyncio.iscoroutine(func):
            print(" ********* AS_BUG 1 ******** ", func, posargs, namedargs)
            return

        if len(VirtualMachine.AS_CALL):
            print(f"  ********** PENDING Q not empty {len(VirtualMachine.AS_CALL)} ")

        # could be the real thing, or None + a stacked coro

        try:
            retval = func(*posargs, **namedargs)
        except TypeError:
            raise

        if len(VirtualMachine.AS_CALL):
            VirtualMachine.AS_CALL.append(retval)
            #print(f'  <<<< expect delay {VirtualMachine.AS_CALL} >>>>', retval)
            return VirtualMachine.AS_DELAYED

        try:
            self.push(retval)
        finally:
            if MONITOR:
                print('    -call_function', func.__name__, retval)
                MONITOR-=1

    def top(self):
        """Return the value at the top of the stack, with no changes."""
        return self.frame.stack[-1]

    def pop(self, i=0):
        """Pop a value from the stack.

        Default to the top of the stack, but `i` can be a count from the top
        instead.

        """
        return self.frame.stack.pop(-1 - i)

    def push(self, *vals):
        """Push values onto the value stack."""
        self.frame.stack.extend(vals)

    def popn(self, n):
        """Pop a number of values from the value stack.

        A list of `n` values is returned, the deepest value first.

        """
        if n:
            ret = self.frame.stack[-n:]
            self.frame.stack[-n:] = []
            return ret
        else:
            return []

    def peek(self, n):
        """Get a value `n` entries down in the stack, without changing the stack."""
        return self.frame.stack[-n]

    def jump(self, jump):
        """Move the bytecode pointer to `jump`, so it will execute next."""
        self.frame.f_lasti = jump

    def push_block(self, type, handler=None, level=None):
        if level is None:
            level = len(self.frame.stack)
        self.frame.block_stack.append(Block(type, handler, level))

    def pop_block(self):
        return self.frame.block_stack.pop()

    def make_frame(self, code, callargs={}, f_globals=None, f_locals=None, f_closure=None):
        log.info("make_frame: code=%r, callargs=%s" % (code, repr(callargs)))
        if f_globals is not None:
            f_globals = f_globals
            if f_locals is None:
                f_locals = f_globals
        elif self.frames:
            f_globals = self.frame.f_globals
            f_locals = {}
        else:
            f_globals = f_locals = {
                "__builtins__": __builtins__,
                "__name__": "__main__",
                "__doc__": None,
                "__package__": None,
            }
        f_locals.update(callargs)
        frame = Frame(code, f_globals, f_locals, f_closure, self.frame)
        return frame

    def push_frame(self, frame):
        self.frames.append(frame)
        self.frame = frame

    def pop_frame(self):
        self.frames.pop()
        if self.frames:
            self.frame = self.frames[-1]
        else:
            self.frame = None

    def print_frames(self):
        """Print the call stack, for debugging."""
        for f in self.frames:
            filename = f.f_code.co_filename
            lineno = f.line_number()
            print('  File "%s", line %d, in %s' % (filename, lineno, f.f_code.co_name))
            linecache.checkcache(filename)
            line = linecache.getline(filename, lineno, f.f_globals)
            if line:
                print("    " + line.strip())



    def unwind_block(self, block):
        if block.type == "except-handler":
            offset = 3
        else:
            offset = 0

        while len(self.frame.stack) > block.level + offset:
            self.pop()

        if block.type == "except-handler":
            tb, value, exctype = self.popn(3)
            self.last_exception = exctype, value, tb

    def parse_byte_and_args(self):
        """ Parse 1 - 3 bytes of bytecode into
        an instruction and optionally arguments.
        In Python3.6 the format is 2 bytes per instruction."""

        f = self.frame
        opoffset = f.f_lasti

        if sys.version_info >= (3, 6):
            currentOp = f.opcodes[opoffset]
            byteCode = currentOp.opcode
            byteName = currentOp.opname
        else:
            byteCode = byteint(f.f_code.co_code[opoffset])
            byteName = dis.opname[byteCode]

        f.f_lasti += 1
        arg = None
        arguments = []

        if byteCode == dis.EXTENDED_ARG:
            # Prefixes any opcode which has an argument too big to fit into the
            # default two bytes. ext holds two additional bytes which, taken
            # together with the subsequent opcode’s argument, comprise a
            # four-byte argument, ext being the two most-significant bytes.
            # We simply ignore the EXTENDED_ARG because that calculation
            # is already done by dis, and stored in next currentOp.
            # Lib/dis.py:_unpack_opargs
            return self.parse_byte_and_args()

        if byteCode >= dis.HAVE_ARGUMENT:
            # if sys.version_info >= (3, 6):
            intArg = currentOp.arg
            # else:
            #    arg = f.f_code.co_code[f.f_lasti : f.f_lasti + 2]
            #    f.f_lasti += 2
            #    intArg = byteint(arg[0]) + (byteint(arg[1]) << 8)

            if byteCode in dis.hasconst:
                arg = f.f_code.co_consts[intArg]

            elif byteCode in dis.hasfree:
                if intArg < len(f.f_code.co_cellvars):
                    arg = f.f_code.co_cellvars[intArg]
                else:
                    var_idx = intArg - len(f.f_code.co_cellvars)
                    arg = f.f_code.co_freevars[var_idx]
            elif byteCode in dis.hasname:
                arg = f.f_code.co_names[intArg]

            elif byteCode in dis.hasjrel:
                if sys.version_info >= (3, 6):
                    arg = f.f_lasti + intArg // 2
                else:
                    arg = f.f_lasti + intArg

            elif byteCode in dis.hasjabs:
                if sys.version_info >= (3, 6):
                    arg = intArg // 2
                else:
                    arg = intArg

            elif byteCode in dis.haslocal:
                arg = f.f_code.co_varnames[intArg]

            else:
                arg = intArg

            arguments = [arg]

        return byteName, arguments, opoffset



    def manage_block_stack(self, why):
        """ Manage a frame's block stack.
        Manipulate the block stack and data stack for looping,
        exception handling, or returning."""
        assert why != "yield"

        block = self.frame.block_stack[-1]
        if block.type == "loop" and why == "continue":
            self.jump(self.return_value)
            why = None
            return why

        self.pop_block()
        self.unwind_block(block)

        if block.type == "loop" and why == "break":
            why = None
            self.jump(block.handler)
            return why

        if why == "exception" and block.type in ["setup-except", "finally"]:
            self.push_block("except-handler")
            exctype, value, tb = self.last_exception
            self.push(tb, value, exctype)
            # PyErr_Normalize_Exception goes here
            self.push(tb, value, exctype)
            why = None
            self.jump(block.handler)
            return why

        elif block.type == "finally":
            if why in ("return", "continue"):
                self.push(self.return_value)
            self.push(why)

            why = None
            self.jump(block.handler)
            return why

        return why


    ## Operators

    UNARY_OPERATORS = {
        "POSITIVE": operator.pos,
        "NEGATIVE": operator.neg,
        "NOT": operator.not_,
        "CONVERT": repr,
        "INVERT": operator.invert,
    }

    def unaryOperator(self, op):
        x = self.pop()
        self.push(self.UNARY_OPERATORS[op](x))

    BINARY_OPERATORS = {
        "POWER": pow,
        "MULTIPLY": operator.mul,
        "DIVIDE": getattr(operator, "div", lambda x, y: None),
        "FLOOR_DIVIDE": operator.floordiv,
        "TRUE_DIVIDE": operator.truediv,
        "MODULO": operator.mod,
        "ADD": operator.add,
        "SUBTRACT": operator.sub,
        "SUBSCR": operator.getitem,
        "LSHIFT": operator.lshift,
        "RSHIFT": operator.rshift,
        "AND": operator.and_,
        "XOR": operator.xor,
        "OR": operator.or_,
    }

    def binaryOperator(self, op):
        x, y = self.popn(2)
        self.push(self.BINARY_OPERATORS[op](x, y))

    if 1:

        def inplaceOperator(self, op):
            x, y = self.popn(2)
            if op == "POWER":
                x **= y
            elif op == "MULTIPLY":
                x *= y
            elif op in ["DIVIDE", "FLOOR_DIVIDE"]:
                x //= y
            elif op == "TRUE_DIVIDE":
                x /= y
            elif op == "MODULO":
                x %= y
            elif op == "ADD":
                x += y
            elif op == "SUBTRACT":
                x -= y
            elif op == "LSHIFT":
                x <<= y
            elif op == "RSHIFT":
                x >>= y
            elif op == "AND":
                x &= y
            elif op == "XOR":
                x ^= y
            elif op == "OR":
                x |= y
            else:  # pragma: no cover
                raise VirtualMachineError("Unknown in-place operator: %r" % op)
            self.push(x)

    else:

        def inplaceOperator(self, op):
            global iop_keys, iop_func
            x, y = self.popn(2)
            opk = iop_keys.get(op, None)

            if opk is None:
                raise VirtualMachineError("Unknown in-place operator: %r" % op)

            tx = type(x)

            if hasattr(tx, opk):
                self.push( getattr(tx, opk)(x, y) )
            else:
                self.push( tx( iop_func[op](x, y) ) )

    def sliceOperator(self, op):
        start = 0
        end = None  # we will take this to mean end
        op, count = op[:-2], int(op[-1])

        if count == 1:
            start = self.pop()
        elif count == 2:
            end = self.pop()
        elif count == 3:
            end = self.pop()
            start = self.pop()

        l = self.pop()

        if end is None:
            end = len(l)

        if op.startswith("STORE_"):
            l[start:end] = self.pop()
        elif op.startswith("DELETE_"):
            del l[start:end]
        else:
            self.push(l[start:end])

    COMPARE_OPERATORS = [
        operator.lt,
        operator.le,
        operator.eq,
        operator.ne,
        operator.gt,
        operator.ge,
        lambda x, y: x in y,
        lambda x, y: x not in y,
        lambda x, y: x is y,
        lambda x, y: x is not y,
        lambda x, y: issubclass(x, Exception) and issubclass(x, y),
    ]

    def byte_COMPARE_OP(self, opnum):
        x, y = self.popn(2)
        self.push(self.COMPARE_OPERATORS[opnum](x, y))

    ## Attributes and indexing

    def byte_LOAD_ATTR(self, attr):
        obj = self.pop()
        val = getattr(obj, attr)
        self.push(val)

    def byte_STORE_ATTR(self, name):
        val, obj = self.popn(2)
        setattr(obj, name, val)

    def byte_DELETE_ATTR(self, name):
        obj = self.pop()
        delattr(obj, name)

    def byte_STORE_SUBSCR(self):
        val, obj, subscr = self.popn(3)
        obj[subscr] = val

    def byte_DELETE_SUBSCR(self):
        obj, subscr = self.popn(2)
        del obj[subscr]

    ## Building

    def byte_BUILD_TUPLE_UNPACK_WITH_CALL(self, count):
        # This is similar to BUILD_TUPLE_UNPACK, but is used for f(*x, *y, *z)
        # call syntax. The stack item at position count + 1 should be the
        # corresponding callable f.
        self.build_container_flat(count, tuple)

    def byte_BUILD_TUPLE_UNPACK(self, count):
        # Pops count iterables from the stack, joins them in a single tuple,
        # and pushes the result. Implements iterable unpacking in
        # tuple displays (*x, *y, *z).
        self.build_container_flat(count, tuple)

    def byte_BUILD_TUPLE(self, count):
        self.build_container(count, tuple)

    def byte_BUILD_LIST_UNPACK(self, count):
        # This is similar to BUILD_TUPLE_UNPACK, but a list instead of tuple.
        # Implements iterable unpacking in list displays [*x, *y, *z].
        self.build_container_flat(count, list)

    def byte_BUILD_SET_UNPACK(self, count):
        # This is similar to BUILD_TUPLE_UNPACK, but a set instead of tuple.
        # Implements iterable unpacking in set displays {*x, *y, *z}.
        self.build_container_flat(count, set)

    def byte_BUILD_MAP_UNPACK(self, count):
        # Pops count mappings from the stack, merges them to a single dict,
        # and pushes the result. Implements dictionary unpacking in dictionary
        # displays {**x, **y, **z}.
        self.build_container(count, dict)

    def byte_BUILD_MAP_UNPACK_WITH_CALL(self, count):
        self.build_container(count, dict)

    def build_container_flat(self, count, container_fn):
        elts = self.popn(count)
        self.push(container_fn(e for l in elts for e in l))

    def build_container(self, count, container_fn):
        elts = self.popn(count)
        self.push(container_fn(elts))

    def byte_BUILD_LIST(self, count):
        elts = self.popn(count)
        self.push(elts)

    def byte_BUILD_SET(self, count):
        elts = self.popn(count)
        self.push(set(elts))

    def byte_BUILD_CONST_KEY_MAP(self, count):
        # count values are consumed from the stack.
        # The top element contains tuple of keys
        # added in version 3.6
        keys = self.pop()
        values = self.popn(count)
        kvs = dict(zip(keys, values))
        self.push(kvs)

    def byte_BUILD_MAP(self, count):
        # Pushes a new dictionary on to stack.
        if sys.version_info < (3, 5):
            self.push({})
            return
        # Pop 2*count items so that
        # dictionary holds count entries: {..., TOS3: TOS2, TOS1:TOS}
        # updated in version 3.5
        kvs = {}
        for i in range(count):
            key, val = self.popn(2)
            kvs[key] = val
        self.push(kvs)

    def byte_STORE_MAP(self):
        the_map, val, key = self.popn(3)
        the_map[key] = val
        self.push(the_map)

    def byte_UNPACK_SEQUENCE(self, count):
        seq = self.pop()
        for x in reversed(seq):
            self.push(x)

    def byte_BUILD_SLICE(self, count):
        if count == 2:
            x, y = self.popn(2)
            self.push(slice(x, y))
        elif count == 3:
            x, y, z = self.popn(3)
            self.push(slice(x, y, z))
        else:  # pragma: no cover
            raise VirtualMachineError("Strange BUILD_SLICE count: %r" % count)

    def byte_LIST_APPEND(self, count):
        val = self.pop()
        the_list = self.peek(count)
        the_list.append(val)

    def byte_SET_ADD(self, count):
        val = self.pop()
        the_set = self.peek(count)
        the_set.add(val)

# Changed from 2.4: Map value is TOS and map key is TOS1. Before, those were reversed.
    def byte_MAP_ADD(self, count):
# UNSURE!
        val, key = self.popn(2)
        the_map = self.peek(count)
        the_map[key] = val



    def do_raise(self, exc, cause):
        if exc is None:  # reraise
            exc_type, val, tb = self.last_exception
            if exc_type is None:
                return "exception"  # error
            else:
                return "reraise"

        elif type(exc) == type:
            # As in `raise ValueError`
            exc_type = exc
            val = exc()  # Make an instance.
        elif isinstance(exc, BaseException):
            # As in `raise ValueError('foo')`
            exc_type = type(exc)
            val = exc
        else:
            return "exception"  # error

        # If you reach this point, you're guaranteed that
        # val is a valid exception instance and exc_type is its class.
        # Now do a similar thing for the cause, if present.
        if cause:
            if type(cause) == type:
                cause = cause()
            elif not isinstance(cause, BaseException):
                return "exception"  # error

            val.__cause__ = cause

        self.last_exception = exc_type, val, val.__traceback__
        return "exception"



    ## Functions

    def byte_MAKE_FUNCTION(self, argc):
        name = self.pop()
        code = self.pop()
        globs = self.frame.f_globals
        closure = self.pop() if (argc & 0x8) else None
        ann = self.pop() if (argc & 0x4) else None
        kwdefaults = self.pop() if (argc & 0x2) else None
        defaults = self.pop() if (argc & 0x1) else None
        fn = Function(name, code, globs, defaults, kwdefaults, closure, self)
        self.push(fn)

    def byte_LOAD_CLOSURE(self, name):
        self.push(self.frame.cells[name])

    def byte_MAKE_CLOSURE(self, argc):
        # TODO: the py3 docs don't mention this change.
        name = self.pop()
        closure, code = self.popn(2)
        defaults = self.popn(argc)
        globs = self.frame.f_globals
        fn = Function(name, code, globs, defaults, None, closure, self)
        self.push(fn)

    def byte_CALL_FUNCTION_EX(self, arg):
        # Calls a function. The lowest bit of flags indicates whether the
        # var-keyword argument is placed at the top of the stack. Below
        # the var-keyword argument, the var-positional argument is on the
        # stack. Below the arguments, the function object to call is placed.
        # Pops all function arguments, and the function itself off the stack,
        # and pushes the return value.
        # Note that this opcode pops at most three items from the stack.
        # Var-positional and var-keyword arguments are packed by
        # BUILD_TUPLE_UNPACK_WITH_CALL and BUILD_MAP_UNPACK_WITH_CALL.
        # new in 3.6
        varkw = self.pop() if (arg & 0x1) else {}
        varpos = self.pop()
        return self.call_function(0, varpos, varkw)

    def byte_CALL_FUNCTION(self, arg):
        # Calls a function. argc indicates the number of positional arguments.
        # The positional arguments are on the stack, with the right-most
        # argument on top. Below the arguments, the function object to call is
        # on the stack. Pops all function arguments, and the function itself
        # off the stack, and pushes the return value.
        # 3.6: Only used for calls with positional args
        return self.call_function(arg, [], {})

    def byte_CALL_FUNCTION_VAR(self, arg):
        args = self.pop()
        return self.call_function(arg, args, {})

    def byte_CALL_FUNCTION_KW(self, argc):
        # changed in 3.6: keyword arguments are packed in a tuple instead
        # of a dict. argc indicates total number of args.
        kwargnames = self.pop()
        lkwargs = len(kwargnames)
        kwargs = self.popn(lkwargs)
        arg = argc - lkwargs
        return self.call_function(arg, [], dict(zip(kwargnames, kwargs)))

    def byte_CALL_FUNCTION_VAR_KW(self, arg):
        args, kwargs = self.popn(2)
        return self.call_function(arg, args, kwargs)

    def byte_CALL_METHOD(self, count):
        return self.call_function(count, [], {})


    def byte_RETURN_VALUE(self):
        self.return_value = self.pop()
        if self.frame.generator:
            self.frame.generator.finished = True
        return "return"


    # Coroutine opcodes

    def byte_GET_AWAITABLE(self):
        iterable = self.pop()
        print("byte_GET_AWAITABLE:", iterable )
        iter = self.get_awaitable_iter(iterable)
        if iscoroutinefunction(iter):
            # if iter.get_delegate() is not None:
            #     # 'w_iter' is a coroutine object that is being awaited,
            #     # '.w_yielded_from' is the current awaitable being awaited on.
            #     raise RuntimeError("coroutine is being awaited already")
            pass
        self.vm.push(iter)

    def byte_YIELD_VALUE(self):
        self.return_value = self.pop()
        return "yield"

    def byte_YIELD_FROM(self):
        u = self.pop()
        x = self.top()

        try:
            if not isinstance(x, Generator) or u is None:
                # Call next on iterators.
                retval = next(x)
            else:
                retval = x.send(u)
            self.return_value = retval
        except StopIteration as e:
            self.pop()
            self.push(e.value)
        else:
            # YIELD_FROM decrements f_lasti, so that it will be called
            # repeatedly until a StopIteration is raised.
            self.jump(self.frame.f_lasti - 1)
            # Returning "yield" prevents the block stack cleanup code
            # from executing, suspending the frame in its current state.
            return "yield"

    ## Importing
    def byte_IMPORT_NAME(self, name):
        level, fromlist = self.popn(2)
        print("1968:byte_IMPORT_NAME",name,level,fromlist)
        frame = self.frame
        self.push(__import__(name, frame.f_globals, frame.f_locals, fromlist, level))

    def byte_IMPORT_STAR(self):
        # TODO: this doesn't use __all__ properly.
        mod = self.pop()
        for attr in dir(mod):
            if attr[0] != "_":
                self.frame.f_locals[attr] = getattr(mod, attr)

    def byte_IMPORT_FROM(self, name):
        #mod = self.top()
        self.push(getattr(self.top(), name))

    ## And the rest...

    def byte_EXEC_STMT(self):
        exec( *self.popn(3) )

    def byte_STORE_LOCALS(self):
        self.frame.f_locals = self.pop()

    def byte_LOAD_BUILD_CLASS(self):
        global MONITOR
        # New in py3
#        if VirtualMachine.ASYNC:
#            print("  + async-build_class", self.frame)
        MONITOR+=1
        self.push(build_class)



async def async_run_code(vm, code, f_globals=None, f_locals=None):
    vm.AS = 1
    frame = vm.make_frame(code, f_globals=f_globals, f_locals=f_locals)
    val = await vm.run_frame(frame)

    # Check some invariants
    if vm.frames:  # pragma: no cover
        raise VirtualMachineError("Frames left over!")

    if vm.frame and vm.frame.stack:  # pragma: no cover
        raise VirtualMachineError("Data left on stack! %r" % vm.frame.stack)
    vm.AS = 0
    return val
















class vm_INTERFACE:

    READY = False


    exporter = 0

    def export(self, fn, *argv, **kw):
        VirtualMachine.exporter += 1
        try:
            sid = repr(fn)
            native = VirtualMachine.AS_RES.pop(sid)
            if asyncio.iscoroutinefunction(native._func):
                print("289: exporting coro")
                if len(argv):
                    argv = list(argv)
                    argv.insert(0, native._self)
                    return native._func(*argv, **kw)
                else:
                    return native._func(native._self, **kw)
            return native

        finally:
            VirtualMachine.exporter -= 1

    def lock(self):
        self.spinlock += 1

    def unlock(self):
        if self.spinlock > 0:
            self.spinlock -= 1


    def log(self, byteName, arguments, opoffset):
        """ Log arguments, block stack, and data stack for each opcode."""
        op = "%d: %s" % (opoffset, byteName)
        if arguments:
            op += " %r" % (arguments[0],)
        indent = "    " * (len(self.frames) - 1)
        stack_rep = repr(self.frame.stack)
        block_stack_rep = repr(self.frame.block_stack)

        log.info("  %sdata: %s" % (indent, stack_rep))
        log.info("  %sblks: %s" % (indent, block_stack_rep))
        log.info("%s%s" % (indent, op))









class VirtualMachineError(Exception):
    """For raising errors in the operation of the VM."""
    pass


class VirtualMachine(
        vm_MODE,
        vm_STACK,
        vm_JUMPS,
        vm_BLOCKS,
        vm_TRY_FINALLY,
        vm_CORE,
        vm_PRINT,
        vm_INTERFACE
    ):
    pass


if __name__ == '__main__':

    main_mod = sys.modules['__main__']

    import os
    import sys
    import time

    import pythons


    import asyncio

    sys.modules['aio_suspend'] = type(sys)('aio_suspend')

    filename = sys.argv[-1]

    source = open(filename,'r').read()

    # We have the source.  `compile` still needs the last line to be clean,
    # so make sure it is, then compile a code object from it.
    if not source or source[-1] != '\n':
        source += '\n'
    code = compile(source, filename, "exec")

    # Execute the source file.
    vm = VirtualMachine()
    aio.vm  = vm

    print("\n"*8)
    print(f"Welcome to Python{sys.version.split(' ',1)[0]}+1 async={vm.ASYNC}\n\n")


    if not vm.ASYNC:
        vm.run_code(code, f_globals=main_mod.__dict__)

    else:

        async def async_io_host(vm):
            while not aio.loop.is_closed():
                if vm.spinlock:
                    print('\n ******* HOST IO/SYSCALLS ********\n')
                    vm.unlock()
                await asyncio.sleep(1)

        async def async_io_render(vm):
            while not aio.loop.is_closed():
                if vm.READY:
                    break
                await aio.sleep(.5)

            print('async_io_render : rendering starting')

            while not aio.loop.is_closed():
                await asyncio.sleep(.016)
                try:
                    taskMgr.step()
                except Exception as e:
                    await aio.sleep(1)
                    print('render not ready', e)

        aio.loop.create_task( async_io_host(vm) )
        aio.loop.create_task( async_io_render(vm) )
        aio.loop.create_task( async_run_code(vm, code, f_globals=main_mod.__dict__) )

        if 1:
            sys.path.append('/data/git/aioprompt')
            import aioprompt
            aioprompt.schedule(aioprompt.step, 1)
        else:

            try:
                aio.loop.run_forever()
            except KeyboardInterrupt:
                aio.loop.close()

    print("\n"*8)

#

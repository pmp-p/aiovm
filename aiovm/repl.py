import sys
import builtins
import asyncio

from asyncio import *
builtins.aio = sys.modules[__name__]
sys.modules['asyncio'] = aio

aio.loop = aio.get_event_loop()
aio.loop.paused = False

async def asleep_ms(ms=0):
    await asyncio.sleep(float(ms)/1000)

aio.asleep_ms = asleep_ms
aio.asleep = aio.sleep


scheduled = None
scheduler = None
wrapper_ref = None


# TODO: display traceback safely at toplevel
import traceback

def print_exception(e, out=sys.stderr, **kw):
    kw["file"] = out
    traceback.print_exc(**kw)

sys.print_exception = print_exception


# ======== have asyncio loop runs interleaved with repl
if not sys.flags.inspect:
    print("Error: interpreter must be run with -i or PYTHONINSPECT must be set for using", __name__)
    raise SystemExit


def init():
    global scheduled, scheduler, wrapper_ref
    #! KEEP IT WOULD BE GC OTHERWISE!
    # wrapper_ref

    scheduled = []
    import ctypes
    try:
        ctypes = ctypes.this
    except:
        pass

    c_char_p = ctypes.c_char_p
    c_void_p = ctypes.c_void_p

    HOOKFUNC = ctypes.CFUNCTYPE(c_char_p)
    PyOS_InputHookFunctionPointer = c_void_p.in_dll(ctypes.pythonapi, "PyOS_InputHook")

    def scheduler():
        global scheduled
        # prevent reenter
        lq = len(scheduled)
        while lq:
            fn, a = scheduled.pop(0)
            fn(a)
            lq -= 1

    wrapper_ref = HOOKFUNC(scheduler)
    scheduler_c = ctypes.cast(wrapper_ref, c_void_p)
    PyOS_InputHookFunctionPointer.value = scheduler_c.value


# ========== asyncio stepping ================

def step(arg):
    global aio
    al = aio.loop
    if al.paused is None:
        al.close()
        return

    if al.is_closed():
        sys.__stdout__.write(f"\n:async: stopped\n{sys.ps1}")
        return

    if not al.paused:
        al.call_soon(al.stop)
        al.run_forever()

    if arg:
        scheduled.append((aio.step, arg))

init()
scheduled.append((aio.step, True))

del init


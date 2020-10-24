import sys
import repl
import tui

from vm import *

main_module = sys.modules['__main__']

sys.modules['aio_suspend'] = type(sys)('aio_suspend')

filename = sys.argv[-1]

source = ()

lines = []

# preload imports
pygame = False
for line in open(filename,'r').readlines():
    ls = line.strip()

    if ls.startswith('import '):
        pygame = pygame or (ls.find('pygame')>=0)
        exec(compile(ls, filename, "exec"), globals(), globals() )
    lines.append( line )

# We have the source.  `compile` still needs the last line to be clean,
# so make sure it is, then compile a code object from it.
if lines[-1]:
    lines.append('')


# get bytecode for async vm.
code = compile( "\n".join(lines), filename, "exec")


# asyncifier for the stdlib, the asyncified function bytecode must be in the async frame
# so have a look in the test code  "block_test.py"

def asyncify(modname,func):
    #print(f'asyncify {modname}.{func.__name__[4:]} => {func}')
    mod = __import__(modname)
    mod = sys.modules[modname]=mod
    setattr( aio,f'_{modname}', mod )
    #print("aio",aio)
    setattr( mod , func.__name__[4:] , func )
    return mod

builtins.asyncify = asyncify


if pygame:
    pygame.init()
    pygame.font.init()
    pygame.display.set_mode((1,1))


# get an async VM/interpreter

vm = VirtualMachine()
aio.vm  = vm

# say hi
print("\n"*8)
print(f"Welcome to Python{sys.version.split(' ',1)[0]}+1 async={vm.ASYNC} {__name__}\n\n")


# start the async "I/O manager"
async def async_io_host(vm):
    while not aio.loop.is_closed():
        if vm.spinlock:
            print('\n ******* HOST IO/SYSCALL ********\n')
            vm.unlock()
        await asyncio.sleep(1)

aio.loop.create_task( async_io_host(vm) )

# start async vm loop
aio.loop.create_task( async_run_code(vm, code, f_globals = main_module.__dict__) )


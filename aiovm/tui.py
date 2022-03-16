import sys

# http://www.linusakesson.net/programming/tty/
# fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))



try:
    aio
except:
    import asyncio as aio
    aio.loop = aio.get_event_loop()

try:
    overloaded
except:
    import builtins

    def overloaded(i, *attrs):
        for attr in attrs:
            if attr in i.__class__.__dict__:
                if attr in i.__dict__:
                    return True
        return False

    builtins.overloaded = overloaded







import time

class block:
    # use direct access, it is absolute addressing on raw terminal.
    out = sys.__stdout__.write


    # clrscr
    #out('\x1b[2J')

    out('\x1b[?69h')

    top = 0
    bottom = 0
    left = 0
    right = 0

    def __init__(self):
        self._tb = 0
        self._lr = 0

    def set(self, **kw):
        for k,v in kw.items():
            if hasattr(self.__class__,k):
                setattr(self,k,int(v))
            else:
                pdb("30: %s.%S = %s ?" % (self,k,v) )


    # save cursor activate local viewport
    @classmethod
    def margins_tb(cls, source):
        cls.out('\x1b[{};{}r'.format( source.top or '', source.bottom or 255) )

    @classmethod
    def margins_lr(cls, source):
        cls.out('\x1b[{};{}s'.format( source.left or '', source.right or 255) )

    def __enter__(self):
        # st
        # self.out("\x1b7\x1b[?25l')
        # xterm
        self.out("\x1b7\x1b[?25l")

        if overloaded(self, 'top', 'bottom'):
            self._tb +=1
            self.margins_tb(self)

        if overloaded(self, 'left', 'right'):
            self._lr +=1
            self.margins_lr(self)

        return self

    # restore cursor and workspace viewport
    def __exit__(self, *tb):

        while self._tb:
            self.out("\x1b[;r" * self._tb)
            self._tb = 0

        while self._lr:
            self.out("\x1b[;s" * self._lr)
            self._lr = 0

        if self.__class__.top or self.__class__.bottom:
            self.margins_tb(self.__class__)

        if self.__class__.left or self.__class__.right:
            self.margins_lr(self.__class__)

        self.out("\x1b8\x1b[?25h")


    # now all those are relative draw calls.

    def __call__(self, *a, **kw):
        # default center to 80x25
        z = kw.get("z", 12)
        x = kw.get("x", 40)
        dx = ""
        dz = ""

        # overflow cursor and then go back left or/and up
        if x<0 or z<0:
            if x<0:
                dx = "\x1b[{}D".format( str(-x) )
                x = 999
            if z<0:
                dz = "\x1b[{}A".format( str(-z) )
                z = 999
        self.out("\x1b[{};{}H{}{}{}".format(z,x,dx,dz," ".join(a)))


root = block()

async def render_ui(window):
    # ok on xterm, but not st+sixel
    # https://github.com/charlesdaniels/st/issues/4
    block.out('\x1b[?69h')


    def box(t,x,y,z):
        lines = t.split('\n')
        fill = "─"*len(t)
        if z<0:
            z = z - len(lines)
        if abs(z)>1:
            print( '┌%s┐' % fill, x=x, z=z)
        for t in lines:
            z+=1
            print( '│%s│' % t, x=x, z=z)
        print( '└%s┘' % fill, x=x, z=z+1)

    while not aio.loop.is_closed():
        with window as print:
            # draw a clock
            t =  " {:02}:{:02}:{:02} ☢ 99% ".format( *time.localtime()[3:6] )
            box(t,x=-20,y=0,z=+2)


        await aio.sleep(1)
        sys.stdout.flush()

aio.loop.create_task(render_ui(root))

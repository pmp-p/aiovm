import sys

# http://www.linusakesson.net/programming/tty/
# fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))



try:
    aio
except:
    import asyncio as aio
    aio.loop = aio.get_event_loop()

import time

class block:
    # use direct access, it is absolute addressing on raw terminal.
    out = sys.__stdout__.write


    # save cursor
    def __enter__(self):
        self.out("\x1b7\x1b[?25l")
        return self

    # restore cursor
    def __exit__(self, *tb):
        self.out("\x1b8\x1b[?25h")

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
            box(t,x=-20,y=-3,z=-2)


        await aio.sleep(1)
        sys.stdout.flush()

aio.loop.create_task(render_ui(root))

#====================================================================================================================

def aio_sleep(t):
    print("aio",aio)
    start = int( aio._time.time() * 1_000_000 )
    stop = start + int( t * 1_000_000 )
    while int(aio._time.time()*1_000_000) < stop:
        import aio_suspend
    return None

time = asyncify("time",aio_sleep)

#===================================================================================================================





import time
#import p ygame
import pickle
import math
import random
import os

time = sys.modules['time']


T=10

for i in range(1):

    print(f"""i'm blocking for {T} seconds with""",time.sleep)
    time.sleep(T)
    print('exiting previously "blocking" block')


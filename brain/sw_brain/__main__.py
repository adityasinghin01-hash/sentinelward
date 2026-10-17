import logging
import os
import time

def main():
    # Bound native-library parallelism within the single shared service process.
    for key in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS'): os.environ.setdefault(key,'1')
    from .io import MQTTBus
    from .research import Research
    from .service import BrainService
    logging.basicConfig(level=os.environ.get('SW_LOG_LEVEL','INFO'))
    bus=MQTTBus(); service=BrainService(bus,research=Research()); bus.connect()
    next_epoch_ms=(int(time.time()*1000)//5000+1)*5000
    deadline=time.monotonic()+(next_epoch_ms-int(time.time()*1000))/1000
    try:
        while True:
            bus.drain()
            if time.monotonic()>=deadline:
                service.tick(int(time.time()*1000))
                next_epoch_ms+=5000; deadline+=5
                if time.monotonic()-deadline>5:
                    next_epoch_ms=(int(time.time()*1000)//5000+1)*5000
                    deadline=time.monotonic()+(next_epoch_ms-int(time.time()*1000))/1000
            time.sleep(.02)
    except KeyboardInterrupt: pass
    finally: bus.close()

if __name__=='__main__': main()

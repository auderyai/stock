import time

class RateLimitedClient:
    """Retry the same read request after a rate error; never skip its matrix."""
    def __init__(self,client,clock=time.monotonic,sleep=time.sleep):
        self.client=client;self.clock=clock;self.sleep=sleep;self.delay=1.5;self.last=None;self.successes=0
    def _call(self,tr,path,block):
        for attempt in range(7):
            if self.last is not None:
                wait=self.delay-(self.clock()-self.last)
                if wait>0:self.sleep(wait)
            try:
                started=self.clock()
                result=self.client._call(tr,path,block)
                self.last=started
                self.successes+=1
                if self.successes>=20:
                    self.delay=max(1.5,self.delay*0.8)
                    self.successes=0
                return result
            except Exception as error:
                self.last=self.clock()
                rate='IGW00201' in str(error) or 'HTTP 429' in str(error) or '호출 거래건수' in str(error)
                if not rate or attempt==6:raise
                self.successes=0
                self.delay=min(6.0,max(2.0,self.delay*1.5))
                cooldown=min(60,10*(2**attempt))
                print(f'LS rate limit: wait {cooldown}s; retry same matrix {attempt+1}/6; pacing {self.delay:.2f}s',flush=True)
                self.sleep(cooldown)

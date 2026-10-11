import importlib.util
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
p=ROOT/'src/krx_research/infrastructure/xing_db/rate_limited_bridge.py'
spec=importlib.util.spec_from_file_location('rl',p); m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
class Clock:
 def __init__(self): self.t=0.; self.sleeps=[]
 def now(self): return self.t
 def sleep(self,s): self.sleeps.append(s); self.t+=s
class Inner:
 def connect(self): pass
 def close(self): pass
 def raw_tr(self,tr,v): return {'rows':[]}
c=Clock(); b=m.RateLimitedRawTrBridge(Inner(),sleep_fn=c.sleep,clock_fn=c.now)
for _ in range(201): b.raw_tr('t8429',{})
assert c.t >= 601.0, c.t
print('V41_7_QUOTA_RESUME_UNIT: PASS')

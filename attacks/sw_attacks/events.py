"""One flushed JSONL writer; event keys are exactly those in locked doc-00."""
import json
from pathlib import Path
import re

class EventLog:
    def __init__(self,runs_dir,run_id,origin_ms):
        if not isinstance(run_id,str) or re.fullmatch(r'[A-Za-z0-9_-]{1,80}',run_id) is None: raise ValueError('Invalid run_id')
        self.run_id=run_id; self.origin_ms=origin_ms
        self.path=Path(runs_dir)/run_id/'events.jsonl'
        self.path.parent.mkdir(parents=True,exist_ok=True)
        self.stream=self.path.open('a',encoding='utf-8')
    def write(self,now_ms,bed_id,event,detail):
        record={'run_id':self.run_id,'t_s':round((now_ms-self.origin_ms)/1000,6),'ts':int(now_ms),'bed_id':bed_id,'event':event,'detail':str(detail)}
        self.stream.write(json.dumps(record,separators=(',',':'),allow_nan=False)+'\n'); self.stream.flush()
    def close(self):
        if not self.stream.closed: self.stream.close()

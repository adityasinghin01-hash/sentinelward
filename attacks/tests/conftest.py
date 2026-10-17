import math
import pytest

@pytest.fixture
def frame():
    def make(t=0,bed='B05',**updates):
        data={'v':1,'type':'vitals','bed_id':bed,'device_id':'MON-'+bed[1:],'seq':t,'ts':t*1000,'fs':125,'ecg':[math.sin(i/8)+t/10000 for i in range(125)],'ppg':[500+50*math.sin(i/10) for i in range(125)],'abp':[90+10*math.sin(i/10) for i in range(125)] if bed=='B10' else None,'hr':75,'spo2':98,'rr':16,'nibp':None,'monitor_alarm':None}
        data.update(updates)
        return data
    return make

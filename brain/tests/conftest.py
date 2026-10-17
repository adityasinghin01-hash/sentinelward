import copy
import math
import pytest

@pytest.fixture
def frame():
    def make(sec=0, bed='B01', **updates):
        ecg = [0.8 * math.exp(-((i % 125 - 20)/3)**2) + 0.02 * math.sin(i) for i in range(125)]
        ppg = [500 + 100 * math.sin(2 * math.pi * (i-25)/125) for i in range(125)]
        data = {'v':1,'type':'vitals','bed_id':bed,'device_id':'MON-'+bed[1:], 'seq':sec,'ts':sec*1000,'fs':125,'ecg':ecg,'ppg':ppg,'abp':None,'hr':60,'spo2':98,'rr':16,'nibp':None,'monitor_alarm':None}
        data.update(updates)
        return copy.deepcopy(data)
    return make

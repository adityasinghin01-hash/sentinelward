"""Launch seams for existing services. No changes to simulator/ or agents/."""
import asyncio
import json
import os

from sw_common import Bus
from .containment import Containment, device_id
from .io import private_read


class MonitorBus:
    def __init__(self, env, client_id, *, bus_factory=Bus):
        self.env=env
        self.factory=bus_factory
        self.passwords=json.loads(private_read(os.environ['SW_MONITOR_CREDENTIALS']))
        self.control=bus_factory(env.mqtt_host,env.mqtt_port,client_id,username=env.mqtt_user,password=env.mqtt_pass)
        self.monitors={}
        self.control.connect()

    def publish(self,message):
        device=device_id(message.get('device_id'))
        if message.get('type')!='vitals' or message.get('bed_id')!='B'+device[-2:]:
            raise ValueError('Simulator may publish only device-bound vitals')
        if device not in self.monitors:
            bus=self.factory(self.env.mqtt_host,self.env.mqtt_port,device,username=device,password=self.passwords[device])
            self.monitors[device]=bus
            bus.connect(wait_s=0)
        return self.monitors[device].publish(message)

    def subscribe(self,pattern,handler):
        return self.control.subscribe(pattern,handler)

    def close(self):
        for bus in [self.control,*self.monitors.values()]: bus.close()


class AgentBroker:
    def __init__(self, helper, passwords):
        self.helper,self.passwords=helper,passwords

    @staticmethod
    def _device(device):
        name=device_id(device.device_id)
        if device.username!=name or device.client_id!=name or device.bed_id!='B'+name[-2:]:
            raise ValueError('Agent device binding does not match secured inventory')
        return name

    async def disabled(self,device):
        return await asyncio.to_thread(self.helper.disabled,self._device(device))

    async def disable(self,device):
        await asyncio.to_thread(self.helper.disable_client,self._device(device))

    async def enable(self,device):
        await asyncio.to_thread(self.helper.enable_client,self._device(device))

    async def clean_session(self,device):
        name=self._device(device)
        await asyncio.to_thread(self.helper.clean_session,name,self.passwords[name])


def simulator_main():
    import sw_sim.__main__ as simulator
    simulator.make_bus=MonitorBus
    raise SystemExit(simulator.main())


def agents_main():
    import sentinelward.cli as cli
    original=cli.build_team
    helper=Containment(os.environ['SW_DYNSEC_OPTIONS'],os.environ['SW_CONTAIN_AUDIT'])
    passwords=json.loads(private_read(os.environ['SW_MONITOR_CREDENTIALS']))
    # Fail at launch if credentials are missing; verify broker identity on each action.
    private_read(helper.options)
    def secured_team(settings,alerts):
        phase4,phase5=original(settings,alerts)
        phase4.broker=AgentBroker(helper,passwords)
        if phase4.policy is not None:
            phase4.policy=phase4.policy.model_copy(update={'version':'security-v2-hub'})
        return phase4,phase5
    cli.build_team=secured_team
    cli.main()

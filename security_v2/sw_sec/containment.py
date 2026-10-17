"""Narrow device-only mosquitto_ctrl wrapper, with state confirmation and audit."""
import re
import subprocess
import time
from pathlib import Path

from .io import audit, private_read
from .policy import DEVICES


UNENCRYPTED_WARNING = ("Warning: You are running mosquitto_ctrl without encryption.\n"
                       "This means all of the configuration changes you are making are visible on the network, including passwords.\n")


def ctrl_failed(result):
    remaining = result.stderr.replace(UNENCRYPTED_WARNING, '').strip()
    return bool(result.returncode or remaining or 'Error:' in result.stdout)


def device_id(value):
    if not isinstance(value,str) or not re.fullmatch(r'MON-\d{2}',value,flags=re.ASCII) or value not in DEVICES:
        raise ValueError('Device must be MON-01..MON-12')
    return value


class Containment:
    def __init__(self, options, audit_path, *, run=subprocess.run):
        self.options, self.audit_path, self.run = Path(options), Path(audit_path), run

    def _command(self, command, device=None):
        private_read(self.options)  # checks file permissions; never put its contents in argv
        argv=['mosquitto_ctrl','-o',str(self.options),'dynsec',command]
        if device is not None: argv.append(device_id(device))
        try:
            result=self.run(argv,capture_output=True,text=True,timeout=12,shell=False)
        except (OSError, subprocess.TimeoutExpired):
            raise RuntimeError('Broker control unavailable or timed out') from None
        # 2.0.18 ctrl can report plugin errors on stderr with a zero exit status.
        if ctrl_failed(result):
            raise RuntimeError('Broker rejected control command; diagnostics withheld')
        return result.stdout

    def disabled(self, device):
        output=self._command('getClient',device)
        fields=dict(line.split(':',1) for line in output.splitlines() if ':' in line)
        fields={k.strip():v.strip() for k,v in fields.items()}
        if fields.get('Username') != device or fields.get('Clientid') != device or fields.get('Disabled', 'false') not in ('true','false'):
            raise RuntimeError('Broker identity/state did not match inventory')
        # Mosquitto 2.0.18 serializes disabled only when true.
        return fields.get('Disabled', 'false')=='true'

    def _change(self, device, disabled, dry_run):
        device_id(device)
        event='disable_client' if disabled else 'enable_client'
        audit(self.audit_path,event,ts=time.time_ns()//1_000_000,device=device,result='requested',dry_run=dry_run)
        if dry_run: return
        try:
            self._command('disableClient' if disabled else 'enableClient',device)
            if self.disabled(device) != disabled:
                raise RuntimeError('Broker state change was not confirmed')
        except Exception:
            audit(self.audit_path,event,ts=time.time_ns()//1_000_000,device=device,result='failed')
            raise
        audit(self.audit_path,event,ts=time.time_ns()//1_000_000,device=device,result='confirmed')

    def disable_client(self, device, *, dry_run=False):
        self._change(device,True,dry_run)

    def enable_client(self, device, *, dry_run=False):
        self._change(device,False,dry_run)

    def list(self):
        return {device:self.disabled(device) for device in DEVICES}

    def clean_session(self, device, password, *, connect=None):
        """Wipe a saved session while all data ACLs are revoked, then leave disabled.

        A temporary enable is required to authenticate CleanSession=1. Removing
        its sole role first keeps both attacker and monitor powerless throughout.
        Finally disable BEFORE restoring the role. Crash midway is fail-closed:
        either disabled or enabled without any data/subscribe/receive permission.
        """
        from .mqtt_probe import clean_session
        connect = connect or clean_session
        device_id(device)
        self.disable_client(device)
        role='monitor-'+device[-2:]
        current=self._command('getClient',device)
        if role in current:
            self._role_command('removeClientRole',device,role)
        try:
            self._command('enableClient',device)
            connect('127.0.0.1',1883,device,password)
        finally:
            self._command('disableClient',device)
            if not self.disabled(device): raise RuntimeError('Cleanup did not leave device disabled')
            self._role_command('addClientRole',device,role)
        audit(self.audit_path,'clean_session',ts=time.time_ns()//1_000_000,device=device,result='confirmed')

    def _role_command(self, command, device, role):
        # Role is derived exclusively from the validated inventory ID.
        private_read(self.options)
        argv=['mosquitto_ctrl','-o',str(self.options),'dynsec',command,device,role]
        if command=='addClientRole': argv.append('0')
        try:
            result=self.run(argv,capture_output=True,text=True,timeout=12,shell=False)
        except (OSError,subprocess.TimeoutExpired):
            raise RuntimeError('Broker role change unavailable') from None
        if ctrl_failed(result):
            raise RuntimeError('Broker role change rejected')

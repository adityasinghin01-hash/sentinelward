"""Server transport and raw logging. Never logs credentials or session tokens."""
from __future__ import annotations
import base64
import hashlib
import json
import os
from pathlib import Path
import signal
import socket
import ssl
import struct
import subprocess
import sys
import threading
import time
from urllib.parse import urlsplit
import uuid

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'tests_system' / 'out'
RESULTS = ROOT / 'tests_system' / 'results'


def now_ms():
    return time.time_ns() // 1_000_000


def identifier(prefix):
    return prefix + '_' + time.strftime('%Y%m%d_%H%M%S', time.gmtime()) + '_' + uuid.uuid4().hex[:6]


class Unavailable(RuntimeError):
    """A deliberately non-secret explanation safe for a results file."""


def safe_error(exc):
    if isinstance(exc, Unavailable):
        return str(exc)
    # Exception text may include a token URL, password or DSN.
    if isinstance(exc, ModuleNotFoundError):
        return 'Missing dependency: ' + str(exc.name)
    response = getattr(exc, 'response', None)
    if response is not None:
        return type(exc).__name__ + ' HTTP ' + str(response.status_code)
    return type(exc).__name__


class JsonLog:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.file = Path(path).open('x', buffering=1)
        self.lock = threading.Lock()

    def write(self, data):
        with self.lock:
            self.file.write(json.dumps(data, allow_nan=False, separators=(',', ':')) + '\n')

    def close(self):
        with self.lock:
            self.file.flush()
            os.fsync(self.file.fileno())
            self.file.close()


class Capture:
    def __init__(self, directory):
        from sw_common import Bus, decode, validate, topic_for
        self.directory = Path(directory)
        self.started_ms = now_ms()
        self.log = JsonLog(self.directory / 'bus.jsonl')
        self.rows = []
        self.lock = threading.Lock()
        owner = self

        class ReceiptBus(Bus):
            def _on_message(self, client, userdata, message):
                stamp = now_ms()
                decoded, errors = decode(message.payload)
                if decoded and not errors:
                    try:
                        if topic_for(decoded) != message.topic:
                            errors = ['Payload does not match MQTT topic']
                    except ValueError:
                        errors = ['Invalid contract topic']
                data = dict(recv_ms=stamp, recv_mono_ns=time.monotonic_ns(), topic=message.topic,
                            retained=bool(message.retain), qos=message.qos, size_bytes=len(message.payload),
                            raw=message.payload.decode('utf-8', errors='replace'), message=decoded,
                            errors=errors or (validate(decoded) if decoded else ['Not an object']))
                owner.log.write(data)
                with owner.lock:
                    owner.rows.append(data)
                super()._on_message(client, userdata, message)

        self.bus = ReceiptBus(os.environ.get('MQTT_HOST', '127.0.0.1'), int(os.environ.get('MQTT_PORT', 1883)),
                              identifier('system-tests'), username=os.environ.get('MQTT_USER') or None,
                              password=os.environ.get('MQTT_PASS') or None)
        self.bus.subscribe(['ward/#', 'net/#'], lambda m, t: None)
        if not self.bus.connect(wait_s=5):
            self.close()
            raise ConnectionError('MQTT unavailable')
        time.sleep(.3)  # subscriptions are sent by on_connect before this returns

    def snapshot(self):
        with self.lock:
            return list(self.rows)

    def quiet(self, seconds=3):
        since = now_ms()
        time.sleep(seconds)
        return not any(not r['retained'] and r['recv_ms'] >= since and isinstance(r.get('message'), dict)
                       and r['message'].get('type') == 'vitals' for r in self.snapshot())

    def close(self):
        state = dict(started_ms=self.started_ms, ended_ms=now_ms(), connected_at_end=self.bus.is_connected, stats=self.bus.stats())
        self.bus.close()
        self.log.close()
        (self.directory / 'capture.json').write_text(json.dumps(state, indent=2))


class Api:
    def __init__(self, base, users):
        import httpx
        import yaml
        self.base = base.rstrip('/')
        parsed = urlsplit(self.base)
        if parsed.scheme not in ('http', 'https') or parsed.username or parsed.password or parsed.query:
            raise ValueError('Use a plain HTTP origin URL')
        self.client = httpx.Client(base_url=self.base, timeout=3, trust_env=False)
        try:
            config = yaml.safe_load(Path(users).read_text())
            admin = next(u for u in config['users'] if u['role'] == 'admin')
            response = self.client.post('/api/session', json={'username': admin['username'], 'pin': str(admin['pin'])})
            response.raise_for_status()
            self.token = response.json()['token']
            self.client.headers['Authorization'] = 'Bearer ' + self.token
        except BaseException:
            self.client.close()
            raise

    def get(self, path):
        return self.client.get(path)

    def post(self, path, body):
        response = self.client.post(path, json=body)
        response.raise_for_status()
        return response.json()

    def close(self):
        self.client.close()


class Poller:
    def __init__(self, api, directory):
        self.api, self.log = api, JsonLog(Path(directory) / 'ward_polls.jsonl')
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def run(self):
        deadline = time.monotonic()
        while not self.stop_event.is_set():
            begin = time.monotonic_ns()
            try:
                response = self.api.get('/api/ward')
                data = dict(recv_ms=now_ms(), status=response.status_code,
                            elapsed_ms=(time.monotonic_ns() - begin) / 1e6)
                if response.status_code == 200:
                    data['data'] = response.json()
                else:
                    data['error'] = 'HTTP status ' + str(response.status_code)
            except Exception as exc:
                data = dict(recv_ms=now_ms(), elapsed_ms=(time.monotonic_ns() - begin) / 1e6, error=safe_error(exc))
            self.log.write(data)
            deadline += 1
            self.stop_event.wait(max(0, deadline - time.monotonic()))

    def close(self):
        self.stop_event.set()
        self.thread.join(timeout=5)
        if self.thread.is_alive():
            raise RuntimeError('Poller failed to stop')
        self.log.close()


class WebSocketCapture:
    """Small RFC6455 receive client using stdlib only (httpx has no WS transport)."""
    def __init__(self, api, directory):
        self.stop_event = threading.Event()
        self.log = JsonLog(Path(directory) / 'ws.jsonl')
        self.sock = None
        self.api = api
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def exact(self, size):
        data = bytearray()
        while len(data) < size:
            if self.stop_event.is_set():
                raise EOFError()
            try:
                chunk = self.sock.recv(size - len(data))
            except socket.timeout:
                continue
            if not chunk:
                raise EOFError()
            data.extend(chunk)
        return bytes(data)

    def pong(self, payload):
        mask = os.urandom(4)
        self.sock.sendall(bytes([0x8a, 0x80 | len(payload)]) + mask + bytes(c ^ mask[i % 4] for i, c in enumerate(payload)))

    def run(self):
        try:
            parsed = urlsplit(self.api.base)
            self.sock = socket.create_connection((parsed.hostname, parsed.port or (443 if parsed.scheme == 'https' else 80)), timeout=3)
            if parsed.scheme == 'https':
                self.sock = ssl.create_default_context().wrap_socket(self.sock, server_hostname=parsed.hostname)
            key = base64.b64encode(os.urandom(16)).decode()
            self.sock.sendall((f'GET /ws HTTP/1.1\r\nHost: {parsed.netloc}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n'
                               f'Sec-WebSocket-Version: 13\r\nSec-WebSocket-Key: {key}\r\nAuthorization: Bearer {self.api.token}\r\n\r\n').encode())
            header = bytearray()
            while not header.endswith(b'\r\n\r\n'):
                if len(header) > 16384:
                    raise ValueError('Oversize upgrade')
                header.extend(self.exact(1))
            expected = base64.b64encode(hashlib.sha1((key + '258EAFA5-E914-47DA-95CA-C5AB0DC85B11').encode()).digest())
            headers = dict(line.split(b':', 1) for line in bytes(header).split(b'\r\n')[1:] if b':' in line)
            headers = {k.lower(): v.strip() for k, v in headers.items()}
            if b' 101 ' not in bytes(header).split(b'\r\n')[0] or headers.get(b'sec-websocket-accept') != expected:
                raise ConnectionError('WebSocket handshake rejected')
            self.sock.settimeout(.5)
            buffer, first_opcode = bytearray(), None
            while not self.stop_event.is_set():
                a, b = self.exact(2)
                final, opcode = bool(a & 0x80), a & 15
                size = b & 127
                if size == 126:
                    size = struct.unpack('!H', self.exact(2))[0]
                elif size == 127:
                    size = struct.unpack('!Q', self.exact(8))[0]
                if size > 8_000_000 or b & 0x80:
                    raise ValueError('Invalid/oversize server frame')
                payload = self.exact(size)
                if opcode == 8:
                    if not self.stop_event.is_set():
                        self.log.write(dict(recv_ms=now_ms(), error='Server closed WebSocket', close_code=int.from_bytes(payload[:2], 'big')))
                    return
                if opcode == 9:
                    self.pong(payload)
                    continue
                if opcode == 10:
                    continue
                if opcode in (1, 2):
                    first_opcode = opcode
                    buffer = bytearray()
                buffer.extend(payload)
                if len(buffer) > 8_000_000:
                    raise ValueError('Oversize fragmented message')
                if final:
                    if first_opcode == 1:
                        self.log.write(dict(recv_ms=now_ms(), message=json.loads(buffer)))
                    buffer, first_opcode = bytearray(), None
        except Exception as exc:
            if not self.stop_event.is_set():
                self.log.write(dict(recv_ms=now_ms(), error=safe_error(exc)))
        finally:
            if self.sock:
                self.sock.close()

    def close(self):
        self.stop_event.set()
        if self.sock:
            try:
                self.sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
        self.thread.join(timeout=5)
        self.log.close()


def stop_child(child):
    if child and child.poll() is None:
        child.send_signal(signal.SIGTERM)
        try:
            child.wait(timeout=10)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait(timeout=5)


def add_arguments(parser):
    parser.add_argument('--api', default='http://127.0.0.1:8000', help='Backend origin (no /api suffix)')
    parser.add_argument('--users', type=Path, default=ROOT / 'backend' / 'users.yaml')
    parser.add_argument('--sim-runs', type=Path, default=Path.home() / 'sw' / 'runs' / 'simulator')
    parser.add_argument('--attack-runs', type=Path, default=Path.home() / 'sw' / 'runs' / 'attacks')
    parser.add_argument('--packs', type=Path, default=Path(os.environ.get('SW_PACKS', str(Path.home() / 'sw' / 'packs'))))


def sim_command(args, mode, *extra):
    return [sys.executable, '-m', 'sw_sim', mode, '--packs', str(args.packs),
            '--script', str(ROOT / 'simulator' / 'ward_script.yaml'), *extra]


def safe_run_id(value):
    import re
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}', value):
        raise ValueError('Unsafe run_id')
    return value


def events_for(parent, run_id):
    safe_run_id(run_id)
    # Simulator can suffix a reused directory; unique test run ids avoid ambiguous joins.
    return Path(parent) / run_id / 'events.jsonl'

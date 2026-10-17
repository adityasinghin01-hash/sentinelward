"""Command line: python -m sw_sim run | listen | scale."""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Sequence

import sw_common

from .clock import RealClock, make_clock
from .config import Env, ScriptError, WardScript, check_run_id, format_t, load_env, load_script, parse_start_at
from .engine import STOP_RESET, STOP_SIGNAL, WardRun
from .listen import ControlError, Controller, parse_control
from .packs import PackError, load_packs
from .scale import FIRST_SCALE_BED, MAX_SCALE_BEDS, run_scale, scale_templates

log = logging.getLogger("sw_sim")

EXIT_OK, EXIT_RUNTIME, EXIT_CONFIG = 0, 1, 2


def default_run_id(prefix: str = "run") -> str:
    """run_YYYYMMDD_HHMMSS in UTC."""
    return f"{prefix}_{datetime.now(timezone.utc):%Y%m%d_%H%M%S}"


def make_bus(env: Env, client_id: str) -> Any:
    """Connect a sw_common.Bus to our own hub (never to a real monitor)."""
    bus_class = getattr(sw_common, "Bus", None)
    if bus_class is None:  # sw_common versions that keep Bus only in sw_common.bus
        from sw_common.bus import Bus as bus_class
    bus = bus_class(env.mqtt_host, env.mqtt_port, client_id, username=env.mqtt_user, password=env.mqtt_pass)
    if bus.connect() is False:
        log.warning("MQTT hub %s:%d not reachable yet; the bus keeps retrying, messages are dropped until then",
                    env.mqtt_host, env.mqtt_port)
    else:
        log.info("connected to MQTT hub %s:%d as %s", env.mqtt_host, env.mqtt_port, client_id)
    return bus


def install_stop_signals(on_stop: Callable[[], None]) -> None:
    """Call on_stop on Ctrl+C or SIGTERM (main thread only)."""
    def handler(signum: int, _frame: Any) -> None:
        log.info("received %s: stopping after the current second", signal.Signals(signum).name)
        on_stop()
    signal.signal(signal.SIGINT, handler)
    signal.signal(signal.SIGTERM, handler)


def _parse_beds(text: str | None) -> list[str] | None:
    if not text:
        return None
    return [b.strip().upper() for b in text.split(",") if b.strip()]


def _load(args: argparse.Namespace, env: Env) -> tuple[WardScript, dict]:
    script = load_script(args.script).select(_parse_beds(getattr(args, "beds_list", None)))
    packs_dir = Path(args.packs) if args.packs else env.packs_dir
    packs = load_packs(packs_dir, [b.pack_name for b in script.beds])
    return script, packs


def cmd_run(args: argparse.Namespace, env: Env) -> int:
    """run: play the ward (or a subset) once."""
    script, packs = _load(args, env)
    start_at = parse_start_at(args.start_at) if args.start_at else 0
    clock = make_clock(args.speed, args.dry_run)
    run_id = check_run_id(args.run_id) if args.run_id else default_run_id()
    runs_dir = Path(args.runs) if args.runs else env.runs_dir
    bus = None if args.dry_run else make_bus(env, script.mqtt_client_id)
    try:
        run = WardRun(script, packs, run_id=run_id, runs_dir=runs_dir, clock=clock, bus=bus,
                      start_at_s=start_at, dry_run=args.dry_run, dir_suffix="_dry" if args.dry_run else "")
        install_stop_signals(lambda: run.request_stop(STOP_SIGNAL))
        if bus is not None:
            def on_control(message: Any, topic: str) -> None:
                try:
                    command = parse_control(message, script.run_length_s)
                except ControlError as exc:
                    log.warning("ignoring control message: %s", exc)
                    return
                if command.cmd == "reset":
                    run.request_stop(STOP_RESET)
                else:
                    log.warning("'run' command ignored: use 'python -m sw_sim listen' for the Demo button")
            bus.subscribe(sw_common.DEMO_CONTROL_TOPIC, on_control)
        result = run.run()
    finally:
        if bus is not None:
            bus.close()
    print(f"{result.status}: {result.sent} messages sent ({result.invalid} invalid, {result.publish_errors} "
          f"publish errors), lag p99 {result.lag_p99_ms} ms, next {format_t(result.next_t_s)} -> {result.run_dir}")
    if not args.dry_run and not clock.fast and result.lag_p99_ms is not None and result.lag_p99_ms >= script.lag_budget_ms:
        log.warning("p99 send lag %.1f ms is over the %g ms budget", result.lag_p99_ms, script.lag_budget_ms)
    return EXIT_OK if result.invalid == 0 and result.publish_errors == 0 else EXIT_RUNTIME


def cmd_listen(args: argparse.Namespace, env: Env) -> int:
    """listen: wait for demo_control run/reset commands."""
    script, packs = _load(args, env)
    runs_dir = Path(args.runs) if args.runs else env.runs_dir
    bus = make_bus(env, script.mqtt_client_id)
    try:
        def factory(run_id: str, start_at_s: int) -> WardRun:
            return WardRun(script, packs, run_id=run_id, runs_dir=runs_dir, clock=RealClock(), bus=bus,
                           start_at_s=start_at_s)
        controller = Controller(factory, script.run_length_s)
        shutdown = threading.Event()
        install_stop_signals(shutdown.set)
        bus.subscribe(sw_common.DEMO_CONTROL_TOPIC, controller.on_message)
        log.info("listening on %s (%d beds ready)", sw_common.DEMO_CONTROL_TOPIC, len(script.beds))
        controller.serve(shutdown)
    finally:
        bus.close()
    return EXIT_OK


def cmd_scale(args: argparse.Namespace, env: Env) -> int:
    """scale: the T10 resource test with N quiet beds B13.."""
    script = load_script(args.script)
    packs_dir = Path(args.packs) if args.packs else env.packs_dir
    packs = load_packs(packs_dir, scale_templates(script))
    runs_dir = Path(args.runs) if args.runs else env.runs_dir
    bus = make_bus(env, f"{script.mqtt_client_id}_scale")
    try:
        report = run_scale(
            script, packs, n_beds=args.beds, seconds=args.seconds, run_id=default_run_id("scale"),
            runs_dir=runs_dir, clock=RealClock(), bus=bus,
            on_run=lambda run: install_stop_signals(lambda: run.request_stop(STOP_SIGNAL)),
            first_bed=args.first_bed, loop=args.loop,
        )
    finally:
        bus.close()
    print("\n".join(report.lines()))
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    """The argparse parser for all three commands."""
    parser = argparse.ArgumentParser(prog="python -m sw_sim", description=__doc__)
    parser.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--packs", help="bed pack folder (default: $SW_PACKS or ./packs)")
        p.add_argument("--script", default="ward_script.yaml", help="ward script (default: ./ward_script.yaml)")
        p.add_argument("--runs", help="output folder for runs (default: $SW_RUNS or ./runs)")

    p_run = sub.add_parser("run", help="play the ward once in real time")
    common(p_run)
    p_run.add_argument("--start-at", help="jump into the script, e.g. T+04:30")
    p_run.add_argument("--speed", type=float, default=1.0, help="virtual speed >= 1 (above 1: self-tests only)")
    p_run.add_argument("--beds", dest="beds_list", help="comma-separated subset, e.g. B03,B05")
    p_run.add_argument("--dry-run", action="store_true", help="build and validate every message, send nothing")
    p_run.add_argument("--run-id", help="run id (default: run_YYYYMMDD_HHMMSS, UTC)")
    p_run.set_defaults(func=cmd_run)

    p_listen = sub.add_parser("listen", help="wait for demo_control run/reset on ward/demo/control")
    common(p_listen)
    p_listen.add_argument("--beds", dest="beds_list", help="comma-separated subset, e.g. B03,B05")
    p_listen.set_defaults(func=cmd_listen)

    p_scale = sub.add_parser("scale", help=f"resource test: N quiet beds B13.. (max {MAX_SCALE_BEDS})")
    common(p_scale)
    p_scale.add_argument("--beds", type=int, required=True, help=f"number of extra beds, 1..{MAX_SCALE_BEDS}")
    p_scale.add_argument("--seconds", type=int, required=True, help="run length in seconds")
    p_scale.add_argument("--first-bed", type=int, default=FIRST_SCALE_BED,
                         help=f"first bed number (default {FIRST_SCALE_BED}; 1 = beds B01.. with the ward sim stopped)")
    p_scale.add_argument("--loop", action="store_true",
                         help="restart each pack at its end (seq/ts continue), for runs longer than a pack")
    p_scale.set_defaults(func=cmd_scale)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point; returns the process exit code."""
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s", stream=sys.stderr)
    try:
        env = load_env()
        return args.func(args, env)
    except (ScriptError, PackError, ValueError) as exc:
        log.error("%s", exc)
        return EXIT_CONFIG


if __name__ == "__main__":
    sys.exit(main())

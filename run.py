"""Verdure discovery engine entry point.

    python run.py            run forever: refresh on a schedule, re-rank when profiles change
    python run.py --once     run one refresh and exit (use this with cron / Task Scheduler)
    python run.py --rerank   rebuild user feeds from stored events without fetching sources
"""

from __future__ import annotations

import argparse
import logging
import signal
import sys
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

import yaml

from verdure.pipeline import refresh, rerank_only
from verdure.users import users_fingerprint

BASE_DIR = str(Path(__file__).resolve().parent)
PROFILE_CHECK_SECONDS = 30

_stop = False


def _handle_stop(signum, frame):
    global _stop
    _stop = True
    logging.getLogger("verdure").info("Stop requested; finishing current step and exiting.")


def load_config(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def setup_logging(cfg: dict, verbose: bool) -> None:
    log_path = Path(BASE_DIR) / cfg["paths"]["log_file"]
    log_path.parent.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s", "%Y-%m-%d %H:%M:%S")
    root = logging.getLogger()
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    for handler in (logging.StreamHandler(sys.stdout),
                    RotatingFileHandler(log_path, maxBytes=2_000_000, backupCount=3, encoding="utf-8")):
        handler.setFormatter(fmt)
        root.addHandler(handler)


def run_forever(cfg_path: str) -> None:
    log = logging.getLogger("verdure")
    signal.signal(signal.SIGINT, _handle_stop)
    signal.signal(signal.SIGTERM, _handle_stop)

    cfg = load_config(cfg_path)
    users_dir = str(Path(BASE_DIR) / cfg["paths"]["users_dir"])
    next_refresh = 0.0
    last_users = None

    log.info("Engine started. Refresh every %d min; checking profiles every %ds. Ctrl+C to stop.",
             cfg["schedule"]["refresh_minutes"], PROFILE_CHECK_SECONDS)
    while not _stop:
        now = time.time()
        try:
            if now >= next_refresh:
                cfg = load_config(cfg_path)  # pick up config edits without restarting
                refresh(cfg, BASE_DIR)
                last_users = users_fingerprint(users_dir)
                next_refresh = now + cfg["schedule"]["refresh_minutes"] * 60
            else:
                current = users_fingerprint(users_dir)
                if current != last_users:
                    rerank_only(cfg, BASE_DIR)
                    last_users = current
        except Exception:
            log.exception("Cycle failed; will retry in 5 minutes.")
            next_refresh = time.time() + 300

        for _ in range(PROFILE_CHECK_SECONDS):
            if _stop:
                break
            time.sleep(1)
    log.info("Engine stopped.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Verdure event discovery engine")
    parser.add_argument("--config", default=str(Path(BASE_DIR) / "config.yaml"))
    parser.add_argument("--once", action="store_true", help="run one refresh and exit")
    parser.add_argument("--rerank", action="store_true", help="re-rank feeds from stored events only")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    cfg = load_config(args.config)
    setup_logging(cfg, args.verbose)

    if args.rerank:
        rerank_only(cfg, BASE_DIR)
    elif args.once:
        refresh(cfg, BASE_DIR)
    else:
        run_forever(args.config)


if __name__ == "__main__":
    main()
#!/usr/bin/env python3
"""运行一次对比并启动本地网页。"""


import argparse
from contextlib import nullcontext
from http.server import ThreadingHTTPServer
import json
import os
from pathlib import Path
import signal
import sys
import threading

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from zonepick.application.datasets import dataset_paths
from zonepick.web.server import (
    PROJECT_ROOT, build_handler, load_scenario, parse_region, resolve_noise_config,
)
from zonepick.workbench.cleanup import temporary_run
from zonepick.workbench.compare import compare


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="ZonePick 一键公平评测 + 网页可视化")
    parser.add_argument("--scenario", default="free_field", help="预设场景名，默认 free_field")
    parser.add_argument("--algorithms", nargs="+", default=["das", "mvdr"],
                        help="对比算法名（identity 自动作为基线；默认含 几何导向矢量 MVDR）")
    parser.add_argument("--noise", action="store_true",
                        help="强制启用多类型真实噪声（默认按场景 noise_hint 决定）")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址，默认 127.0.0.1")
    parser.add_argument("--port", type=int, default=0, help="监听端口，默认 0 由系统分配")
    parser.add_argument("--datasets", help="数据路径配置，默认 configs/local/datasets.yaml")
    retention = parser.add_mutually_exclusive_group()
    retention.add_argument("--keep", action="store_true", help="保留本次产物（默认）")
    retention.add_argument("--temporary", action="store_true", help="退出时清理本次临时产物")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    os.chdir(ROOT)
    local = PROJECT_ROOT / "configs" / "local" / "datasets.yaml"
    datasets = dataset_paths(args.datasets or (str(local) if local.is_file() else None))
    config = load_scenario(args.scenario)
    noise_config = resolve_noise_config(config, cli_enabled=args.noise)

    retention = temporary_run(ROOT) if args.temporary else nullcontext(ROOT / "runs")
    with retention as run_root:
        return serve_run(args, config, datasets, noise_config, run_root)


def serve_run(args, config, datasets, noise_config, run_root):
    print("正在准备场景并运行公平对比，请稍候…", flush=True)
    directory, summary = compare(
        config, datasets, args.algorithms, output_root=run_root / "compare",
        noise_config=noise_config,
    )
    print("对比完成：" + json.dumps(summary, ensure_ascii=False), flush=True)

    server = ThreadingHTTPServer((args.host, args.port), build_handler(run_root, datasets=datasets))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://{args.host}:{server.server_port}/"
    print(f"网页已启动：{url}（按 Ctrl+C 结束）", flush=True)

    stop = threading.Event()

    def shutdown(signum, frame):
        stop.set()

    previous = {}
    for sig in (signal.SIGINT, signal.SIGTERM):
        previous[sig] = signal.signal(sig, shutdown)
    try:
        stop.wait()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        for sig, handler in previous.items():
            signal.signal(sig, handler)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

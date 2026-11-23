#!/usr/bin/env python3
"""ZonePick 一键入口：公平对比 → 网页可视化 → 退出自动清理。

直接执行 `python main.py` 即可：准备一次复杂噪声场景，让 identity / das 在同一份
输入上公平对比，起本地网页展示二维图、波形和多算法指标；按 Ctrl+C 停止服务后，
本次产物与可重建缓存会自动清理（--keep 可保留产物）。

各能力仍由 zonepick 包提供，本文件只是编排入口，方便一键运行。
"""

import argparse
from http.server import ThreadingHTTPServer
import json
import os
from pathlib import Path
import signal
import sys
import threading

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from zonepick.application.datasets import dataset_paths, read_mapping
from zonepick.web.server import (
    PROJECT_ROOT, build_handler, load_scenario, parse_region, resolve_noise_config,
)
from zonepick.workbench.cleanup import cleanup_generated
from zonepick.workbench.compare import compare


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="ZonePick 一键公平评测 + 网页可视化")
    parser.add_argument("--scenario", default="free_field", help="预设场景名，默认 free_field")
    parser.add_argument("--algorithms", nargs="+", default=["das", "mvdr"],
                        help="对比算法名（identity 自动作为基线；默认含 Souden 2010 MVDR）")
    parser.add_argument("--noise", action="store_true",
                        help="强制启用多类型真实噪声（默认按场景 noise_hint 决定）")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址，默认 127.0.0.1")
    parser.add_argument("--port", type=int, default=0, help="监听端口，默认 0 由系统分配")
    parser.add_argument("--datasets", help="数据路径配置，默认 configs/local/datasets.yaml")
    parser.add_argument("--keep", action="store_true", help="退出时保留本次产物目录")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    os.chdir(ROOT)
    local = PROJECT_ROOT / "configs" / "local" / "datasets.yaml"
    datasets = dataset_paths(args.datasets or (str(local) if local.is_file() else None))
    config = load_scenario(args.scenario)
    compare_root = ROOT / "runs" / "compare"
    noise_config = resolve_noise_config(config, cli_enabled=args.noise)

    print("正在准备场景并运行公平对比，请稍候…", flush=True)
    directory, summary = compare(
        config, datasets, args.algorithms, output_root=compare_root,
        noise_config=noise_config,
    )
    print("对比完成：" + json.dumps(summary, ensure_ascii=False), flush=True)

    server = ThreadingHTTPServer((args.host, args.port), build_handler(ROOT / "runs"))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://{args.host}:{server.server_port}/"
    print(f"网页已启动：{url}（按 Ctrl+C 结束并清理）", flush=True)

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
        if args.keep:
            print(f"已保留产物：{directory}", flush=True)
        else:
            removed = cleanup_generated([directory, compare_root], ROOT)
            print(f"收尾清理完成，删除 {removed} 个产物目标及字节码缓存", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

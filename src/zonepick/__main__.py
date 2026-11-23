"""ZonePick 命令行入口。"""

import argparse
import json

from zonepick.application import run
from zonepick.application.datasets import dataset_paths, inspect_datasets, read_mapping


def main():
    parser = argparse.ArgumentParser(description="ZonePick 离线区域语音增强与公平评测工作台")
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("datasets", help="抽查数据目录与实际格式")
    task = commands.add_parser("run", help="运行场景和几何 DAS（原 CLI 行为不变）")
    web = commands.add_parser("serve", help="启动本地网页可视化")
    bench = commands.add_parser("compare", help="公平对比多个算法（同一输入、统一评分）")
    split_cmd = commands.add_parser("split", help="生成参数化 train/val/test 冻结划分 manifest")
    for command in (check, task, bench):
        command.add_argument("--datasets", help="数据路径配置，默认读取 configs/local/datasets.yaml")
    task.add_argument("--config", required=True, help="场景 JSON")
    web.add_argument("--host", default="127.0.0.1", help="监听地址，默认 127.0.0.1")
    web.add_argument("--port", type=int, default=8000, help="监听端口，默认 8000")
    web.add_argument("--output-root", help="运行产物根目录，默认 runs/")
    bench.add_argument("--config", required=True, help="场景 JSON")
    bench.add_argument("--algorithms", nargs="+", default=["das"],
                       help="待对比算法名（identity 自动作为基线）")
    bench.add_argument("--noise", action="store_true", help="启用多类型真实噪声注入")
    bench.add_argument("--noise-config", help="噪声配置 JSON（可选，覆盖默认）")
    bench.add_argument("--output-root", help="对比产物根目录，默认 runs/compare/")
    split_cmd.add_argument("--root", required=True, help="数据根目录（FLAC/scenario 源）")
    split_cmd.add_argument("--output", required=True, help="manifest 输出路径（JSON）")
    split_cmd.add_argument("--train-ratio", type=float, default=0.70)
    split_cmd.add_argument("--val-ratio", type=float, default=0.15)
    split_cmd.add_argument("--test-ratio", type=float, default=0.15)
    split_cmd.add_argument("--seed", type=int, default=42)
    split_cmd.add_argument("--strategy", default="group", choices=["group", "file"])
    args = parser.parse_args()
    try:
        if args.command == "datasets":
            report = inspect_datasets(dataset_paths(args.datasets))
        elif args.command == "serve":
            from zonepick.web import serve
            serve(args.host, args.port, args.output_root)
            return
        elif args.command == "compare":
            from zonepick.workbench.compare import compare
            from zonepick.workbench.noise import NoiseConfig
            config = read_mapping(args.config)
            paths = {} if config["backend"] == "recording" else dataset_paths(args.datasets)
            noise_config = NoiseConfig(enabled=args.noise)
            if args.noise_config:
                noise_config = NoiseConfig(**read_mapping(args.noise_config))
            directory, summary = compare(
                config, paths, args.algorithms,
                output_root=args.output_root or "runs/compare",
                noise_config=noise_config,
            )
            report = {"compare_directory": str(directory), "summary": summary}
        elif args.command == "split":
            from zonepick.workbench.splits import SplitConfig, build_librispeech_split
            config = SplitConfig(
                train_ratio=args.train_ratio, val_ratio=args.val_ratio,
                test_ratio=args.test_ratio, seed=args.seed, strategy=args.strategy,
            )
            manifest = build_librispeech_split(args.root, config)
            path = manifest.write(args.output)
            report = {
                "manifest": str(path),
                "counts": {name: len(manifest.paths_for(name)) for name in ("train", "val", "test")},
            }
        else:
            config = read_mapping(args.config)
            paths = {} if config["backend"] == "recording" else dataset_paths(args.datasets)
            directory, scores = run(config, paths)
            report = {"run_directory": str(directory), **scores}
    except (OSError, ValueError, TypeError, RuntimeError, KeyError) as error:
        parser.exit(2, f"ZonePick: {error}\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

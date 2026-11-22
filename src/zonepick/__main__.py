"""ZonePick 命令行入口。"""

import argparse
import json

from zonepick.application import run
from zonepick.application.datasets import dataset_paths, inspect_datasets, read_mapping


def main():
    parser = argparse.ArgumentParser(description="ZonePick 离线区域语音增强")
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("datasets", help="抽查数据目录与实际格式")
    task = commands.add_parser("run", help="运行场景和几何 DAS")
    for command in (check, task):
        command.add_argument("--datasets", help="数据路径配置，默认读取 configs/local/datasets.yaml")
    task.add_argument("--config", required=True, help="场景 JSON")
    args = parser.parse_args()
    try:
        if args.command == "datasets":
            report = inspect_datasets(dataset_paths(args.datasets))
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

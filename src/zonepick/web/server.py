"""ZonePick v0.1-B 最小网页服务。

仅用 Python 标准库 http.server 提供静态页面和少量 JSON 接口；所有声学计算
仍然交给 zonepick.application.run / zonepick.workbench.compare，保证网页与
命令行复用同一应用层与同一公平评测口径。
"""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit

from zonepick.application import resolve_geometry, run
from zonepick.application.datasets import dataset_paths, read_mapping

PROJECT_ROOT = Path(__file__).resolve().parents[3]
STATIC_ROOT = Path(__file__).resolve().parent / "static"
SCENARIO_ROOT = PROJECT_ROOT / "configs" / "scenarios"
RUN_ID_PATTERN = re.compile(r"^[0-9]{8}T[0-9]{6}-[0-9a-f]{12}$")
SAFE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_\-]{1,128}$")
WAV_NAME_PATTERN = re.compile(r"^[A-Za-z0-9_\-]+\.wav$")
AUDIO_NAMES = ("mixture.wav", "reference_mic.wav", "enhanced.wav", "target.wav", "interference.wav")
STATIC_FILES = ("index.html",)


def list_scenarios():
    """返回 configs/scenarios 下可用的预设场景名。"""
    if not SCENARIO_ROOT.is_dir():
        return []
    return sorted(path.stem for path in SCENARIO_ROOT.glob("*.json") if path.is_file())


def load_scenario(name):
    """按预设名读取场景配置，拒绝路径穿越。"""
    if not isinstance(name, str) or name not in list_scenarios():
        raise ValueError(f"未知预设场景: {name}")
    return read_mapping(SCENARIO_ROOT / f"{name}.json")


def geometry_payload(config, datasets=None):
    """解析场景真实几何（麦克风/声源坐标），供预览画图。

    实测场景需要数据集才能拿到坐标；数据不可用时返回空几何并在 reason 中说明，
    前端据此显示提示而不是画一张空图。几何只用于可视化，不参与推理。
    """
    try:
        microphones, positions = resolve_geometry(config, datasets) if datasets else (
            config.get("microphones", []),
            [s["position"] for s in config.get("sources", []) if "position" in s],
        )
        return {
            "microphones": microphones,
            "sources": [{"index": i, "position": p} for i, p in enumerate(positions)],
            "reason": None,
        }
    except (OSError, ValueError, KeyError, RuntimeError) as error:
        return {
            "microphones": config.get("microphones", []),
            "sources": [
                {"index": i, "position": s["position"]}
                for i, s in enumerate(config.get("sources", [])) if "position" in s
            ],
            "reason": str(error),
        }


def scenario_summary(name, config, datasets=None):
    """给前端的预设摘要：中文名、区域默认值、噪声提示与可直接画图的真实几何。"""
    return {
        "name": name,
        "label": config.get("label") or name,
        "backend": config.get("backend"),
        "region": config.get("region", {}),
        "noise_hint": config.get("noise_hint"),
        "geometry": geometry_payload(config, datasets),
    }


# ---- 自定义场景：只接受白名单字段与严格类型，写回 configs/scenarios/<name>.json ----
CUSTOM_SCENARIO_KEYS = {
    "label", "backend", "sample_rate", "samples", "seed", "microphones",
    "channels", "reference_channel", "region", "sources", "array_id",
    "das", "noise_hint", "input_wav",
}
VALID_BACKENDS = {"free_field", "dechorate", "mcvampire", "recording"}


def _validate_sources(sources):
    if not isinstance(sources, list) or not sources:
        raise ValueError("sources 须为非空数组")
    result = []
    for source in sources:
        if not isinstance(source, dict):
            raise ValueError("每个声源须为对象")
        item = dict(source)
        if not isinstance(item.get("file"), str) or not item["file"]:
            raise ValueError("声源 file 须为非空字符串")
        if "position" in item:
            pos = item["position"]
            if (not isinstance(pos, (list, tuple)) or len(pos) != 3
                    or any(type(v) not in (int, float) for v in pos)):
                raise ValueError("声源 position 须为三个数字 [x, y, z]")
            item["position"] = list(pos)
        if "gain" in item and type(item["gain"]) not in (int, float):
            raise ValueError("声源 gain 须为数字")
        if "azimuth" in item and type(item["azimuth"]) not in (int, float):
            raise ValueError("声源 azimuth 须为数字")
        if "seat" in item and type(item["seat"]) is not int:
            raise ValueError("声源 seat 须为整数")
        result.append(item)
    return result


def parse_custom_scenario(payload):
    """把前端提交的自定义场景校验成可直接交给 application.run 的 config。

    以 base 预设为模板（保证数据集路径与实测阵列几何合法），仅覆盖白名单字段；
    名称须匹配 SAFE_NAME_PATTERN，避免路径穿越或覆盖既有预设。
    """
    if not isinstance(payload, dict):
        raise ValueError("请求体须为 JSON 对象")
    name = payload.get("name")
    if not isinstance(name, str) or not SAFE_NAME_PATTERN.fullmatch(name):
        raise ValueError("场景名须为 1–128 位字母、数字、下划线或连字符")
    if (SCENARIO_ROOT / f"{name}.json").exists():
        raise ValueError("该场景名已存在，请换一个")
    base = payload.get("base")
    config = dict(load_scenario(base)) if base else {}
    if not config:
        raise ValueError("须选择载入一个基础预设场景")
    overrides = payload.get("config") or {}
    if not isinstance(overrides, dict):
        raise ValueError("config 须为对象")
    unknown = set(overrides) - CUSTOM_SCENARIO_KEYS
    if unknown:
        raise ValueError(f"不支持的自定义字段: {', '.join(sorted(unknown))}")
    backend = overrides.get("backend", config.get("backend"))
    if backend not in VALID_BACKENDS:
        raise ValueError(f"未知 backend: {backend}")
    config.update(overrides)
    config["backend"] = backend
    config["label"] = overrides.get("label") or f"自定义 · {name}"
    if "region" in overrides or not config.get("region"):
        config["region"] = parse_region(overrides.get("region", config.get("region")))
    for key in ("sample_rate", "samples", "seed", "reference_channel", "array_id"):
        if key in config and type(config[key]) is not int:
            raise ValueError(f"{key} 须为整数")
    if "sample_rate" not in config or config["sample_rate"] <= 0:
        raise ValueError("须提供正整数 sample_rate")
    if "samples" not in config or config["samples"] <= 0:
        raise ValueError("须提供正整数 samples")
    if "microphones" in config:
        mics = config["microphones"]
        if (not isinstance(mics, list) or not mics
                or any(not isinstance(m, (list, tuple)) or len(m) != 3
                       or any(type(v) not in (int, float) for v in m) for m in mics)):
            raise ValueError("microphones 须为三维坐标数组")
        config["microphones"] = [list(m) for m in mics]
    if "channels" in config:
        channels = config["channels"]
        if (not isinstance(channels, list) or not channels
                or any(type(c) is not int or c < 0 for c in channels)):
            raise ValueError("channels 须为非负整数数组")
        config["channels"] = channels
    reference = config.get("reference_channel", 0)
    if type(reference) is not int or not 0 <= reference < len(config.get("channels", [0])):
        raise ValueError("reference_channel 须为所选通道内的有效索引")
    if "sources" in config:
        config["sources"] = _validate_sources(config["sources"])
    elif not config.get("sources"):
        raise ValueError("须提供 sources 声源列表")
    if "das" in config:
        das = config["das"]
        if not isinstance(das, dict):
            raise ValueError("das 须为对象")
        for key in ("n_fft", "sound_speed"):
            if key in das and type(das[key]) not in (int, float):
                raise ValueError(f"das.{key} 须为数字")
    if "noise_hint" in config and not isinstance(config["noise_hint"], dict):
        raise ValueError("noise_hint 须为对象")
    return name, config


def save_custom_scenario(name, config):
    """把校验后的自定义场景落盘，之后即可像普通预设一样被选择/运行。"""
    path = SCENARIO_ROOT / f"{name}.json"
    path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def parse_region(value):
    """校验前端提交的区域参数，返回可写回场景的 region 对象。"""
    if not isinstance(value, dict):
        raise ValueError("区域参数须为对象")
    center = value.get("center")
    if (not isinstance(center, (list, tuple)) or len(center) != 2
            or any(type(number) not in (int, float) for number in center)):
        raise ValueError("圆心须为两个数字 [x, y]")
    radius = value.get("radius")
    height = value.get("steering_height")
    if type(radius) not in (int, float) or radius <= 0:
        raise ValueError("区域半径须为正数")
    if type(height) not in (int, float):
        raise ValueError("指向高度须为数字")
    return {"center": list(center), "radius": radius, "steering_height": height}


def _compare_dirs(root):
    """公平对比记录的候选父目录：产物根目录本身，以及其下的 compare/ 子目录。

    main.py 把对比写到 runs/compare/<run_id>/，而普通 CLI 可能直接写到
    runs/<run_id>/；两处都要能列出、读取与提供音频。
    """
    root = Path(root)
    parents = [root]
    compare = root / "compare"
    if compare.is_dir():
        parents.append(compare)
    return parents


def resolve_noise_config(config, cli_enabled=False):
    """按场景 noise_hint 构造噪声配置；命令行 --noise 可强制开启。"""
    from zonepick.workbench.noise import noise_config_from_hint
    hint = config.get("noise_hint")
    override = True if cli_enabled else (False if hint is None else None)
    return noise_config_from_hint(hint, override_enabled=override)


def _find_compare_dir(root, run_id):
    """按 run_id 找到实际存放对比产物的目录，找不到返回 None。"""
    if not isinstance(run_id, str) or not SAFE_NAME_PATTERN.fullmatch(run_id):
        raise ValueError("对比记录名不合法")
    for parent in _compare_dirs(root):
        candidate = parent / run_id
        if candidate.is_dir() and (candidate / "manifest.json").is_file():
            return candidate
    return None


def list_compare_runs(root):
    """列出所有公平对比记录（含 manifest.json 的子目录）。"""
    runs = []
    for parent in _compare_dirs(root):
        for directory in sorted(parent.iterdir()):
            if not directory.is_dir() or not (directory / "manifest.json").is_file():
                continue
            manifest = read_mapping(directory / "manifest.json")
            scenario = manifest.get("scenario") or {}
            backend = scenario.get("backend", "")
            runs.append({
                "run_id": directory.name,
                "scenario": scenario.get("name") or backend,  # 配置文件通常无 name，回落显示 backend
                "backend": backend,
                "algorithms": manifest.get("algorithms", []),
            })
    return runs


def load_compare_run(root, run_id):
    """读取一次公平对比的完整清单与各算法指标。"""
    directory = _find_compare_dir(root, run_id)
    if directory is None:
        raise FileNotFoundError("对比记录不存在")
    manifest = read_mapping(directory / "manifest.json")
    scores = {}
    for algorithm in manifest.get("algorithms", []):
        path = directory / f"{algorithm}.metrics.json"
        if path.is_file():
            scores[algorithm] = read_mapping(path)
    return {
        "run_id": run_id,
        "scenario": manifest.get("scenario", {}),
        "algorithms": manifest.get("algorithms", []),
        "summary": manifest.get("summary", scores),
        "scores": scores,
        "audio": {name: f"/api/audio/{run_id}/{name}.wav"
                  for name in manifest.get("algorithms", [])
                  if (directory / f"{name}.wav").is_file()},
    }


def build_handler(output_root, datasets=None):
    """构造请求处理器；datasets 显式传入时优先使用（便于测试）。"""
    root = Path(output_root)

    def resolve_datasets():
        if datasets is not None:
            return datasets
        local = PROJECT_ROOT / "configs" / "local" / "datasets.yaml"
        return dataset_paths(str(local) if local.is_file() else None)

    class ZonePickHandler(BaseHTTPRequestHandler):
        server_version = "ZonePickWeb/0.1"

        def _send(self, status, body, content_type):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _send_json(self, status, payload):
            body = json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
            self._send(status, body, "application/json; charset=utf-8")

        def _send_error(self, status, message):
            self._send_json(status, {"error": str(message)})

        def do_GET(self):
            path = urlsplit(self.path).path
            try:
                if path == "/":
                    path = "/static/index.html"
                if path.startswith("/static/"):
                    name = unquote(path[len("/static/"):])
                    if name not in STATIC_FILES:
                        self._send_error(404, "页面不存在")
                        return
                    self._send(200, (STATIC_ROOT / name).read_bytes(),
                               "text/html; charset=utf-8")
                    return
                if path == "/api/scenarios":
                    self._send_json(200, [
                        scenario_summary(name, load_scenario(name), resolve_datasets())
                        for name in list_scenarios()
                    ])
                    return
                if path.startswith("/api/preview/"):
                    name = unquote(path[len("/api/preview/"):])
                    config = load_scenario(name)
                    self._send_json(200, {
                        "name": name,
                        "geometry": geometry_payload(config, resolve_datasets()),
                        "region": config.get("region", {}),
                    })
                    return
                if path == "/api/compare":
                    self._send_json(200, list_compare_runs(root))
                    return
                if path.startswith("/api/compare/"):
                    run_id = unquote(path[len("/api/compare/"):])
                    self._send_json(200, load_compare_run(root, run_id))
                    return
                if path.startswith("/api/runs/"):
                    run_id = unquote(path[len("/api/runs/"):])
                    if not RUN_ID_PATTERN.fullmatch(run_id):
                        self._send_error(404, "运行记录不存在")
                        return
                    directory = root / run_id
                    if not directory.is_dir():
                        self._send_error(404, "运行记录不存在")
                        return
                    scenario = read_mapping(directory / "scenario.json")
                    metrics = read_mapping(directory / "metrics.json")
                    self._send_json(200, {"run_id": run_id, "scenario": scenario, "metrics": metrics})
                    return
                if path.startswith("/api/audio/"):
                    parts = [unquote(part) for part in path[len("/api/audio/"):].split("/")]
                    if (len(parts) != 2 or not SAFE_NAME_PATTERN.fullmatch(parts[0])
                            or not WAV_NAME_PATTERN.fullmatch(parts[1])):
                        self._send_error(404, "音频不存在")
                        return
                    audio = None
                    for parent in _compare_dirs(root):
                        candidate = parent / parts[0] / parts[1]
                        if candidate.is_file():
                            audio = candidate
                            break
                    if audio is None:
                        self._send_error(404, "音频不存在")
                        return
                    self._send(200, audio.read_bytes(), "audio/wav")
                    return
                self._send_error(404, "接口不存在")
            except FileNotFoundError as error:
                self._send_error(404, error)
            except (OSError, ValueError, TypeError, KeyError, RuntimeError) as error:
                self._send_error(400, error)
            except Exception:  # 未预期异常不把内部细节暴露给浏览器
                self._send_error(500, "服务内部错误")

        def do_POST(self):
            path = urlsplit(self.path).path
            if path == "/api/scenarios/custom":
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    if length <= 0 or length > 1024 * 1024:
                        raise ValueError("请求体须为不超过 1 MiB 的 JSON")
                    payload = json.loads(self.rfile.read(length))
                    name, config = parse_custom_scenario(payload)
                    save_custom_scenario(name, config)
                    self._send_json(201, {
                        "name": name,
                        "label": config.get("label"),
                        "summary": scenario_summary(name, config, resolve_datasets()),
                    })
                except (OSError, ValueError, TypeError, KeyError, RuntimeError, json.JSONDecodeError) as error:
                    self._send_error(400, error)
                except Exception:
                    self._send_error(500, "服务内部错误")
                return
            if path != "/api/runs":
                self._send_error(404, "接口不存在")
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0 or length > 1024 * 1024:
                    raise ValueError("请求体须为不超过 1 MiB 的 JSON")
                payload = json.loads(self.rfile.read(length))
                if not isinstance(payload, dict):
                    raise ValueError("请求体须为 JSON 对象")
                scenario_name = payload.get("scenario")
                config = load_scenario(scenario_name)
                config["region"] = parse_region(payload.get("region"))
                directory, scores = run(config, resolve_datasets(), root)
                self._send_json(201, {
                    "run_id": directory.name,
                    "metrics": scores,
                })
            except (OSError, ValueError, TypeError, KeyError, RuntimeError, json.JSONDecodeError) as error:
                self._send_error(400, error)
            except Exception:
                self._send_error(500, "服务内部错误")

    return ZonePickHandler


def serve(host="127.0.0.1", port=8000, output_root=None):
    """启动本地网页服务（阻塞直到 Ctrl+C）。"""
    os.chdir(PROJECT_ROOT)  # 数据配置中的相对路径按项目根目录解析
    root = Path(output_root) if output_root else PROJECT_ROOT / "runs"
    root.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer((host, port), build_handler(root))
    print(f"ZonePick 网页已启动: http://{host}:{server.server_port}/", flush=True)
    print(f"运行产物目录: {root}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nZonePick 网页服务已停止", flush=True)
    finally:
        server.server_close()

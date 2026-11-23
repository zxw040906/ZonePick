"""ZonePick v0.1-B 最小网页服务。

仅用 Python 标准库 http.server 提供静态页面和少量 JSON 接口；所有声学计算
仍然交给 zonepick.application.run，保证网页与命令行复用同一应用层。
"""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit

from zonepick.application import run
from zonepick.application.datasets import dataset_paths, read_mapping

PROJECT_ROOT = Path(__file__).resolve().parents[3]
STATIC_ROOT = Path(__file__).resolve().parent / "static"
SCENARIO_ROOT = PROJECT_ROOT / "configs" / "scenarios"
RUN_ID_PATTERN = re.compile(r"^[0-9]{8}T[0-9]{6}-[0-9a-f]{12}$")
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


def scenario_summary(name, config):
    """给前端的预设摘要：区域默认值与可直接画图的几何。"""
    geometry = {
        "microphones": config.get("microphones", []),
        "sources": [
            {"index": index, "position": source["position"]}
            for index, source in enumerate(config.get("sources", []))
            if "position" in source
        ],
    }
    return {
        "name": name,
        "backend": config.get("backend"),
        "region": config.get("region", {}),
        "geometry": geometry,
    }


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
                        scenario_summary(name, load_scenario(name))
                        for name in list_scenarios()
                    ])
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
                    if len(parts) != 2 or not RUN_ID_PATTERN.fullmatch(parts[0]) or parts[1] not in AUDIO_NAMES:
                        self._send_error(404, "音频不存在")
                        return
                    audio = root / parts[0] / parts[1]
                    if not audio.is_file():
                        self._send_error(404, "音频不存在")
                        return
                    self._send(200, audio.read_bytes(), "audio/wav")
                    return
                self._send_error(404, "接口不存在")
            except (OSError, ValueError, TypeError, KeyError, RuntimeError) as error:
                self._send_error(400, error)
            except Exception:  # 未预期异常不把内部细节暴露给浏览器
                self._send_error(500, "服务内部错误")

        def do_POST(self):
            path = urlsplit(self.path).path
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

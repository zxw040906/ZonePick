"""ZonePick 最小网页入口（标准库 http.server）。"""

from zonepick.web.server import build_handler, serve

__all__ = ["build_handler", "serve"]

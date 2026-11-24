"""MIT License

Copyright (c) 2023 - present Vocard Development

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

from __future__ import annotations

import logging
import math
import time
from typing import Any

from aiohttp import web
from discord.ext import commands

from .mongodb import MongoDBHandler
from .pool import NodePool


class HealthServer:
    """Lightweight HTTP health check server exposing /health and /healthz."""

    def __init__(
        self,
        bot: commands.Bot,
        *,
        host: str = "0.0.0.0",
        port: int = 8080,
        require_lavalink: bool = False,
        version: str = "",
    ) -> None:
        self._bot: commands.Bot = bot
        self._host: str = host
        self._port: int = port
        self._require_lavalink: bool = require_lavalink
        self._version: str = version
        self._started_at: float = time.monotonic()
        self._runner: web.AppRunner | None = None
        self._site: web.TCPSite | None = None
        self._logger: logging.Logger = logging.getLogger("vocard.health")

    def build_payload(self, *, strict: bool = False) -> tuple[int, dict[str, Any]]:
        """Build the HTTP status code and JSON health payload."""
        discord_ready = bool(self._bot.is_ready() and not self._bot.is_closed())
        raw_latency = getattr(self._bot, "latency", float("nan"))
        latency_ms = (
            round(raw_latency * 1000, 2)
            if isinstance(raw_latency, (int, float)) and math.isfinite(raw_latency)
            else None
        )

        mongodb_connected = MongoDBHandler._client is not None

        nodes_status = {
            identifier: {
                "available": bool(node._available),
                "connected": bool(node.is_connected),
                "players": len(node._players),
            }
            for identifier, node in NodePool._nodes.items()
        }
        total_nodes = len(nodes_status)
        connected_nodes = sum(
            1 for node_info in nodes_status.values()
            if node_info["available"] and node_info["connected"]
        )

        if not discord_ready or not mongodb_connected:
            status_str = "unhealthy"
            http_status = 503
        elif total_nodes > 0 and connected_nodes == 0:
            if strict or self._require_lavalink:
                status_str = "unhealthy"
                http_status = 503
            else:
                status_str = "degraded"
                http_status = 200
        else:
            status_str = "ok"
            http_status = 200

        payload: dict[str, Any] = {
            "status": status_str,
            "version": self._version,
            "uptime_seconds": int(time.monotonic() - self._started_at),
            "discord": {
                "ready": discord_ready,
                "latency_ms": latency_ms,
                "guilds": len(getattr(self._bot, "guilds", ())),
                "players": len(getattr(self._bot, "voice_clients", ())),
            },
            "mongodb": {
                "connected": mongodb_connected,
            },
            "lavalink": {
                "total_nodes": total_nodes,
                "connected_nodes": connected_nodes,
                "nodes": nodes_status,
            },
        }
        return http_status, payload

    async def _handle_health(self, request: web.Request) -> web.Response:
        strict = request.query.get("strict", "").lower() in ("true", "1", "yes")
        http_status, payload = self.build_payload(strict=strict)
        return web.json_response(payload, status=http_status)

    async def start(self) -> None:
        """Start the HTTP health check server."""
        if self._runner is not None:
            return

        app = web.Application()
        app.router.add_get("/health", self._handle_health)
        app.router.add_get("/healthz", self._handle_health)

        self._runner = web.AppRunner(app, access_log=None)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, self._host, self._port)
        await self._site.start()
        self._logger.info("Health check server listening on http://%s:%s/health", self._host, self._port)

    async def stop(self) -> None:
        """Stop the HTTP health check server cleanly."""
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None
            self._site = None
            self._logger.info("Health check server stopped.")

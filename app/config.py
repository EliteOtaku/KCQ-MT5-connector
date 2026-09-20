# 环境配置：全部可调参数集中于此，其余模块只读 Settings，禁止散落 os.environ。

from __future__ import annotations

import os
from dataclasses import dataclass

# 对齐开关合法取值：on=高周期按 UTC 自然边界重采样 / off=取原生周期边界
ALIGN_MODES = ("on", "off")


def _parse_bool(raw: str | None, default: bool) -> bool:
    """解析布尔环境变量；缺省回落 default，非法值视为 default。"""
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() not in ("0", "false", "no", "off")


@dataclass(frozen=True)
class Settings:
    """连接器运行配置（由 load_settings 从环境读取）。"""

    port: int = 8090
    # MT5 终端全路径；缺省时自动探测已知 Exness 安装路径
    terminal_path: str | None = None
    # 仅允许 Exness 平台（公司/服务器名校验）
    exness_only: bool = True
    # 对齐开关：on=高周期对齐到 UTC 自然边界 / off=取原生周期边界
    align_mode: str = "on"
    # 服务器 UTC 偏移覆盖（小时）；缺省走实测
    server_utc_offset_override: int | None = None
    # 活跃订阅轮询基线（秒）：tick 探针间隔
    active_poll_seconds: float = 1.0
    # 无观察者后的残留轮询基线（秒）
    background_poll_seconds: float = 5.0
    # 静默退避封顶（秒）
    quiet_backoff_cap_seconds: float = 30.0
    # 终端连接心跳间隔（秒）
    heartbeat_seconds: float = 5.0
    # SSE keepalive 注释帧间隔（秒）
    sse_keepalive_seconds: float = 15.0
    # 每流环形缓冲帧数（Last-Event-ID 重放窗口）
    ring_buffer_frames: int = 500
    # 订阅建立时快照推送的尾部根数
    snapshot_bars: int = 2
    # 服务器偏移复测间隔（秒）
    clock_recheck_seconds: float = 300.0
    # 逐笔 tick 轮询间隔（秒）
    tick_poll_seconds: float = 0.25
    # 单次增量拉取的 tick 上限
    tick_pull_max: int = 5000
    # tick 去重窗口（最近 N 笔；覆盖 copy_ticks_from 秒级取整造成的重复）
    tick_seen_window: int = 8192


def load_settings(env: dict[str, str] | None = None) -> Settings:
    """从环境变量构造 Settings；非法值回落默认并保持启动不中断。"""
    source = dict(os.environ if env is None else env)

    align_raw = source.get("ALIGN_UTC", "on").strip().lower()
    if align_raw not in ALIGN_MODES:
        align_raw = "on"

    offset_raw = source.get("EXNESS_SERVER_UTC_OFFSET", "").strip()
    try:
        offset_override = int(offset_raw.replace("+", "")) if offset_raw else None
    except ValueError:
        offset_override = None

    try:
        port = int(source.get("MT5_PORT", "8090"))
    except ValueError:
        port = 8090

    try:
        tick_poll = float(source.get("MT5_TICK_POLL_SECONDS", "0.25"))
    except ValueError:
        tick_poll = 0.25
    if tick_poll <= 0:
        tick_poll = 0.25

    try:
        tick_pull_max = int(source.get("MT5_TICK_PULL_MAX", "5000"))
    except ValueError:
        tick_pull_max = 5000
    if tick_pull_max <= 0:
        tick_pull_max = 5000

    return Settings(
        port=port,
        terminal_path=source.get("MT5_TERMINAL_PATH", "").strip() or None,
        exness_only=_parse_bool(source.get("EXNESS_ONLY"), True),
        align_mode=align_raw,
        server_utc_offset_override=offset_override,
        tick_poll_seconds=tick_poll,
        tick_pull_max=tick_pull_max,
    )

# 连接器入口（向后兼容保留）：uv run python ./server.py。
# 新代码请用 `python -m mt5connector` 或安装后的 `mt5connector-server`。

from mt5connector.__main__ import main

if __name__ == "__main__":
    main()

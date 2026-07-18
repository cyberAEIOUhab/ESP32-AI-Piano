"""
mcp_server.py — ESP32 AI Piano 工具链 MCP 服务器
==================================================

基于 MCP (Model Context Protocol) Python SDK 实现的工具服务器。
通过 stdio 传输与 Claude Code 通信，将串口监控等硬件工具暴露为
AI 可调用的 Tool。

V2 架构变更：
  服务器启动时立即建立串口连接并启动后台采集线程，无需等待
  第一次工具调用。所有 ESP32 输出被持续缓存，AI 随时查询
  "最近发生了什么"。

=== 如何被 Claude Code 连接（供理解，配置需自行操作） ===

Claude Code 通过 MCP 协议与本文件通信：

  1. 启动方式：Claude Code 读取配置文件中的 command 字段，
     以子进程方式启动本文件：
       python path/to/toolchain/mcp_server.py

  2. 通信协议：JSON-RPC over stdio
     - stdout → 服务器发送 JSON-RPC 响应给 Claude Code
     - stderr → 服务器日志（不会干扰协议通信）
     - stdin  → Claude Code 发送 JSON-RPC 请求给服务器

  3. 发现工具：Claude Code 连接后首先发送 tools/list 请求，
     本服务器返回已注册的工具列表（含 name/description/inputSchema）。
     Claude 根据这些信息在对话中自动判断何时调用哪个工具。

  4. 调用工具：用户说"帮我看看 ESP32 在输出什么"时，Claude 根据
     serial_monitor 工具的 description 判断匹配，发送 tools/call
     请求。本服务器从后台缓冲区直接查询缓存数据，毫秒级返回。

  5. Claude Code 配置示例（放在 ~/.claude/claude-code.json 或项目
     .mcp.json 中）：
       {
         "mcpServers": {
           "esp32-piano": {
             "command": "python",
             "args": ["toolchain/mcp_server.py"],
             "cwd": "C:/Users/notch/Desktop/ESP32-AI-Piano"
           }
         }
       }

=== 当前状态 ===

  已注册工具：serial_monitor（1个）
  待注册工具：file_transfer, execute_program, reset_device,
              fetch_logs, report_error（5个）
"""

import sys
import os
import json
import logging
import asyncio

# 确保 toolchain 目录在 sys.path 中，使工具模块可导入
_TOOLCHAIN_DIR = os.path.dirname(os.path.abspath(__file__))
if _TOOLCHAIN_DIR not in sys.path:
    sys.path.insert(0, _TOOLCHAIN_DIR)

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

# ─── 日志配置 ───────────────────────────────────────────────
# MCP 协议使用 stdout 传输 JSON-RPC，因此日志必须输出到 stderr，
# 否则会破坏协议消息格式导致连接失败。

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [%(levelname)s] %(name)s: %(message)s',
    stream=sys.stderr,
)
logger = logging.getLogger('mcp_server')


# ─── 服务器实例 ─────────────────────────────────────────────

app = Server("esp32-piano-toolchain")
logger.info("MCP Server 'esp32-piano-toolchain' 已创建（V2: 后台持续采集模式）")


# ─── 后台采集预启动 ─────────────────────────────────────────
# 在服务器启动时立即建立串口连接并开启后台采集线程。
# 这样从启动第一刻起 ESP32 的所有输出都被缓存，不会因为
# "AI 还没调用工具"而漏掉数据。

def _init_serial_collection() -> bool:
    """
    在 MCP Server 启动时初始化串口连接和后台采集。

    这是 V2 架构的核心：后台采集线程从服务器启动即开始运行，
    独立于任何工具调用。AI 连接后随时可以查询历史缓存。
    """
    from serial_connection import SerialConnection
    conn = SerialConnection()

    if not conn.connect():
        logger.warning("串口连接失败，后台采集未启动（稍后工具调用时会重试）")
        return False

    if not conn.start_background_collection():
        logger.warning("后台采集启动失败")
        return False

    logger.info("后台串口采集已启动 — ESP32 输出将持续被缓存")
    return True


# ─── 工具注册：list_tools ───────────────────────────────────

@app.list_tools()
async def list_tools() -> list[Tool]:
    """
    返回当前所有可用工具的元数据。

    Claude Code 连接后会自动调用此方法获取工具列表。
    每个工具的 description 和 inputSchema 会被 Claude 用于
    判断"用户这句话是否该调用这个工具"。

    添加新工具时，只需在此函数中追加 Tool 对象即可。
    """
    tools = [
        Tool(
            name="serial_monitor",
            description=(
                "查询 ESP32 串口输出的最近历史记录（V2: 后台缓存查询）。"
                "ESP32 的所有 print() 输出从 MCP Server 启动起就被持续"
                "采集并缓存，此工具从缓存中查询最近 N 秒的数据，立即返回。"
                "适用于以下场景："
                "(1) 查看 ESP32 当前运行状态（如数字钢琴按键记录）；"
                "(2) 诊断固件问题（捕获异常信息和 Traceback）；"
                "(3) 验证固件修改是否生效（上传代码后观察输出变化）；"
                "(4) 回顾「刚才发生了什么」（不需要提前掐时机监控）。"
                "串口配置：COM3, 115200bps。"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "duration_sec": {
                        "type": "number",
                        "description": (
                            "查询最近多少秒内的缓存数据，默认 10 秒。"
                            "取值范围 1~300 秒。数值越大返回的数据越多。"
                            "注意：这是查询后台已缓存的历史数据窗口，"
                            "不会实时等待。调用立即返回（毫秒级）。"
                        ),
                        "default": 10.0,
                    },
                },
                "required": [],
            },
        ),
        # ─── 以下工具待实现 ─────────────────────────────────
        # Tool(name="file_transfer", ...),
        # Tool(name="execute_program", ...),
        # Tool(name="reset_device", ...),
        # Tool(name="fetch_logs", ...),
        # Tool(name="report_error", ...),
    ]

    logger.info("list_tools() 被调用，返回 %d 个工具", len(tools))
    return tools


# ─── 工具调用：call_tool ─────────────────────────────────────

@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """
    处理来自 Claude Code 的工具调用请求。

    Args:
        name: 工具名（与 list_tools 返回的 Tool.name 对应）
        arguments: 工具参数字典（由 Claude 根据 inputSchema 构造）

    Returns:
        TextContent 列表，内容为格式化的工具执行结果。
        注意：即使工具执行失败，也应返回结构化错误文本而非抛异常，
        这样 Claude 可以理解错误原因并给用户友好提示。
    """
    logger.info("call_tool(name=%s, args=%s)", name, arguments)

    try:
        if name == "serial_monitor":
            return await _handle_serial_monitor(arguments)

        else:
            return [TextContent(
                type="text",
                text=f"未知工具: {name}。当前可用工具: serial_monitor",
            )]

    except Exception as e:
        logger.error("call_tool(%s) 未预期异常: %s", name, e, exc_info=True)
        return [TextContent(
            type="text",
            text=json.dumps({
                "status": "error",
                "error_message": f"MCP Server 内部错误: {str(e)}",
            }, ensure_ascii=False, indent=2),
        )]


async def _handle_serial_monitor(arguments: dict) -> list[TextContent]:
    """
    处理 serial_monitor 工具调用（V2：查询后台缓存）。

    从 arguments 中提取 duration_sec 参数，调用 tools/serial_monitor.py
    的 monitor() 函数从后台缓冲区查询历史数据。

    V2 变更：monitor() 现在是纯查询操作，不再需要 asyncio.to_thread
    （不涉及 sleep 等待）。但保留 to_thread 以兼容内部可能存在的
    I/O 操作。
    """
    from tools.serial_monitor import monitor
    from serial_connection import SerialConnection

    duration_sec = float(arguments.get("duration_sec", 10.0))
    duration_sec = max(1.0, min(300.0, duration_sec))

    logger.info("查询串口缓存: 最近 %.1f 秒", duration_sec)

    result = await asyncio.to_thread(monitor, duration_sec=duration_sec)

    # 格式化为文本返回
    output_parts = [
        f"=== ESP32 串口缓存查询结果 ===",
        f"状态: {result['status']}",
        f"命中行数: {result['line_count']}",
        f"累计断连: {result['disconnects']} 次",
        f"查询窗口: {result['duration_sec']} 秒",
    ]

    if result.get('error_message'):
        output_parts.append(f"错误信息: {result['error_message']}")

    if result['lines']:
        output_parts.append(f"\n--- 最近 {result['duration_sec']} 秒内的输出 "
                           f"({result['line_count']} 行) ---")
        for i, line in enumerate(result['lines'], 1):
            output_parts.append(f"  {i:4d}: {line}")
    else:
        output_parts.append(f"\n(最近 {result['duration_sec']} 秒内无输出)")

    output_parts.append(f"\n--- 系统状态 ---")
    conn = SerialConnection()
    port_info = conn.get_port_info()
    output_parts.append(f"串口状态: {'已连接' if port_info['is_connected'] else '未连接'}")
    output_parts.append(f"后台采集: {'运行中' if port_info['collection_active'] else '已停止'}")
    output_parts.append(f"缓冲区: {port_info['buffer_size']} 行")

    formatted_text = "\n".join(output_parts)
    return [TextContent(type="text", text=formatted_text)]


# ─── 启动入口 ────────────────────────────────────────────────

async def main():
    """
    启动 MCP Server 并开始监听 stdio 上的 JSON-RPC 请求。

    V2 启动流程：
      1. 建立串口连接（COM3, 115200）  ← 新增
      2. 启动后台采集线程              ← 新增
      3. 开始监听 MCP 请求
    """
    logger.info("MCP Server 启动中...")
    logger.info("通信方式: stdio (stdin/stdout)")

    # V2: 预先建立串口连接并启动后台采集
    _init_serial_collection()

    async with stdio_server() as (read_stream, write_stream):
        logger.info("MCP Server 就绪，等待 Claude Code 连接...")
        await app.run(
            read_stream,
            write_stream,
            app.create_initialization_options(),
        )


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("MCP Server 已停止（KeyboardInterrupt）")
    except Exception as e:
        logger.error("MCP Server 异常退出: %s", e, exc_info=True)
        sys.exit(1)

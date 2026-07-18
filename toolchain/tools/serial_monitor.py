"""
serial_monitor.py — 串口监控工具（V2：后台缓存查询模式）
==========================================================

V2 语义变更（重要）：
  旧版 monitor(duration_sec=10) 的行为是"实时等待 10 秒，
  同时捕获期间的所有串口输出"。

  新版 monitor(duration_sec=10) 的行为是"查询最近 10 秒内
  已被后台采集线程缓存的串口输出"，调用立即返回（毫秒级），
  不再阻塞等待。

  这意味着：
    - AI 可以随时调用 monitor() 查看"之前发生了什么"，
      不需要提前掐时机"接下来帮我监控 10 秒"
    - 多次调用 monitor(5) 和 monitor(30) 查询的是同一份
      后台缓存的不同时间窗口，不会打架
    - 后台采集线程由 SerialConnection.start_background_collection()
      控制，通常在 MCP Server 启动时一次性开启

设计背景：
  后台采集线程（SerialConnection._background_reader_loop）
  从 MCP Server 启动起就不间断运行，所有串口输出被实时追加到
  deque 缓冲区（带时间戳）。工具调用时直接从缓冲区查询，
  零等待、不丢数据。
"""

import sys
import os
import time
import logging

logger = logging.getLogger(__name__)


def monitor(duration_sec: float = 10.0) -> dict:
    """
    查询最近 duration_sec 秒内后台缓存的串口输出。

    V2 语义：此函数不会实时等待或监听串口。它只是从
    SerialConnection 后台采集线程已缓存的数据中，
    取出最近 duration_sec 秒窗口内的行。调用立即返回。

    实现流程：
      1. 获取 SerialConnection 单例
      2. 确保已连接（如未连接则尝试连接并启动后台采集）
      3. 调用 get_recent_lines(since_sec=duration_sec) 查询缓存
      4. 组装并返回结构化结果

    Args:
        duration_sec: 查询时间窗口（秒）。monitor(10) 返回最近 10
                      秒内后台缓存的数据。默认 10 秒，范围 1~300。

    Returns:
        dict:
            {
                "status": "ok" | "partial" | "error",
                "lines": ["line1", "line2", ...],
                "line_count": int,
                "disconnects": int,       # 后台采集启动以来的累计断连次数
                "duration_sec": float,     # 查询的时间窗口（即参数值）
                "error_message": str | None
            }
    """
    from serial_connection import SerialConnection

    result = {
        'status': 'ok',
        'lines': [],
        'line_count': 0,
        'disconnects': 0,
        'duration_sec': duration_sec,
        'error_message': None,
    }

    conn = SerialConnection()

    # 确保已连接
    if not conn.is_connected():
        logger.info("串口未连接，尝试连接...")
        if not conn.connect():
            result['status'] = 'error'
            result['error_message'] = (
                '无法连接串口 COM3。'
                '请检查：1) ESP32是否已连接 2) 是否被其他程序占用（Thonny/mpremote等）'
            )
            if conn.last_error:
                result['error_message'] += f' 底层错误: {conn.last_error["message"]}'
            return result

    # 确保后台采集已启动（通常由 MCP Server 启动时完成，
    # 这里做一次兜底检查，兼容独立测试场景）
    if not conn.collection_active:
        logger.info("后台采集未运行，自动启动...")
        if not conn.start_background_collection():
            result['status'] = 'error'
            result['error_message'] = '后台采集启动失败：无法连接串口'
            return result
        # 刚启动时缓冲区为空，如果调用方立即查询可能得到空结果
        # 这是预期行为——提示调用方稍后重试
        logger.info("后台采集刚启动，缓冲区可能为空，建议稍后重试")

    # 查询后台缓存
    entries = conn.get_recent_lines(since_sec=duration_sec)

    # 提取纯文本行（保留时间戳可用于未来扩展）
    lines = [entry['line'] for entry in entries]
    disconnects = conn.get_disconnect_count()

    result['lines'] = lines
    result['line_count'] = len(lines)
    result['disconnects'] = disconnects

    if disconnects > 0:
        result['status'] = 'partial'
        logger.info("后台采集累计发生 %d 次断连", disconnects)

    if not conn.is_connected() and not lines:
        result['status'] = 'error'
        result['error_message'] = '串口已断开且缓冲区无数据'

    logger.info("串口监控查询完成: 窗口 %.1f 秒, 命中 %d 行, 累计断连 %d 次",
                duration_sec, result['line_count'], disconnects)

    return result


def get_buffer_stats() -> dict:
    """
    获取后台缓冲区的统计信息（不查询具体内容）。

    用于快速确认"系统是否在正常采集数据"，不需要传输大量日志行。

    Returns:
        dict: 包含 buffer_size, collection_active, disconnect_count 等
    """
    from serial_connection import SerialConnection
    conn = SerialConnection()
    return conn.get_port_info()


# ─── 独立测试入口 ───────────────────────────────────────────

if __name__ == '__main__':
    """
    V2 独立测试：验证"后台采集 + 按需查询"模式。

    测试流程：
      1. 建立串口连接并启动后台采集
      2. 提示用户去按 ESP32 上的按键（产生 print 输出）
      3. 用户按回车后，查询最近 N 秒的缓存数据
      4. 验证：用户按键期间没有调用 monitor()，但数据已被捕获

    运行方式：
      cd toolchain
      python -m tools.serial_monitor [查询窗口秒数]

    前提条件：
      1. ESP32 已连接 COM3，固件正在运行
      2. 关闭 Thonny/mpremote 等占用 COM3 的程序
    """
    import threading

    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    logging.basicConfig(
        level=logging.INFO,
        format='[%(levelname)s] %(name)s: %(message)s',
    )

    from serial_connection import SerialConnection, list_available_ports

    print("=" * 60)
    print("  ESP32 串口监控 V2 - 后台采集 + 按需查询测试")
    print("=" * 60)
    print()

    # 列出可用端口
    ports = list_available_ports()
    print("可用串口:")
    for p in ports:
        print(f"  {p['device']} - {p['description']}")
    if not ports:
        print("  (未检测到任何串口)")
    print()

    # 建立连接并启动后台采集
    conn = SerialConnection()
    print("正在连接 COM3 并启动后台采集...")
    if not conn.connect():
        print("错误: 无法连接 COM3")
        sys.exit(1)
    if not conn.start_background_collection():
        print("错误: 后台采集启动失败")
        sys.exit(1)

    print("✅ 后台采集已启动！")
    print()
    print("后台采集线程正在持续读取串口数据到缓冲区...")
    print("你现在可以去按 ESP32 上的按键，数据会被自动捕获。")
    print()

    # 等待用户按琴键
    query_sec = float(sys.argv[1]) if len(sys.argv) > 1 else 15.0
    input(f"按回车查询最近 {query_sec} 秒的缓存数据（先弹几个音符再按回车）...")

    # 查询
    print(f"\n正在查询最近 {query_sec} 秒的缓存...")
    result = monitor(duration_sec=query_sec)

    # 打印结果
    print(f"\n{'=' * 60}")
    print(f"  查询结果")
    print(f"{'=' * 60}")
    print(f"状态:       {result['status']}")
    print(f"命中行数:   {result['line_count']}")
    print(f"累计断连:   {result['disconnects']}")
    print(f"查询窗口:   {result['duration_sec']} 秒")
    if result['error_message']:
        print(f"错误信息:   {result['error_message']}")

    # 额外：打印缓冲区统计
    stats = get_buffer_stats()
    print(f"\n后台缓冲区状态:")
    print(f"  缓冲区行数: {stats['buffer_size']}")
    print(f"  采集运行中: {stats['collection_active']}")
    print(f"  串口已连接: {stats['is_connected']}")

    print(f"\n捕获内容:")
    if result['lines']:
        for i, line in enumerate(result['lines'], 1):
            print(f"  {i:3d}: {line}")
    else:
        print("  (查询窗口内无数据 — 如果刚才弹了按键，可能是窗口太长或缓冲区还未填充)")

    # 额外：查询最近 5 行（不管时间窗口），验证 n 参数
    print(f"\n--- 额外验证：最近 5 行（不限时间窗口）---")
    recent = conn.get_recent_lines(n=5)
    if recent:
        for entry in recent:
            ts = time.strftime('%H:%M:%S', time.localtime(entry['timestamp']))
            print(f"  [{ts}] {entry['line']}")
    else:
        print("  (缓冲区为空)")

    # 清理
    conn.stop_background_collection()
    conn.disconnect()
    print("\n测试完成。")

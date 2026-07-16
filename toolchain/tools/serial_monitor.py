"""
serial_monitor.py — 串口监控工具
=================================

在指定时长内持续监听 ESP32 串口输出，返回结构化结果。

设计决策：为什么使用独立线程而不是同步阻塞读取？

  MCP 工具调用是一次性请求-响应模式：
    1. Claude 发来 tool_call 请求（含 duration_sec 参数）
    2. MCP Server 调用 monitor() 函数
    3. monitor() 必须在合理时间内返回结果

  如果 monitor() 内部只是一个 sleep(duration_sec) 循环 + 定时读取，
  在以下场景会出现问题：
    a) 监控时长设为 30 秒 → MCP 调用方等待 30 秒才收到响应
       → 如果中间有其他操作（如文件传输），必须等这个调用完成
    b) 串口读取是 I/O 操作，可能因为 USB 延迟等因素导致单次
       readline() 耗时不确定，累积延迟导致实际捕获的数据窗口
       小于 duration_sec

  使用独立线程的方案：
    1. 启动后台线程持续读取串口并缓存到线程安全的 deque
    2. 主线程等待 duration_sec 后停止后台线程
    3. 返回缓存中的所有数据

  好处：
    - 后台线程在 duration_sec 全程持续读取，不会因主线程等待
      而漏掉数据
    - 即使串口有偶发延迟，后台线程也能在数据到达时立即读取
    - 调用方收到的是 duration_sec 完整窗口内的所有数据，而非
      间断采样的部分数据
    - 未来可以扩展为"持续监控模式"（后台线程常驻，随时取最近
      N 秒缓存）而不改变架构

线程安全：
    _buffer 使用 threading.Lock 保护，后台线程写入时加锁，
    主线程取数据时也加锁。临界区极小（仅 list.append/extend）。
"""

import threading
import time
import logging

logger = logging.getLogger(__name__)


def monitor(duration_sec: float = 10.0) -> dict:
    """
    在指定时长内监听串口输出，返回结构化的监控结果。

    实现流程：
      1. 获取 SerialConnection 单例并确保已连接
      2. 启动后台线程持续读取串口到缓冲区
      3. 主线程等待 duration_sec 秒
      4. 停止后台线程，收集缓冲区数据
      5. 返回结构化结果

    Args:
        duration_sec: 监控时长（秒），范围建议 1~60，默认 10

    Returns:
        dict:
            {
                "status": "ok" | "partial" | "error",
                "lines": ["line1", "line2", ...],
                "line_count": int,
                "disconnects": int,      # 监控期间断连次数
                "duration_sec": float,    # 实际监控耗时
                "error_message": str | None  # 仅在 status="error" 时存在
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

    # 确保串口已连接
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

    # 共享状态
    lock = threading.Lock()
    buffer: list[str] = []        # 缓存捕获的行
    disconnects_counter = [0]     # 使用列表以便在闭包中修改
    stop_flag = threading.Event() # 停止信号

    def _reader_loop():
        """
        后台线程：持续读取串口数据直到 stop_flag 被设置。

        每次迭代：
          1. 调用 read_available_lines() 非阻塞读取
          2. 将新行追加到 buffer
          3. 检测断连并尝试恢复
          4. 短暂休眠避免 CPU 空转
        """
        while not stop_flag.is_set():
            try:
                if not conn.is_connected():
                    # 检测到断连，尝试重连
                    disconnects_counter[0] += 1
                    logger.warning("后台线程检测到断连（第 %d 次），尝试重连...",
                                   disconnects_counter[0])
                    if conn.try_reconnect():
                        logger.info("后台线程重连成功")
                        continue
                    else:
                        logger.error("后台线程重连失败，等待下次尝试")
                        time.sleep(1.0)
                        continue

                # 非阻塞读取当前缓冲区中的数据行
                new_lines = conn.read_available_lines()
                if new_lines:
                    with lock:
                        buffer.extend(new_lines)

                # 短暂休眠，避免 CPU 100% 占用
                # 100ms 间隔配合 115200 波特率，
                # 在固件持续 print 的场景下不会丢数据
                time.sleep(0.1)

            except Exception as e:
                logger.error("后台线程未预期异常: %s", e, exc_info=True)
                disconnects_counter[0] += 1
                time.sleep(0.5)

    # 启动后台读取线程
    reader_thread = threading.Thread(
        target=_reader_loop,
        name='serial-monitor-reader',
        daemon=True,  # daemon=True 确保主线程退出时自动终止
    )

    start_time = time.monotonic()
    reader_thread.start()

    # 主线程等待指定时长
    time.sleep(duration_sec)

    # 发出停止信号并等待后台线程结束
    stop_flag.set()
    reader_thread.join(timeout=2.0)  # 最多等 2 秒，避免卡死

    elapsed = time.monotonic() - start_time

    # 收集最后残留的数据（stop_flag 到 join 之间可能还有新数据）
    final_lines = conn.read_available_lines()
    if final_lines:
        with lock:
            buffer.extend(final_lines)

    # 填充结果
    result['lines'] = list(buffer)
    result['line_count'] = len(buffer)
    result['disconnects'] = disconnects_counter[0]
    result['duration_sec'] = round(elapsed, 2)

    if disconnects_counter[0] > 0:
        result['status'] = 'partial'
        logger.warning("监控期间发生 %d 次断连", disconnects_counter[0])

    if not conn.is_connected() and not buffer:
        result['status'] = 'error'
        result['error_message'] = '监控期间连接完全丢失，且未捕获到任何数据'

    logger.info("串口监控完成: 捕获 %d 行, 断连 %d 次, 耗时 %.2f 秒",
                result['line_count'], result['disconnects'], elapsed)

    return result


# ─── 独立测试入口 ───────────────────────────────────────────

if __name__ == '__main__':
    """
    不通过 MCP Server，直接用 Python 运行以验证串口监控功能。

    前提条件：
      1. ESP32 已通过 USB 连接到 COM3
      2. 固件正在运行（有持续的 print 输出）
      3. 关闭 Thonny/mpremote 等占用 COM3 的程序

    运行方式：
      cd toolchain
      python -m tools.serial_monitor
    """
    import sys
    import os

    # 将 toolchain 目录加入 sys.path，确保能导入 serial_connection
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    # 配置日志输出到 stdout（独立测试时更直观）
    logging.basicConfig(
        level=logging.INFO,
        format='[%(levelname)s] %(name)s: %(message)s',
    )

    print("=" * 60)
    print("  ESP32 串口监控 - 独立测试")
    print("=" * 60)
    print()

    # 先列出可用端口
    from serial_connection import list_available_ports
    ports = list_available_ports()
    print("可用串口:")
    for p in ports:
        print(f"  {p['device']} - {p['description']}")
    if not ports:
        print("  (未检测到任何串口)")
    print()

    # 执行监控
    duration = float(sys.argv[1]) if len(sys.argv) > 1 else 5.0
    print(f"开始监控 {duration} 秒...\n")

    result = monitor(duration_sec=duration)

    print(f"\n--- 监控结果 ---")
    print(f"状态: {result['status']}")
    print(f"捕获行数: {result['line_count']}")
    print(f"断连次数: {result['disconnects']}")
    print(f"实际耗时: {result['duration_sec']} 秒")
    if result['error_message']:
        print(f"错误信息: {result['error_message']}")
    print(f"\n捕获内容:")
    for i, line in enumerate(result['lines'], 1):
        print(f"  {i:3d}: {line}")
    if not result['lines']:
        print("  (无数据)")

"""
serial_connection.py — 串口连接管理单例
========================================

所有工具模块共享同一个串口连接对象，避免多个工具各自创建
serial.Serial 实例导致 COM3 端口抢占冲突。

V2 新增：后台持续采集线程
  连接建立后自动启动后台线程，持续读取串口数据并缓存到
  带时间戳的 deque 中。工具无需主动监控即可查询"最近发生了什么"。

使用方式：
    from serial_connection import SerialConnection
    conn = SerialConnection()
    conn.connect(port='COM3', baudrate=115200)
    conn.start_background_collection()  # V2: 启动后台采集
    entries = conn.get_recent_lines(since_sec=10)
    conn.disconnect()

线程安全说明：
    所有读取操作通过 _read_lock 保护，缓冲区通过 _buffer_lock 保护。
    pyserial 的 readline() 本身不是线程安全的，外部不应直接访问 _serial 对象。
"""

import serial
import serial.tools.list_ports
import threading
import time
import logging
from collections import deque

logger = logging.getLogger(__name__)

# ─── 缓冲区容量说明 ─────────────────────────────────────────
# maxlen=1000：以 ESP32 115200bps 串口、钢琴固件正常输出速率（约每秒
# 1-3 行 print）估算，1000 行可覆盖约 5-15 分钟的日志。对于调试会话
# 来说足够回溯最近的操作历史，同时内存占用可控（每条约 100 字节，
# 含时间戳约 150 字节，总计约 150KB）。
_BUFFER_MAXLEN = 1000


class SerialConnection:
    """
    单例串口连接管理器。

    V2 特性：
      - 单例模式：所有调用方获取同一个实例
      - 后台持续采集：连接建立后启动 daemon 线程不间断读取串口
      - 带时间戳缓存：deque 保留最近 1000 行数据，供随时查询
      - 自动重连：后台线程检测到断连后自动尝试恢复（3次/1秒间隔）
      - 断连计数：记录启动以来的断连总次数
      - 错误记录：最近一次错误的类型和消息可通过 last_error 查询
    """

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        """单例构造：确保全局只有一个 SerialConnection 实例。"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._serial: serial.Serial | None = None
        self._port: str = 'COM3'
        self._baudrate: int = 115200
        self._timeout: float = 0.1  # 读取超时（秒），短超时 = 不阻塞

        # 后台采集相关
        self._buffer: deque = deque(maxlen=_BUFFER_MAXLEN)
        self._buffer_lock = threading.Lock()
        self._reader_thread: threading.Thread | None = None
        self._reader_stop = threading.Event()
        self._disconnect_count: int = 0  # 启动以来累计断连次数
        self._collection_active: bool = False

        # 线程安全
        self._read_lock = threading.Lock()    # 保护底层串口读取
        self._last_error: dict | None = None  # {"type": str, "message": str, "timestamp": float}

        self._initialized = True
        logger.info("SerialConnection 单例已初始化（V2: 后台持续采集模式）")

    # ─── 公开 API：连接管理 ─────────────────────────────────

    def connect(self, port: str = 'COM3', baudrate: int = 115200) -> bool:
        """
        建立串口连接。如果已有连接且匹配参数则复用，否则重建。

        注意：connect() 只建立物理连接，不会自动启动后台采集。
        需要调用 start_background_collection() 或由 MCP Server
        在启动时统一触发。

        Args:
            port: 串口号，默认 COM3
            baudrate: 波特率，默认 115200

        Returns:
            True 表示连接成功，False 表示连接失败
        """
        # 如果参数相同且已连接，直接复用
        if self._serial is not None and self._serial.is_open:
            if self._port == port and self._baudrate == baudrate:
                logger.debug("复用已有串口连接: %s@%d", port, baudrate)
                return True
            else:
                logger.info("端口参数变更，断开旧连接: %s → %s", self._port, port)
                self.disconnect()

        self._port = port
        self._baudrate = baudrate

        try:
            self._serial = serial.Serial(
                port=port,
                baudrate=baudrate,
                timeout=self._timeout,
            )
            self._serial.reset_input_buffer()
            logger.info("串口连接成功: %s@%d", port, baudrate)
            return True
        except serial.SerialException as e:
            self._record_error('SerialException', str(e))
            logger.error("无法打开串口 %s: %s", port, e)
            self._serial = None
            return False
        except PermissionError as e:
            self._record_error('PermissionError', str(e))
            logger.error("串口 %s 权限不足或已被占用: %s", port, e)
            self._serial = None
            return False

    def disconnect(self) -> None:
        """关闭串口连接并释放资源。会先停止后台采集线程。"""
        self.stop_background_collection()

        if self._serial is not None:
            try:
                if self._serial.is_open:
                    self._serial.close()
                    logger.info("串口连接已关闭: %s", self._port)
            except serial.SerialException as e:
                logger.warning("关闭串口时出现异常（忽略）: %s", e)
            finally:
                self._serial = None

    def is_connected(self) -> bool:
        """返回当前物理串口是否处于连接状态。"""
        return self._serial is not None and self._serial.is_open

    # ─── 公开 API：后台采集控制 ─────────────────────────────

    def start_background_collection(self) -> bool:
        """
        启动后台采集线程，开始持续读取串口数据到缓存。

        如果已启动则直接返回 True（幂等）。
        如果未连接则先尝试连接。

        Returns:
            True 表示采集线程已启动，False 表示启动失败（无法连接）
        """
        if self._collection_active and self._reader_thread is not None and self._reader_thread.is_alive():
            logger.debug("后台采集已在运行中，跳过启动")
            return True

        if not self.is_connected():
            logger.info("后台采集启动前先建立串口连接...")
            if not self.connect():
                logger.error("后台采集启动失败：无法连接串口")
                return False

        self._reader_stop.clear()
        self._disconnect_count = 0
        self._reader_thread = threading.Thread(
            target=self._background_reader_loop,
            name='serial-bg-collector',
            daemon=True,
        )
        self._reader_thread.start()
        self._collection_active = True
        logger.info("后台串口采集已启动（缓冲区容量: %d 行）", _BUFFER_MAXLEN)
        return True

    def stop_background_collection(self) -> None:
        """停止后台采集线程。幂等操作。"""
        if not self._collection_active:
            return

        logger.info("正在停止后台串口采集...")
        self._reader_stop.set()
        if self._reader_thread is not None and self._reader_thread.is_alive():
            self._reader_thread.join(timeout=2.0)
        self._collection_active = False
        self._reader_thread = None
        logger.info("后台串口采集已停止")

    @property
    def collection_active(self) -> bool:
        """后台采集线程是否正在运行。"""
        return self._collection_active

    # ─── 公开 API：数据查询 ─────────────────────────────────

    def get_recent_lines(self, n: int | None = None,
                         since_sec: float | None = None) -> list[dict]:
        """
        从后台缓冲区中查询最近的数据行。

        过滤逻辑：
          - n 和 since_sec 可以各自单独使用，也可以同时使用。
          - 同时使用时取交集：先按时间过滤，再取最近 n 条。
          - 都不提供时返回缓冲区全部数据（最多 _BUFFER_MAXLEN 条）。
          - 结果按时间升序排列（最早在前，最新在后）。

        Args:
            n: 返回最近 n 条记录。n=1 返回最新 1 条，n=None 不限制数量。
            since_sec: 只返回最近 since_sec 秒内的记录。
                       since_sec=10 返回最近 10 秒内的数据。

        Returns:
            列表，每项为 {"timestamp": float, "line": str}。
            时间戳为数据被采集线程捕获时的 time.time() 值。

        示例：
            # 最近 50 行
            conn.get_recent_lines(n=50)

            # 最近 30 秒内的所有行
            conn.get_recent_lines(since_sec=30)

            # 最近 30 秒内的最新 50 行
            conn.get_recent_lines(n=50, since_sec=30)
        """
        with self._buffer_lock:
            entries = list(self._buffer)

        # 先按时间过滤（如果指定）
        if since_sec is not None:
            cutoff = time.time() - since_sec
            entries = [e for e in entries if e['timestamp'] >= cutoff]

        # 再按数量截取（取最近 n 条，即列表尾部）
        if n is not None and n > 0:
            entries = entries[-n:]

        return entries

    def get_disconnect_count(self) -> int:
        """返回后台采集启动以来的累计断连次数。"""
        return self._disconnect_count

    # ─── 公开 API：直接读取（供不需要缓存场景使用）─────────────

    def read_available_lines(self) -> list[str]:
        """
        非阻塞直接读取串口缓冲区中当前可用的所有行。

        优先使用 get_recent_lines() 从缓存查询。
        此方法仅在需要绕过缓冲、直接访问串口时使用（如固件写入后的
        即时响应确认）。

        V2 变更：此方法不再触发自动重连。异常时记录错误并返回空列表，
        重连逻辑由后台采集线程独立处理。

        Returns:
            已解码的文本行列表（不含换行符）。如果连接断开或读取异常，
            返回空列表并记录错误。
        """
        with self._read_lock:
            if not self.is_connected():
                return []

            lines: list[str] = []
            try:
                while self._serial.in_waiting > 0:
                    raw = self._serial.readline()
                    try:
                        decoded = raw.decode('utf-8', errors='replace').rstrip('\r\n')
                        if decoded:
                            lines.append(decoded)
                    except UnicodeDecodeError:
                        continue
            except serial.SerialException as e:
                self._record_error('SerialException', str(e))
                logger.warning("串口读取异常: %s", e)
                # V2: 标记连接可能已丢失，但不在此处重连
                # 重连由后台采集线程的 _background_reader_loop 处理
                self._mark_disconnected()
            except PermissionError as e:
                self._record_error('PermissionError', str(e))
                logger.warning("串口读取权限异常: %s", e)
                self._mark_disconnected()

            return lines

    def try_reconnect(self) -> bool:
        """
        主动尝试重新连接（供后台采集线程或外部调用）。

        与 connect() 不同：此方法会先关闭旧句柄，再重试建立连接。
        最多重试 3 次，间隔 1 秒。

        Returns:
            True 表示重连成功
        """
        if self.is_connected():
            return True

        # 先清理可能残留的句柄
        if self._serial is not None:
            try:
                self._serial.close()
            except Exception:
                pass
            self._serial = None

        for attempt in range(1, 4):
            time.sleep(1.0)
            if self.connect(self._port, self._baudrate):
                logger.info("重连成功（第 %d 次尝试）", attempt)
                return True
            logger.warning("重连失败（第 %d/3 次尝试）", attempt)

        logger.error("重连失败：已用完所有重试次数")
        return False

    @property
    def last_error(self) -> dict | None:
        """
        最近一次串口错误的详细信息。

        Returns:
            dict: {"type": "...", "message": "...", "timestamp": 1234567890.0}
            或 None（从未发生过错误）
        """
        return self._last_error

    def get_port_info(self) -> dict:
        """
        获取当前端口状态信息（用于调试和工具返回）。

        Returns:
            dict: 包含 port, baudrate, is_connected, collection_active,
                  disconnect_count, buffer_size, last_error 等字段
        """
        with self._buffer_lock:
            buffer_size = len(self._buffer)
        return {
            'port': self._port,
            'baudrate': self._baudrate,
            'is_connected': self.is_connected(),
            'collection_active': self._collection_active,
            'disconnect_count': self._disconnect_count,
            'buffer_size': buffer_size,
            'last_error': self._last_error,
        }

    # ─── 内部方法 ───────────────────────────────────────────

    def _record_error(self, error_type: str, message: str) -> None:
        """记录最近一次错误信息。"""
        self._last_error = {
            'type': error_type,
            'message': message,
            'timestamp': time.time(),
        }

    def _mark_disconnected(self) -> None:
        """
        标记物理连接已丢失（关闭句柄但不重连）。

        重连由后台采集线程的 _background_reader_loop 负责，
        这样可以保持重连逻辑集中在一处。
        """
        try:
            if self._serial is not None:
                self._serial.close()
        except Exception:
            pass
        self._serial = None

    def _background_reader_loop(self) -> None:
        """
        后台采集线程主循环。

        生命周期：从 start_background_collection() 启动，
        到 stop_background_collection()（设置 _reader_stop）结束。

        每次迭代：
          1. 检查停止信号
          2. 检查串口连接状态，断连则尝试重连（使用 try_reconnect）
          3. 非阻塞读取串口数据
          4. 将新行带时间戳追加到 _buffer
          5. 短暂休眠（100ms），避免 CPU 100% 占用

        异常处理：
          - 单次读取异常不会导致线程退出
          - 重连失败后会继续尝试（每次循环检查）
          - 未预期的异常记录日志后等待 0.5 秒继续

        100ms 休眠间隔说明：
          115200bps 下每字节约 87μs，一条 80 字符的 print 行约 7ms。
          100ms 间隔意味着在最坏情况下可能错过约 14 行（如果它们在
          100ms 窗口内全部到达）。但实际上 ESP32 的 print 输出有
          自然的间隔（固件主循环 sleep 10ms + 人工按键间隔），
          100ms 足够捕获所有正常输出。降低间隔会增加 CPU 占用，
          当前取值在"不丢数据"和"省 CPU"之间取的平衡点。
        """
        logger.info("后台采集线程已启动")
        while not self._reader_stop.is_set():
            try:
                # ── 检查连接状态 ──
                if not self.is_connected():
                    self._disconnect_count += 1
                    logger.warning("后台线程检测到断连（累计第 %d 次），尝试重连...",
                                   self._disconnect_count)
                    if self.try_reconnect():
                        logger.info("后台线程重连成功，继续采集")
                        continue
                    else:
                        # 重连失败，等待后继续尝试
                        logger.warning("后台线程重连失败，1秒后重试")
                        time.sleep(1.0)
                        continue

                # ── 读取并缓存 ──
                new_lines = self.read_available_lines()
                if new_lines:
                    now = time.time()
                    with self._buffer_lock:
                        for line in new_lines:
                            self._buffer.append({
                                'timestamp': now,
                                'line': line,
                            })

                time.sleep(0.1)

            except Exception:
                logger.error("后台线程未预期异常", exc_info=True)
                time.sleep(0.5)

        logger.info("后台采集线程已退出（累计断连 %d 次）", self._disconnect_count)


# ─── 便捷函数 ───────────────────────────────────────────────

def list_available_ports() -> list[dict]:
    """
    列出系统上所有可用的串口。

    Returns:
        列表，每项包含 device, description, hardware_id
    """
    ports = serial.tools.list_ports.comports()
    return [
        {
            'device': p.device,
            'description': p.description,
            'hardware_id': p.hwid,
        }
        for p in ports
    ]

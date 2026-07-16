"""
serial_connection.py — 串口连接管理单例
========================================

所有工具模块共享同一个串口连接对象，避免多个工具各自创建
serial.Serial 实例导致 COM3 端口抢占冲突。

使用方式：
    from serial_connection import SerialConnection
    conn = SerialConnection()
    conn.connect(port='COM3', baudrate=115200)
    lines = conn.read_available_lines()
    conn.disconnect()

线程安全说明：
    read_available_lines() 持有实例级锁，允许多线程并发安全读取。
    pyserial 的 readline() 本身不是线程安全的，所有读取操作都通过
    本类的方法进行，外部不应直接访问 _serial 对象。
"""

import serial
import serial.tools.list_ports
import threading
import time
import logging

logger = logging.getLogger(__name__)


class SerialConnection:
    """
    单例串口连接管理器。

    特性：
      - 单例模式：所有调用方获取同一个实例
      - 自动重连：检测到断连后最多重试 3 次（间隔 1 秒）
      - 错误记录：最近一次错误的类型和消息可通过 last_error 查询
      - 非阻塞读取：read_available_lines() 只返回当前缓冲区已有数据
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
        self._read_lock = threading.Lock()
        self._last_error: dict | None = None  # {"type": str, "message": str, "timestamp": float}
        self._initialized = True
        logger.info("SerialConnection 单例已初始化")

    # ─── 公开 API ───────────────────────────────────────────

    def connect(self, port: str = 'COM3', baudrate: int = 115200) -> bool:
        """
        建立串口连接。如果已有连接且匹配参数则复用，否则重建。

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
                # 参数不同，先断开旧连接
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
            # 清空可能残留的缓冲区数据
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
        """关闭串口连接并释放资源。"""
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
        """返回当前是否处于连接状态。"""
        return self._serial is not None and self._serial.is_open

    def read_available_lines(self) -> list[str]:
        """
        非阻塞读取串口缓冲区中当前可用的所有行。

        实现逻辑：
          1. 检查连接状态，未连接则返回空列表
          2. 使用 in_waiting 判断是否有待读数据
          3. 逐行读取直到缓冲区耗尽或遇到超时

        Returns:
            已解码的文本行列表（不含换行符）。如果连接断开或读取异常，
            返回空列表并记录错误。

        注意：
            此方法是线程安全的（通过 _read_lock 保护），
            但调用方不应假设读取是实时的——串口数据到达有延迟。
        """
        with self._read_lock:
            if not self.is_connected():
                return []

            lines: list[str] = []
            try:
                while self._serial.in_waiting > 0:
                    line = self._serial.readline()
                    try:
                        decoded = line.decode('utf-8', errors='replace').rstrip('\r\n')
                        if decoded:
                            lines.append(decoded)
                    except UnicodeDecodeError:
                        # 非文本数据，跳过
                        continue
            except serial.SerialException as e:
                self._record_error('SerialException', str(e))
                logger.warning("串口读取异常: %s", e)
                # 标记连接可能丢失
                self._handle_disconnect_detected()
            except PermissionError as e:
                self._record_error('PermissionError', str(e))
                logger.warning("串口读取权限异常: %s", e)
                self._handle_disconnect_detected()

            return lines

    @property
    def last_error(self) -> dict | None:
        """
        最近一次串口错误的详细信息。

        Returns:
            dict: {"type": "SerialException", "message": "...", "timestamp": 1234567890.0}
            或 None（从未发生过错误）
        """
        return self._last_error

    # ─── 内部方法 ───────────────────────────────────────────

    def _record_error(self, error_type: str, message: str) -> None:
        """记录最近一次错误信息。"""
        self._last_error = {
            'type': error_type,
            'message': message,
            'timestamp': time.time(),
        }

    def _handle_disconnect_detected(self) -> None:
        """
        检测到串口断连后的处理逻辑：
          1. 标记连接关闭
          2. 尝试自动重连（最多 3 次，间隔 1 秒）
          3. 重连失败则标记错误状态
        """
        # 关闭可能残留的句柄
        try:
            if self._serial is not None:
                self._serial.close()
        except Exception:
            pass
        self._serial = None

        # 自动重连
        logger.info("尝试重新连接串口...")
        for attempt in range(1, 4):
            time.sleep(1.0)
            if self.connect(self._port, self._baudrate):
                logger.info("重连成功（第 %d 次尝试）", attempt)
                return
            logger.warning("重连失败（第 %d/3 次尝试）", attempt)

        logger.error("重连失败：已用完所有重试次数")

    def try_reconnect(self) -> bool:
        """
        主动尝试重新连接（供外部调用）。

        与 _handle_disconnect_detected 不同，此方法不会自动关闭已有连接，
        适用于调用方主动检测到断连后请求恢复的场景。

        Returns:
            True 表示重连成功
        """
        if self.is_connected():
            return True

        for attempt in range(1, 4):
            time.sleep(1.0)
            if self.connect(self._port, self._baudrate):
                logger.info("主动重连成功（第 %d 次尝试）", attempt)
                return True

        return False

    def get_port_info(self) -> dict:
        """
        获取当前端口状态信息（用于调试和工具返回）。

        Returns:
            dict: 包含 port, baudrate, is_connected, last_error 等字段
        """
        info = {
            'port': self._port,
            'baudrate': self._baudrate,
            'is_connected': self.is_connected(),
            'last_error': self._last_error,
        }
        return info


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

"""
leds.py - 板载LED控制模块
==========================
封装LED2（绿）和LED3（红）的控制，对上层屏蔽"低电平点亮"的硬件细节。

GPIO映射（低电平点亮）：
  LED2（绿）→ GPIO32
  LED3（红）→ GPIO33

接口使用 'green' / 'red' 字符串标识LED，调用方无需关心电平极性。
"""

from machine import Pin
import time

# LED GPIO 映射
_LED_MAP = {
    'green': 32,  # LED2
    'red':   33,  # LED3
}

_pins = {}  # 颜色名 → Pin对象


def _init_pin(which):
    """
    惰性初始化指定LED的Pin对象。
    首次访问时创建，后续复用。

    Args:
        which (str): 'green' 或 'red'
    """
    if which not in _pins:
        gpio = _LED_MAP[which]
        _pins[which] = Pin(gpio, Pin.OUT, value=1)  # 初始高电平 = 熄灭


def led_on(which):
    """
    点亮指定LED。

    Args:
        which (str): 'green'（绿灯）或 'red'（红灯）

    Raises:
        ValueError: 传入未识别的LED标识
    """
    if which not in _LED_MAP:
        raise ValueError("未知LED: {}".format(which))
    _init_pin(which)
    _pins[which].value(0)  # 低电平点亮


def led_off(which):
    """
    熄灭指定LED。

    Args:
        which (str): 'green'（绿灯）或 'red'（红灯）

    Raises:
        ValueError: 传入未识别的LED标识
    """
    if which not in _LED_MAP:
        raise ValueError("未知LED: {}".format(which))
    _init_pin(which)
    _pins[which].value(1)  # 高电平熄灭


def flash(which, duration_ms=100):
    """
    短暂点亮LED（duration_ms 毫秒），然后自动熄灭。
    这是一个阻塞操作，适用于按键视觉反馈等短闪烁场景。

    Args:
        which (str): 'green'（绿灯）或 'red'（红灯）
        duration_ms (int): 点亮时长（毫秒），默认 100

    Raises:
        ValueError: 传入未识别的LED标识
    """
    if which not in _LED_MAP:
        raise ValueError("未知LED: {}".format(which))
    _init_pin(which)
    _pins[which].value(0)               # 点亮（低电平）
    time.sleep_ms(duration_ms)          # 保持
    _pins[which].value(1)               # 熄灭（高电平）

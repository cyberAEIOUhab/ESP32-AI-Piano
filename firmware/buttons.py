"""
buttons.py - 外接7按键模块
==========================
封装J4排针接入的7个钢琴按键（do/re/mi/fa/so/la/xi），
提供边沿检测：按下瞬间触发一次，长按不重复触发，
按键释放后才重置状态，允许再次触发。

GPIO映射（均使用内部上拉 PULL_UP，按下为低电平）：
  do  → GPIO5
  re  → GPIO12
  mi  → GPIO14
  fa  → GPIO18
  so  → GPIO19
  la  → GPIO21
  xi  → GPIO22
"""

from machine import Pin

# 音符名 → GPIO引脚号 映射表
_KEY_MAP = {
    'do':  5,
    're': 12,
    'mi': 14,
    'fa': 18,
    'so': 19,
    'la': 21,
    'xi': 22,
}

_pins = {}        # 音符名 → Pin对象
_states = {}      # 音符名 → 当前状态: 'idle'（待触发）| 'fired'（已触发，等待释放后重置）


def init():
    """
    初始化所有外接按键为输入模式（PULL_UP），
    并将每个按键的状态机设为 'idle'（待触发状态）。
    在 piano.py 启动时调用一次即可。
    """
    for name, gpio in _KEY_MAP.items():
        pin = Pin(gpio, Pin.IN, Pin.PULL_UP)
        _pins[name] = pin
        _states[name] = 'idle'


def get_pressed_key():
    """
    扫描所有按键，返回本次新按下的音符名。

    边沿检测逻辑（两态状态机）：
      - 'idle' 状态且检测到低电平（按下）→ 切换为 'fired'，返回音符名
      - 'fired' 状态且仍为低电平（长按）→ 不返回，防重复触发
      - 'fired' 状态且恢复高电平（释放）→ 切换回 'idle'，允许下次触发

    Returns:
        str | None: 新按下的音符名（'do'/'re'/'mi'/'fa'/'so'/'la'/'xi'），
                    无新按下时返回 None
    """
    for name, pin in _pins.items():
        pressed = (pin.value() == 0)  # PULL_UP: 低电平 = 按下

        if _states[name] == 'idle' and pressed:
            _states[name] = 'fired'
            return name

        if _states[name] == 'fired' and not pressed:
            _states[name] = 'idle'

    return None

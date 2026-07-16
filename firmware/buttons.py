"""
buttons.py - 外接7按键 + 八度切换按键模块
==========================================
封装J4排针接入的7个钢琴按键（do/re/mi/fa/so/la/xi），
以及板载KEY1/KEY2用于八度切换。
提供统一的边沿检测：按下瞬间触发一次，长按不重复触发，
按键释放后才重置状态，允许再次触发。

GPIO映射（均使用内部上拉 PULL_UP，按下为低电平）：
  音符键:
    do  → GPIO5
    re  → GPIO12
    mi  → GPIO14
    fa  → GPIO18
    so  → GPIO19
    la  → GPIO21
    xi  → GPIO22
  八度键:
    KEY1 → GPIO35（八度+1）
    KEY2 → GPIO34（八度-1）
"""

from machine import Pin

# 音符名 → GPIO引脚号
_NOTE_KEY_MAP = {
    'do':  5,
    're': 12,
    'mi': 14,
    'fa': 18,
    'so': 19,
    'la': 21,
    'xi': 22,
}

# 八度键名 → GPIO引脚号
_OCTAVE_KEY_MAP = {
    'up':   35,  # KEY1 → 八度+1
    'down': 34,  # KEY2 → 八度-1
}

_note_pins = {}     # 音符名 → Pin对象
_note_states = {}   # 音符名 → 状态: 'idle' | 'fired'
_octave_pins = {}   # 八度键名 → Pin对象
_octave_states = {} # 八度键名 → 状态: 'idle' | 'fired'


def _check_edge(pin, states, key):
    """
    通用边沿检测辅助函数（两态状态机）。
    供 get_pressed_key() 和 get_octave_key_event() 复用。

    逻辑：
      - 'idle' + 低电平（按下）→ 切换为 'fired'，返回 True（触发）
      - 'fired' + 仍为低电平（长按）→ 返回 False（不重复触发）
      - 'fired' + 高电平（释放）→ 切换回 'idle'，返回 False

    Args:
        pin (Pin):   按键Pin对象
        states (dict): 状态字典，key为按键标识
        key (str):   当前按键标识，用于索引 states

    Returns:
        bool: True 表示检测到新的按下事件（边沿触发）
    """
    pressed = (pin.value() == 0)  # PULL_UP: 低电平 = 按下

    if states[key] == 'idle' and pressed:
        states[key] = 'fired'
        return True

    if states[key] == 'fired' and not pressed:
        states[key] = 'idle'

    return False


def init():
    """
    初始化所有按键（7音符键 + 2八度键）为输入模式（PULL_UP），
    并将每个按键的状态机设为 'idle'（待触发状态）。
    在 piano.py 启动时调用一次即可。
    """
    for name, gpio in _NOTE_KEY_MAP.items():
        pin = Pin(gpio, Pin.IN, Pin.PULL_UP)
        _note_pins[name] = pin
        _note_states[name] = 'idle'

    for name, gpio in _OCTAVE_KEY_MAP.items():
        pin = Pin(gpio, Pin.IN, Pin.PULL_UP)
        _octave_pins[name] = pin
        _octave_states[name] = 'idle'


def get_pressed_key():
    """
    扫描7个音符按键，返回本次新按下的音符名。

    Returns:
        str | None: 音符名（'do'/'re'/'mi'/'fa'/'so'/'la'/'xi'），
                    无新按下时返回 None
    """
    for name, pin in _note_pins.items():
        if _check_edge(pin, _note_states, name):
            return name
    return None


def get_octave_key_event():
    """
    扫描2个八度切换按键（KEY1/KEY2），返回本次新按下的事件类型。

    Returns:
        str | None: 'up'（KEY1按下，八度+1）、'down'（KEY2按下，八度-1），
                    无新按下时返回 None
    """
    for name, pin in _octave_pins.items():
        if _check_edge(pin, _octave_states, name):
            return name
    return None

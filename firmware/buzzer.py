"""
buzzer.py - 蜂鸣器PWM驱动模块
==============================
通过GPIO25输出PWM信号驱动蜂鸣器（B1），
提供按音符名播放（支持八度偏移）和立即停止的接口。

音符频率参考（Hz）：
  do=262, re=294, mi=330, fa=349, so=392, la=440, xi=494
"""

from machine import Pin, PWM, Timer

# 蜂鸣器PWM引脚
_BUZZER_PIN = 25

# 音符名 → 基频（Hz），对应八度偏移量 0
_NOTE_FREQ = {
    'do': 262,
    're': 294,
    'mi': 330,
    'fa': 349,
    'so': 392,
    'la': 440,
    'xi': 494,
}

_pwm = None               # PWM对象（惰性初始化）
_auto_stop_timer = None   # 自动停止定时器


def _init_pwm():
    """惰性初始化PWM对象（首次使用时创建）。"""
    global _pwm
    if _pwm is None:
        _pwm = PWM(Pin(_BUZZER_PIN), freq=262, duty=0)


def _stop_callback(t):
    """
    定时器回调：将PWM占空比设为0以停止发声。
    注意 MicroPython 定时器回调中应避免内存分配。
    """
    global _pwm
    if _pwm:
        _pwm.duty(0)


def play_note(note_name, duration_ms=300, octave_offset=0):
    """
    播放指定音符，支持八度偏移，持续 duration_ms 毫秒后自动停止（非阻塞）。

    频率计算公式：
      实际频率 = 基频 × (2 ^ octave_offset)
    例如 octave_offset=+1 时 do 从 262Hz 变为 524Hz；
          octave_offset=-1 时 do 从 262Hz 变为 131Hz。

    实现方式：
      1. 计算实际频率，设置PWM频率，占空比50%（duty=512）
      2. 启动一次性定时器，duration_ms 后将 duty 置零

    如果前一个音符尚未停止就调用此函数，会先取消旧的自动停止定时器，
    再设置新音符参数，保证每次只有一个音符在播放。

    Args:
        note_name (str):    音符名，必须是 'do'/'re'/'mi'/'fa'/'so'/'la'/'xi' 之一
        duration_ms (int):  发声时长（毫秒），默认 300
        octave_offset (int): 八度偏移量，范围 -2 ~ +2，默认 0（无偏移）

    Raises:
        ValueError: 传入未识别的音符名
    """
    global _auto_stop_timer

    base_freq = _NOTE_FREQ.get(note_name)
    if base_freq is None:
        raise ValueError("未知音符名: {}".format(note_name))

    # 频率 = 基频 × 2^octave_offset
    freq = int(base_freq * (2 ** octave_offset))

    _init_pwm()

    # 取消之前的自动停止定时器（如果存在）
    if _auto_stop_timer is not None:
        _auto_stop_timer.deinit()

    # 设置频率并开启50%占空比
    _pwm.freq(freq)
    _pwm.duty(512)

    # 启动一次性定时器，到时自动停止
    _auto_stop_timer = Timer(0)
    _auto_stop_timer.init(
        period=duration_ms,
        mode=Timer.ONE_SHOT,
        callback=_stop_callback,
    )


def stop():
    """
    立即停止发声（PWM占空比置零），同时取消自动停止定时器。
    也可用于在音符播放中途手动静音。
    """
    global _auto_stop_timer

    if _auto_stop_timer is not None:
        _auto_stop_timer.deinit()
        _auto_stop_timer = None

    if _pwm is not None:
        _pwm.duty(0)

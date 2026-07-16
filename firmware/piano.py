"""
piano.py - 数字钢琴主调度模块（含八度切换）
============================================
将按键检测（buttons）、蜂鸣器发声（buzzer）、LED反馈（leds）
三个独立模块组合成完整演奏流程，并支持八度切换。

主循环逻辑：
  1. 扫描八度切换按键（KEY1升/KEY2降），更新八度偏移量
  2. 扫描音符按键，检测是否有新按下
  3. 有按下 → 以当前八度偏移量播放对应音符 + 触发LED闪烁反馈
  4. LED颜色策略：音符用奇偶交替绿/红（100ms），八度切换用绿/红（300ms）

本模块只做"调度/编排"，不直接操作GPIO或PWM。
"""

import buttons
import buzzer
import leds
import time

# 八度偏移范围
_OCTAVE_MIN = -2
_OCTAVE_MAX = 2

# 当前八度偏移量（模块级全局变量）
_octave_offset = 0

# 音符顺序（用于确定LED颜色：偶数为绿，奇数为红）
_NOTE_ORDER = ['do', 're', 'mi', 'fa', 'so', 'la', 'xi']

# 每个音符对应的LED颜色
_NOTE_LED_COLOR = {
    note: 'green' if idx % 2 == 0 else 'red'
    for idx, note in enumerate(_NOTE_ORDER)
}


def init():
    """
    初始化所有子模块。
    必须在 run() 之前调用一次。
    """
    buttons.init()


def run():
    """
    启动数字钢琴主循环（含八度切换）。
    循环扫描八度键和音符键，检测到按下时执行对应操作。
    循环间隔约 10ms，保证按键响应灵敏。
    """
    global _octave_offset

    print("数字钢琴已启动，按下按键演奏...")
    print("音符: do(5) re(12) mi(14) fa(18) so(19) la(21) xi(22)")
    print("八度: KEY1(+1) KEY2(-1)，范围 {:+d} ~ {:+d}".format(_OCTAVE_MIN, _OCTAVE_MAX))
    print("当前八度: {:+d}".format(_octave_offset))
    print("Ctrl+C 停止")

    while True:
        try:
            # ---- 八度切换检测 ----
            octave_event = buttons.get_octave_key_event()
            if octave_event is not None:
                if octave_event == 'up':
                    if _octave_offset < _OCTAVE_MAX:
                        _octave_offset += 1
                        leds.flash('green', duration_ms=300)
                        print("八度切换: +1 (当前八度: {:+d})".format(_octave_offset))
                    else:
                        print("八度已达上限 ({:+d})，无法继续升高".format(_OCTAVE_MAX))

                elif octave_event == 'down':
                    if _octave_offset > _OCTAVE_MIN:
                        _octave_offset -= 1
                        leds.flash('red', duration_ms=300)
                        print("八度切换: -1 (当前八度: {:+d})".format(_octave_offset))
                    else:
                        print("八度已达下限 ({:+d})，无法继续降低".format(_OCTAVE_MIN))

            # ---- 音符按键检测 ----
            note = buttons.get_pressed_key()

            if note is not None:
                # 播放音符（非阻塞，内部使用定时器自动停止），携带当前八度偏移
                buzzer.play_note(note, duration_ms=300, octave_offset=_octave_offset)

                # LED闪烁反馈：偶数音符绿灯，奇数音符红灯
                color = _NOTE_LED_COLOR.get(note, 'green')
                leds.flash(color, duration_ms=100)

                print("演奏: {} ({}LED, 八度{:+d})".format(note, color, _octave_offset))

            # 主循环间隔，保证CPU不过载同时按键响应及时
            time.sleep_ms(10)

        except KeyboardInterrupt:
            print("\n数字钢琴已停止")
            buzzer.stop()
            break

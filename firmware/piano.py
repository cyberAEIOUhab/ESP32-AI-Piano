"""
piano.py - 数字钢琴主调度模块
==============================
将按键检测（buttons）、蜂鸣器发声（buzzer）、LED反馈（leds）
三个独立模块组合成完整演奏流程。

主循环逻辑：
  1. 扫描按键，检测是否有新按下
  2. 有按下 → 播放对应音符（300ms）+ 触发LED闪烁反馈
  3. LED颜色策略：音符索引为偶数用绿灯，奇数用红灯

本模块只做"调度/编排"，不直接操作GPIO或PWM。
"""

import buttons
import buzzer
import leds
import time

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
    启动数字钢琴主循环。
    循环扫描按键，检测到按下时播放对应音符并闪烁LED。
    循环间隔约 10ms，保证按键响应灵敏。
    """
    print("数字钢琴已启动，按下按键演奏...")
    print("音符: do(5) re(12) mi(14) fa(18) so(19) la(21) xi(22)")
    print("Ctrl+C 停止")

    while True:
        try:
            note = buttons.get_pressed_key()

            if note is not None:
                # 播放音符（非阻塞，内部使用定时器自动停止）
                buzzer.play_note(note, duration_ms=300)

                # LED闪烁反馈：偶数音符绿灯，奇数音符红灯
                color = _NOTE_LED_COLOR.get(note, 'green')
                leds.flash(color, duration_ms=100)

                print("演奏: {} ({}LED)".format(note, color))

            # 主循环间隔，保证CPU不过载同时按键响应及时
            time.sleep_ms(10)

        except KeyboardInterrupt:
            print("\n数字钢琴已停止")
            buzzer.stop()
            break

"""
melody_record_demo.py - 旋律录制与回放演示脚本（过渡版本）
==========================================================
这是临时演示版本，复用板载 KEY1/KEY2（GPIO35/GPIO34）控制录制和回放。
正式版本将在新按钮到货后集成到 piano.py 中，届时录制/回放将绑定到
专用按钮，不再复用八度切换键。

依赖模块（复用现有实现，不重复造轮子）：
  buttons.py  — 按键边沿检测（7音符键 + KEY1/KEY2）
  buzzer.py   — PWM蜂鸣器驱动
  leds.py     — LED视觉反馈

按键说明（过渡期复用）：
  KEY1 (GPIO35)：录制切换键
    - 第1次按下 → 清空旧数据，开始录制
    - 第2次按下 → 结束录制
  KEY2 (GPIO34)：回放键
    - 按下时回放已录制内容（录制中按下无效）
  7音符键 (GPIO5/12/14/18/19/21/22)：正常弹奏，录制状态下自动记录

使用方法：
  mpremote connect COM3 run melody_record_demo.py
"""

import buttons
import buzzer
import leds
import time

# ============================================================
# 状态变量
# ============================================================
_recording = False         # 是否处于录制中状态
_recorded_notes = []       # 录制数据：[(note_name, interval_ms), ...]
_last_note_ticks = 0       # 上一个音符被检测到的时刻（ticks_ms），用于计算间隔

# 音符 → LED颜色（与 piano.py 保持一致的交替配色）
_NOTE_ORDER = ['do', 're', 'mi', 'fa', 'so', 'la', 'xi']
_NOTE_LED_COLOR = {
    note: 'green' if idx % 2 == 0 else 'red'
    for idx, note in enumerate(_NOTE_ORDER)
}


# ============================================================
# 回放逻辑
# ============================================================
def _playback():
    """
    按录制顺序和时间间隔回放已录制的旋律。
    回放期间阻塞主循环（不检测按键），这是简化处理的过渡方案。
    """
    print("开始回放 (共 {} 个音符)".format(len(_recorded_notes)))

    for i, (note, interval) in enumerate(_recorded_notes):
        color = _NOTE_LED_COLOR.get(note, 'green')

        # 发声（非阻塞，300ms 自动停止） + LED闪烁（阻塞100ms）
        buzzer.play_note(note, duration_ms=300)
        leds.flash(color, duration_ms=100)

        print("回放 [{}/{}]: {} (间隔 {}ms, {}LED)".format(
            i + 1, len(_recorded_notes), note, interval, color))

        # 等待录制时的间隔时间，再播放下一个音符
        # 注：录制时两个音符检测之间的间隔已包含上一个音符的LED闪烁时间，
        # 回放时我们以相同间隔等待，节奏可基本还原
        if i < len(_recorded_notes) - 1:
            time.sleep_ms(interval)

    print("回放完成")


# ============================================================
# 主循环
# ============================================================
def main():
    """主入口：初始化硬件后进入事件循环。"""
    global _recording, _last_note_ticks, _recorded_notes

    print("=" * 40)
    print("  旋律录制与回放演示（过渡版）")
    print("  KEY1: 录制切换  KEY2: 回放")
    print("=" * 40)

    buttons.init()

    while True:
        try:
            # ---- 控制键检测（复用 buttons.py 的八度键接口） ----
            ctrl_event = buttons.get_octave_key_event()

            if ctrl_event == 'up':   # KEY1 → 录制切换
                if not _recording:
                    # 开始录制：清空旧数据，记录起始时刻
                    _recording = True
                    _recorded_notes = []
                    _last_note_ticks = time.ticks_ms()
                    leds.flash('green', duration_ms=200)
                    print("开始录制")
                else:
                    # 结束录制
                    _recording = False
                    leds.flash('green', duration_ms=200)
                    print("录制结束，共录制 {} 个音符".format(len(_recorded_notes)))

            elif ctrl_event == 'down':  # KEY2 → 回放
                if _recording:
                    print("录制中，请先结束录制")
                elif not _recorded_notes:
                    print("暂无录制内容")
                else:
                    _playback()

            # ---- 音符按键检测（复用 buttons.py 的 get_pressed_key） ----
            note = buttons.get_pressed_key()

            if note is not None:
                color = _NOTE_LED_COLOR.get(note, 'green')

                # 录制：在发声前记录时间戳，保证间隔测量准确
                if _recording:
                    now = time.ticks_ms()
                    interval = time.ticks_diff(now, _last_note_ticks)
                    _last_note_ticks = now
                    _recorded_notes.append((note, interval))

                # 正常发声 + LED反馈（录制和纯演奏都触发）
                buzzer.play_note(note, duration_ms=300)
                leds.flash(color, duration_ms=100)

                if _recording:
                    print("录制: {} (间隔 {}ms, {}LED)".format(note, interval, color))
                else:
                    print("演奏: {} ({}LED)".format(note, color))

            # 主循环间隔 10ms，保证按键响应灵敏
            time.sleep_ms(10)

        except KeyboardInterrupt:
            print("\n演示结束")
            buzzer.stop()
            break


# MicroPython / mpremote run 入口
if __name__ == '__main__':
    main()

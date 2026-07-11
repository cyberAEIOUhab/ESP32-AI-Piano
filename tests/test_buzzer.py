from machine import Pin
import time

# GPIO25驱动蜂鸣器,注意:J11必须短接跳线,否则不响
beep = Pin(25, Pin.OUT)

# 音符周期(微秒),数值来自你之前的表
notes = {
    "do": 1914,
    "re": 1703,
    "mi": 1517,
    "fa": 1432,
    "so": 1276,
    "la": 1136,
    "xi": 1012,
}

def play_note(period_us, duration_ms=300):
    cycles = int(duration_ms * 1000 / (2 * period_us))
    for _ in range(cycles):
        beep.value(1)
        time.sleep_us(period_us)
        beep.value(0)
        time.sleep_us(period_us)

print("开始播放音阶 do-re-mi-fa-so-la-xi")
for name, period in notes.items():
    print("播放:", name)
    play_note(period)
    time.sleep_ms(100)

print("蜂鸣器测试完成")

"""
蜂鸣器工作瞬间电流冲击导致电压跌落,触发了ESP32的掉电检测(Brownout Detector),
芯片被强制复位重启,USB连接随之短暂断开重连,Windows这边就表现为"拒绝访问/连接丢失"
目前暂无解决方案
"""
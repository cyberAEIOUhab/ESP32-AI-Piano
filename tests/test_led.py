from machine import Pin
import time

# LED2(绿)-GPIO32, LED3(红)-GPIO33, 均为低电平点亮
led_green = Pin(32, Pin.OUT)
led_red = Pin(33, Pin.OUT)

"""
新加入。作用：开始前保证红绿灯均熄灭。原因：这是一个很典型也很值得记录的现象,原因和ESP32上电瞬间GPIO的默认状态有关,不是硬件故障。
为什么会这样
LED2/LED3是低电平点亮,而ESP32从完全断电(拔插USB)重新上电到你的代码真正开始执行这段时间里,存在一个短暂的"空窗期"——
芯片刚上电:GPIO32/33此时处于硬件默认状态(通常是低电平或者不确定的浮空状态),这个状态不受你的代码控制,是芯片启动前物理电路本身的默认行为
MicroPython固件加载、REPL初始化:这个过程也需要一点时间
你的代码开始执行,Pin(32, Pin.OUT)、Pin(33, Pin.OUT)才真正把这两个引脚设置成确定的电平
在第1步到第3步之间的空窗期,如果两个GPIO恰好都处于低电平(低电平=点亮),就会出现你看到的"两个灯同时亮"的瞬间现象。
"测试中观察到:完全断电重新上电时,LED2/LED3会短暂同时点亮,随后恢复正常;而软件重新运行不会出现此现象。
经分析,这是ESP32上电瞬间GPIO默认状态与代码尚未执行之间的空窗期导致,属正常现象,已在初始化代码中显式指定初始电平以缩短该窗口。"
"""
led_green.value(1)
led_red.value(1)

print("开始测试LED2(绿)")
led_green.value(0)  # 点亮
time.sleep(1)
led_green.value(1)  # 熄灭
time.sleep(1)

print("开始测试LED3(红)")
led_red.value(0)    # 点亮
time.sleep(1)
led_red.value(1)    # 熄灭
time.sleep(1)

print("交替闪烁测试")
for i in range(5):
    led_green.value(0)
    led_red.value(1)
    time.sleep(0.5)
    led_green.value(1)
    led_red.value(0)
    time.sleep(0.5)

led_green.value(1)
led_red.value(1)
print("LED测试完成")
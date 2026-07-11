from machine import Pin
import time

# GPIO34-KEY2, GPIO35-KEY1
key1 = Pin(35, Pin.IN)
key2 = Pin(34, Pin.IN)

print("开始测试按键,按下KEY1/KEY2观察输出(Ctrl+C停止)")

#电平触发 这段代码每隔0.1秒就检查一次电平,只要按键一直按着(电平持续是0),就会一直满足条件、一直打印——这叫电平触发
while 0:
    if key1.value() == 0:
        print("KEY1 被按下")
    if key2.value() == 0:
        print("KEY2 被按下")
        
    time.sleep(0.1)
    
#去抖动+状态锁定
while True:
    if key1.value() == 0 and key1_state == 1:
        key1_state = 2
        print("KEY1 被按下")
    elif key1.value() == 1:
        key1_state = 1

    if key2.value() == 0 and key2_state == 1:
        key2_state = 2
        print("KEY2 被按下")
    elif key2.value() == 1:
        key2_state = 1

    time.sleep(0.02)
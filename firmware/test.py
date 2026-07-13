from machine import Pin
import time

key = Pin(5, Pin.IN, Pin.PULL_UP)
while True:
    print(key.value())
    time.sleep(0.3)
"""
main.py - 数字钢琴程序入口
===========================
ESP32上电自动执行此文件（MicroPython约定）。
导入 piano 模块并启动主循环，附带异常保护，
避免单次按键读取或PWM操作异常导致整个程序崩溃。
"""

import sys
import time

try:
    import piano
except ImportError as e:
    print("模块导入失败: {}".format(e))
    print("请确保所有 .py 文件已上传到ESP32")
    sys.exit(1)


def main():
    """
    程序主入口。
    初始化钢琴模块并进入主循环，
    外层 try/except 捕获非致命的运行时异常，
    打印错误信息后短暂等待并继续运行。
    """
    print("=" * 40)
    print("  ESP32 数字钢琴")
    print("=" * 40)

    # 初始化硬件
    try:
        piano.init()
    except Exception as e:
        print("硬件初始化失败: {}".format(e))
        sys.exit(1)

    # 进入主循环（内部自带 KeyboardInterrupt 处理）
    while True:
        try:
            piano.run()
            # run() 正常退出（KeyboardInterrupt）后也退出外层循环
            break
        except KeyboardInterrupt:
            print("\n程序终止")
            break
        except Exception as e:
            # 捕获其他未预期的运行时异常，打印后短暂等待再重试
            print("运行异常: {}".format(e))
            time.sleep_ms(500)


# MicroPython 上电自动执行入口
if __name__ == '__main__':
    main()

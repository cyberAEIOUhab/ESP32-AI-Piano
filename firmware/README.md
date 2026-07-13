# ESP32 数字钢琴 — 固件说明

## 模块职责

| 文件 | 职责 | 对外接口 |
|------|------|----------|
| `buttons.py` | 7按键初始化（PULL_UP）与边沿检测 | `init()`, `get_pressed_key()` |
| `buzzer.py` | GPIO25 PWM 蜂鸣器驱动 | `play_note(note, duration_ms)`, `stop()` |
| `leds.py` | 板载LED2/LED3控制（屏蔽低电平点亮细节） | `led_on(which)`, `led_off(which)`, `flash(which, duration_ms)` |
| `piano.py` | 调度层：按键→发声→LED反馈 | `init()`, `run()` |
| `main.py` | 程序入口 + 异常保护 | 上电自动执行 |

## GPIO 映射表

### 外接7按键（J4排针，内部上拉，按下为低电平）

| 音符 | GPIO | 说明 |
|------|------|------|
| do   | 5    | Strapping pin，已确认不影响启动 |
| re   | 12   | Strapping pin，已确认不影响启动 |
| mi   | 14   | — |
| fa   | 18   | — |
| so   | 19   | — |
| la   | 21   | — |
| xi   | 22   | — |

### 蜂鸣器

| 功能 | GPIO | 说明 |
|------|------|------|
| B1 蜂鸣器 PWM | 25 | 需 J11 跳线短接（硬件已连接） |

### 音符频率

| 音符 | 频率 (Hz) |
|------|-----------|
| do   | 262       |
| re   | 294       |
| mi   | 330       |
| fa   | 349       |
| so   | 392       |
| la   | 440       |
| xi   | 494       |

### 板载LED（低电平点亮）

| LED | 颜色 | GPIO |
|-----|------|------|
| LED2 | 绿 | 32 |
| LED3 | 红 | 33 |

### 板载按键（可选扩展/调试）

| 按键 | GPIO |
|------|------|
| KEY1 | 35 |
| KEY2 | 34 |

## 按键边沿检测逻辑

```
状态机（每按键独立）:

  idle ──按下(低电平)──→ fired（返回音符名，触发演奏）
   ↑                      │
   └──释放(高电平)────────┘

长按保持期间（fired + 低电平）不重复返回，
确保每次按下只触发一次音符。
```

## LED 配色方案

音符按顺序交替使用绿灯和红灯：

| 音符 | LED 颜色 |
|------|----------|
| do   | 绿       |
| re   | 红       |
| mi   | 绿       |
| fa   | 红       |
| so   | 绿       |
| la   | 红       |
| xi   | 绿       |

## 如何运行

### 前置条件

- 安装 [mpremote](https://pypi.org/project/mpremote/)：`pip install mpremote`
- ESP32 已刷入 MicroPython 固件
- ESP32 通过 USB 连接电脑

### 上传固件到 ESP32

```bash
# 在项目根目录执行

# 1. 创建远程目录
mpremote mkdir firmware

# 2. 上传所有模块文件
mpremote cp firmware/buttons.py :firmware/buttons.py
mpremote cp firmware/buzzer.py  :firmware/buzzer.py
mpremote cp firmware/leds.py    :firmware/leds.py
mpremote cp firmware/piano.py   :firmware/piano.py
mpremote cp firmware/main.py    :main.py

# 3. 软复位启动
mpremote reset
```

### 一键上传脚本（Windows Git Bash / Linux / macOS）

```bash
# 在项目根目录执行
mpremote mkdir firmware 2>/dev/null
mpremote cp firmware/buttons.py :firmware/buttons.py
mpremote cp firmware/buzzer.py  :firmware/buzzer.py
mpremote cp firmware/leds.py    :firmware/leds.py
mpremote cp firmware/piano.py   :firmware/piano.py
mpremote cp firmware/main.py    :main.py
mpremote reset
```

### 交互式调试

```bash
# 进入 REPL 查看串口输出
mpremote repl

# 或组合使用：先上传再进入 repl
mpremote cp firmware/main.py :main.py && mpremote repl
```

### 上电自动运行

`main.py` 位于 ESP32 文件系统根目录时，MicroPython 上电会自动执行。
上传后按 RST 键或 `mpremote reset` 即可启动钢琴程序。

### 停止程序

在 REPL 中按 `Ctrl+C` 中断主循环。

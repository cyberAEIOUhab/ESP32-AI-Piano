# ESP32-AI-Piano

基于 ESP32 的 AI 辅助数字钢琴与 AI 原生开发工具链

## 项目简介

本项目旨在构建一台 AI 辅助的数字钢琴系统，通过 ESP32 作为主控芯片，结合无源蜂鸣器实现音符发声，并辅以 LED 灯光反馈与物理按键交互。项目涵盖硬件设计、固件开发以及一套完整的 AI 原生开发工具链（Toolchain），支持代码上传、串口监控、远程执行与错误诊断，探索 AI 辅助嵌入式开发的全新工作流。

## 硬件平台

- **主控**：ESP32
- **音频**：无源蜂鸣器（可选 PWM 或 DAC 输出）
- **输入**：物理按键（多键矩阵 / 独立按键）
- **反馈**：LED 指示灯 / WS2812 灯带

## 项目结构

```
ESP32-AI-Piano/
├── README.md                 # 项目说明
├── LICENSE                   # MIT 许可证
├── .gitignore                # Git 忽略规则
├── firmware/                 # ESP32 MicroPython 固件
│   ├── main.py               # 入口程序
│   ├── buzzer.py             # 蜂鸣器驱动
│   ├── buttons.py            # 按键扫描
│   ├── leds.py               # LED 控制
│   └── piano.py              # 钢琴逻辑
├── toolchain/                # AI 原生开发工具链
│   ├── mcp_server.py         # MCP 服务端入口
│   ├── tools/                # 工具集
│   │   ├── file_transfer.py  # 文件传输
│   │   ├── serial_monitor.py # 串口监控
│   │   ├── executor.py       # 远程执行器
│   │   └── error_handler.py  # 错误诊断
│   └── README.md             # 工具链说明
├── hardware/                 # 硬件设计
│   ├── schematic.pdf         # 原理图
│   ├── pcb.pdf               # PCB 设计图
│   └── bom_analysis.md       # BOM 物料分析
├── docs/                     # 项目文档
├── tests/                    # 测试用例
│   ├── test_led.py
│   ├── test_key.py
│   └── test_buzzer.py
├── images/                   # 图片资源
└── report/                   # 项目报告
```

## 运行方法

> 待补充：固件烧录步骤、依赖安装、启动方式等详细说明。

## 许可证

本项目采用 [MIT License](LICENSE)。

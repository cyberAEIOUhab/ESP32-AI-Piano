"""
toolchain/tools/ — ESP32 AI Piano 工具集
=========================================

每个工具模块实现一个 MCP 工具能力。
所有工具通过 serial_connection.SerialConnection 单例共享串口连接。
"""

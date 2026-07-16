# ESP32 AI Piano — 工具链

基于 MCP (Model Context Protocol) 的 ESP32 开发工具链，连接 AI 模型与物理硬件。

## 快速开始

### 安装依赖

```bash
pip install pyserial mcp
```

### 单独测试 serial_monitor（不通过 AI）

```bash
# 在 toolchain 目录下运行
cd toolchain
python -m tools.serial_monitor [监控秒数]

# 示例：监控 5 秒
python -m tools.serial_monitor 5
```

**前提条件**：
1. ESP32 已通过 USB 连接，串口为 COM3
2. 固件正在运行（有持续的 print 输出）
3. 关闭 Thonny、mpremote、Arduino IDE Serial Monitor 等占用 COM3 的程序

**预期输出**：
- 列出系统可用串口
- 监控指定时长，期间所有 ESP32 print 输出逐行显示
- 最后打印统计信息（捕获行数、断连次数、耗时）

如果 ESP32 未连接或 COM3 被占用，会显示明确错误提示而非崩溃。

### 启动 MCP Server

```bash
cd toolchain
python mcp_server.py
```

启动后服务器进入 stdio 监听模式，等待 Claude Code 通过 MCP 协议连接。日志输出到 stderr，JSON-RPC 通信走 stdout。

单独测试 MCP Server（发送 JSON-RPC 请求验证）：

```bash
echo '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' | python mcp_server.py
```

### 配置 Claude Code 连接

在自己的 Claude Code 配置文件中添加：

```json
{
  "mcpServers": {
    "esp32-piano": {
      "command": "python",
      "args": ["toolchain/mcp_server.py"],
      "cwd": "C:/Users/notch/Desktop/ESP32-AI-Piano"
    }
  }
}
```

配置后 Claude Code 会自动启动 MCP Server 进程并注册 `serial_monitor` 工具。

## 目录结构

```
toolchain/
├── ARCHITECTURE.md          # 架构设计文档（读这个了解整体设计）
├── README.md                # 本文件
├── mcp_server.py            # MCP 服务器入口
├── serial_connection.py     # 串口连接管理单例
└── tools/
    ├── __init__.py
    ├── serial_monitor.py    # [✅ 已实现] 串口监控
    ├── file_transfer.py     # [⏳ 待实现] 文件传输
    ├── executor.py          # [⏳ 待实现] 程序执行
    └── error_handler.py     # [⏳ 待实现] 错误报告
```

## 已知限制

| 限制 | 说明 | 预计解决 |
|------|------|----------|
| **仅实现 1/6 工具** | 目前只有 `serial_monitor` 可用，`file_transfer`、`execute_program`、`reset_device`、`fetch_logs`、`report_error` 待后续阶段实现 | 第三周+ |
| **端口硬编码** | 串口参数（COM3/115200）目前硬编码，未支持命令行参数或配置文件 | 第二周后续 |
| **Windows 专属** | COM3 是 Windows 串口命名，Linux/macOS 为 `/dev/ttyUSB0` | 后续增加自动检测 |
| **单串口** | 工具链运行时独占 COM3，不能同时使用 Thonny/mpremote | 硬件限制，文档提示即可 |
| **无日志持久化** | 监控期间捕获的数据仅在内存中，不落盘 | 后续 fetch_logs 工具实现时增加 |
| **MCP 测试覆盖** | 仅测试了 serial_monitor 独立运行，MCP Server 端到端测试待补充 | 第二周后续 |

## 错误处理设计

本工具链遵循"永不崩溃"原则：所有底层异常都被捕获并转换为结构化错误信息返回给 AI，而非抛出异常导致 MCP Server 进程崩溃。详见 [ARCHITECTURE.md](ARCHITECTURE.md) 第四节。

针对 ESP32 硬件已知问题（蜂鸣器 PWM 导致 USB 供电跌落 → 串口断连），`serial_connection.py` 内置了 3 次自动重连机制（间隔 1 秒），`serial_monitor.py` 在后台线程中持续读取 + 断连恢复，确保偶发硬件问题不会导致工具链服务中断。

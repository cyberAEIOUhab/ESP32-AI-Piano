# ESP32 AI Piano — 工具链

基于 MCP (Model Context Protocol) 的 ESP32 开发工具链，连接 AI 模型与物理硬件。

**V2 架构**：后台采集线程从 MCP Server 启动即开始运行，ESP32 输出持续缓存，AI 随时查询"最近发生了什么"。

## 快速开始

### 安装依赖

```bash
pip install pyserial mcp
```

### 单独测试 serial_monitor（不通过 AI）— V2 交互式测试

V2 测试改为交互式：先启动后台采集，你去弹几个琴键，再查询缓存验证。

```bash
cd toolchain
python -m tools.serial_monitor [查询窗口秒数]

# 示例：启动后台采集，弹几个音符后按回车查询最近 15 秒数据
python -m tools.serial_monitor 15
```

**测试流程**：
1. 脚本自动连接 COM3 并启动后台采集线程
2. 提示"你现在可以去按 ESP32 上的按键，数据会被自动捕获"
3. 你去弹几个琴键（产生 print 输出）
4. 按回车 → 查询后台缓存中最近 N 秒的数据
5. 验证：按键期间没调用 monitor()，但数据已被后台线程捕获

**前提条件**：
1. ESP32 已通过 USB 连接，串口为 COM3
2. 固件正在运行（有持续的 print 输出）
3. 关闭 Thonny、mpremote、Arduino IDE Serial Monitor 等占用 COM3 的程序

**预期输出**：
- 列出系统可用串口
- 确认"后台采集已启动"
- 按回车后显示查询窗口内捕获到的所有输出行
- 最后打印统计信息（命中行数、断连次数、缓冲区状态）

如果 ESP32 未连接或 COM3 被占用，会显示明确错误提示而非崩溃。

### 启动 MCP Server

```bash
cd toolchain
python mcp_server.py
```

启动后：
1. 自动连接 COM3 并启动后台采集线程（日志: `"后台串口采集已启动"`）
2. 进入 stdio 监听模式，等待 Claude Code 通过 MCP 协议连接
3. 日志输出到 stderr，JSON-RPC 通信走 stdout

单独测试 MCP Server（发送 JSON-RPC 请求验证）：

```bash
# 需要先发 initialize 再发 tools/list（MCP 协议要求）
printf '{"jsonrpc":"2.0","id":0,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"1.0"}}}\n{"jsonrpc":"2.0","method":"notifications/initialized","params":{}}\n{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}\n' | python mcp_server.py 2>/dev/null
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
├── mcp_server.py            # MCP 服务器入口（启动时连接 COM3 + 开启后台采集）
├── serial_connection.py     # 串口连接管理单例 + 后台采集线程 + 缓冲区
└── tools/
    ├── __init__.py
    ├── serial_monitor.py    # [✅ V2] 串口监控（查询后台缓存，毫秒级返回）
    ├── file_transfer.py     # [⏳ 待实现] 文件传输
    ├── executor.py          # [⏳ 待实现] 程序执行
    └── error_handler.py     # [⏳ 待实现] 错误报告
```

## V2 vs V1 行为对比

| 方面 | V1（旧） | V2（新） |
|------|----------|----------|
| 数据采集 | 调用 monitor() 时才临时启动线程采集 N 秒 | 服务器启动起后台线程持续采集 |
| 工具调用 | `monitor(10)`: 阻塞等待 10 秒后返回 | `monitor(10)`: 查询最近 10 秒缓存，毫秒级返回 |
| 数据丢失风险 | AI 没提前调用 monitor() 就错过 | 不会错过——启动起全量缓存 |
| CPU 占用 | 只在调用期间有后台线程 | 后台 daemon 线程持续运行（100ms 间隔，CPU 忽略不计） |
| 内存占用 | 无持久缓存 | deque 最多 1000 行，约 150KB |

## 已知限制

| 限制 | 说明 | 预计解决 |
|------|------|----------|
| **仅实现 1/6 工具** | 目前只有 `serial_monitor` 可用，`file_transfer`、`execute_program`、`reset_device`、`fetch_logs`、`report_error` 待后续阶段实现 | 第三周+ |
| **端口硬编码** | 串口参数（COM3/115200）目前硬编码，未支持命令行参数或配置文件 | 第二周后续 |
| **Windows 专属** | COM3 是 Windows 串口命名，Linux/macOS 为 `/dev/ttyUSB0` | 后续增加自动检测 |
| **单串口** | 工具链运行时独占 COM3，不能同时使用 Thonny/mpremote | 硬件限制，文档提示即可 |
| **无日志持久化** | 缓存仅在内存中（deque, 1000 行），不落盘 | 后续 fetch_logs 工具实现时增加 |
| **后台线程生命周期** | 后台采集线程的生命周期 = MCP Server 进程的生命周期，Server 退出则缓存丢失 | 设计如此 |

## 错误处理设计

本工具链遵循"永不崩溃"原则：所有底层异常都被捕获并转换为结构化错误信息返回给 AI，而非抛出异常导致 MCP Server 进程崩溃。详见 [ARCHITECTURE.md](ARCHITECTURE.md) 第四节。

**V2 后台线程容错**：`_background_reader_loop` 的每次迭代都有完整 try/except 保护，单次串口异常不会导致后台采集线程退出。断连时自动调用 `try_reconnect()`，重连成功后无缝继续。

针对 ESP32 硬件已知问题（蜂鸣器 PWM 导致 USB 供电跌落 → 串口断连），`serial_connection.py` 内置了 3 次自动重连机制（间隔 1 秒），后台采集线程在每次循环中自动检测并恢复连接，确保偶发硬件问题不会导致工具链服务中断。

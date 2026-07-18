# ESP32 AI Piano — 工具链架构设计文档

> 版本: 0.2.0 | 日期: 2026-07-18 | 状态: 第一阶段（1/6 工具已实现）+ V2 后台采集重构

## 一、总体架构

### 1.1 为什么选择 MCP Server 方案？

本项目需要一个能够连接 AI 模型和 ESP32 物理硬件的桥接层。在考察了三种方案后，选择 MCP Server：

| 方案 | 优点 | 缺点 | 结论 |
|------|------|------|------|
| **MCP Server** | 开放标准协议，Claude Code/Desktop 原生支持；工具定义即文档（Tool Description + Schema 由 AI 自行理解）；Python SDK 成熟 | 需要单独启动一个进程 | ✅ 选型 |
| Codex 插件 | VS Code 内置，UI 集成好 | 闭源生态，仅限 Copilot；无法自定义工具语义 | ❌ 过于封闭 |
| Zcode 扩展 | 某些社区项目在用 | 小众，文档不全，上游维护不稳定 | ❌ 风险太高 |

**核心决策逻辑**：MCP（Model Context Protocol）将"AI 能做什么"定义为一系列 **工具（Tool）**，每个工具有清晰的 `name` / `description` / `inputSchema`。Claude 等模型通过标准 JSON-RPC 协议发现和调用这些工具，完全不需了解底层串口通信细节。当未来增加新能力（如文件传输、程序执行），只需在 `list_tools()` 中注册新工具即可，架构上零侵入。

### 1.2 四层角色关系（V2 更新）

```
┌─────────────────────────────────────────────────────────────┐
│                      AI 模型 (Claude)                        │
│  理解用户意图 → 选择合适的工具 → 解析工具返回的结构化结果       │
└─────────────────────┬───────────────────────────────────────┘
                      │ MCP 协议 (JSON-RPC over stdio)
                      ▼
┌─────────────────────────────────────────────────────────────┐
│                   MCP Server (mcp_server.py)                 │
│  启动时: 建立串口连接 + 启动后台采集线程                       │
│  运行时: 注册工具列表(list_tools) → 接收调用请求(call_tool)    │
│  → 分发给对应的工具模块 → 格式化返回结果                       │
└────────┬──────────────────────────────────┬─────────────────┘
         │ Python 函数调用                    │ 后台采集线程
         ▼                                  │ (持续运行)
┌────────────────────────────────────────────┼─────────────────┐
│              工具层 (toolchain/tools/*.py)  │                  │
│  serial_monitor / file_transfer / ...      │                  │
│  → 查询: get_recent_lines() 从缓存取       │                  │
│  → 写入: 通过 SerialConnection 单例         │                  │
└─────────────────────┬──────────────────────┼─────────────────┘
                      │                      │
         ┌────────────┴──────────┐           │
         ▼                       ▼           ▼
┌─────────────────────────────────────────────────────────────┐
│            SerialConnection 单例 (serial_connection.py)       │
│                                                             │
│  _serial (物理连接)          _buffer (deque, maxlen=1000)    │
│  connect()/disconnect()      _background_reader_loop()       │
│  read_available_lines()      后台 daemon 线程，100ms 间隔     │
│  try_reconnect()             get_recent_lines(n, since_sec)  │
│  is_connected()              断连自动重连（3次/1秒）          │
└─────────────────────┬───────────────────────────────────────┘
                      │ pyserial
                      ▼
┌─────────────────────────────────────────────────────────────┐
│                  ESP32 物理硬件 (COM3, 115200)               │
└─────────────────────────────────────────────────────────────┘
```

**V2 关键约束**：
- AI 不直接访问硬件，所有串口操作都封装在工具层/SingleConnection 内
- **后台采集线程从 MCP Server 启动即开始运行**，独立于任何工具调用
- ESP32 的 print 输出被持续缓存（带时间戳），AI 随时查询"最近发生了什么"
- 工具调用从"实时等待 N 秒采集"变为"查询最近 N 秒缓存"，毫秒级返回

---

## 二、6 项基本能力接口定义

### 2.1 工具总览

| # | 工具名 | 功能 | 状态 |
|---|--------|------|------|
| 1 | `serial_monitor` | 串口监控：查询后台缓存的 ESP32 print 输出（V2: 后台持续采集 + 按需查询） | ✅ 已实现 |
| 2 | `file_transfer` | 文件传输：将 Python 文件上传到 ESP32 或从 ESP32 下载 | 📋 待实现 |
| 3 | `execute_program` | 程序执行：触发 ESP32 上指定模块的运行/停止 | 📋 待实现 |
| 4 | `reset_device` | 微控制器复位：通过串口 DTR/RTS 或命令触发 ESP32 重启 | 📋 待实现 |
| 5 | `fetch_logs` | 运行日志检索：基于关键字/时间范围从历史日志中查询 | 📋 待实现 |
| 6 | `report_error` | 错误报告：解析 ESP32 输出的异常信息，生成结构化错误报告 | 📋 待实现 |

### 2.2 接口详细定义

#### (1) serial_monitor — 串口监控（V2：后台缓存查询模式）

| 字段 | 内容 |
|------|------|
| **工具名** | `serial_monitor` |
| **功能描述** | **V2 语义**：查询最近 N 秒内后台缓存的 ESP32 串口输出，调用立即返回（毫秒级）。后台采集线程从 MCP Server 启动即开始运行，ESP32 的所有 print 输出被持续追加到带时间戳的 deque 缓冲区（容量 1000 行），无需 AI 提前"掐时机"监控。 |
| **输入参数** | `duration_sec` (float, 可选, 默认10.0) — 查询最近多少秒的缓存数据，范围 1~300 |
| **返回值** | `{ "status": "ok" \| "partial" \| "error", "lines": [...], "line_count": N, "disconnects": N, "duration_sec": 10.0 }` |
| **与 V1 的区别** | V1 是"实时等待 N 秒并将期间数据返回"（阻塞式），V2 是"查询后台已缓存的最近 N 秒数据"（非阻塞）。V1 如果 AI 没调用就错过数据，V2 从启动起全量缓存，AI 随时补查。 |

#### (2) file_transfer — 文件传输

| 字段 | 内容 |
|------|------|
| **工具名** | `file_transfer` |
| **功能描述** | 将本地 Python 文件上传到 ESP32 文件系统，或从 ESP32 下载指定文件到本地。基于 MicroPython 的 raw REPL 文件操作协议。 |
| **输入参数** | `direction` (str, 必填) — `"upload"` 或 `"download"`；`local_path` (str, 必填) — 本地文件路径；`remote_path` (str, 必填) — ESP32 上的目标路径 |
| **返回值** | `{ "status": "ok" \| "error", "bytes_transferred": N, "remote_path": "..." }` |
| **异常处理** | 串口被占用 → 提示关闭其他程序（mpremote/Thonny）；传输超时 → 重试 2 次后返回错误；文件不存在 → `status="error"` + 明确提示 |

#### (3) execute_program — 程序执行

| 字段 | 内容 |
|------|------|
| **工具名** | `execute_program` |
| **功能描述** | 通过串口 REPL 在 ESP32 上执行指定的 Python 模块或代码片段，捕获 stdout 输出和可能的异常信息。 |
| **输入参数** | `module` (str, 可选) — 要执行的模块名（如 `"piano"`）；`code` (str, 可选) — 直接执行的代码片段；`timeout_sec` (float, 可选, 默认 30.0) — 等待执行完成的超时 |
| **返回值** | `{ "status": "ok" \| "error", "stdout": "...", "stderr": "...", "exit_code": 0 }` |
| **异常处理** | 串口不可用 → 返回连接错误；执行超时 → 发送 Ctrl+C 中断后返回部分输出；ESP32 崩溃 → 尝试捕获复位原因并报告 |

#### (4) reset_device — 微控制器复位

| 字段 | 内容 |
|------|------|
| **工具名** | `reset_device` |
| **功能描述** | 通过串口 DTR/RTS 信号或 Ctrl+D 软复位指令触发热重启，等待 ESP32 重新就绪后返回。 |
| **输入参数** | `mode` (str, 可选, 默认 `"soft"`) — `"soft"`（REPL Ctrl+D）或 `"hard"`（DTR 拉低）；`wait_ready_sec` (float, 可选, 默认 5.0) — 等待设备就绪的超时时间 |
| **返回值** | `{ "status": "ok" \| "error", "boot_msg": "...", "ready": true }` |
| **异常处理** | 复位后设备无响应 → 超时返回错误；DTR 操作失败（部分 CH9102 驱动不支持）→ 自动回退到软复位 |

#### (5) fetch_logs — 运行日志检索

| 字段 | 内容 |
|------|------|
| **工具名** | `fetch_logs` |
| **功能描述** | 从后台采集线程维护的历史日志缓存中检索符合条件的日志行，支持按关键字和时间范围过滤。V2 有了持续缓存后，此工具的实现基础已具备（get_recent_lines 提供了 since_sec 过滤）。 |
| **输入参数** | `keyword` (str, 可选) — 搜索关键字；`since_sec` (float, 可选) — 最近 N 秒内的日志；`max_lines` (int, 可选, 默认 100) — 最多返回行数 |
| **返回值** | `{ "status": "ok", "matches": [...], "match_count": N, "total_cached": N }` |
| **异常处理** | 缓存为空 → 返回空列表 + 提示"后台采集尚未缓存数据"；无匹配 → `match_count=0` + 提示调整过滤条件 |

#### (6) report_error — 错误报告/异常检测

| 字段 | 内容 |
|------|------|
| **工具名** | `report_error` |
| **功能描述** | 解析后台缓存中的最近串口输出，识别异常模式（Traceback、ImportError、OSError 等），生成结构化诊断报告。 |
| **输入参数** | `context_lines` (int, 可选, 默认 50) — 检查最近 N 行缓存 |
| **返回值** | `{ "status": "ok", "errors": [{ "type": "...", "message": "...", "line": "..." }], "has_errors": true \| false }` |
| **异常处理** | 缓存为空 → 返回 `has_errors=false` + 提示信息；无法解析 → 返回原始文本 + `type="unclassified"` |

---

## 三、串口连接管理策略

### 3.1 问题背景

ESP32 通过 CH9102 USB-UART 芯片连接电脑，**同一时刻只能有一个程序打开 COM3**。多个工具（serial_monitor / file_transfer / execute_program 等）如果各自独立创建 `serial.Serial()` 连接，必然互相抢占，导致 `SerialException: Access is denied`。

### 3.2 设计决策：单例连接管理器 + 后台采集线程（V2）

```
┌──────────────────────────────────────────────────────┐
│          SerialConnection (单例)                      │
│                                                      │
│  _instance: SerialConnection (唯一实例)               │
│  _serial: serial.Serial (唯一物理连接)                │
│                                                      │
│  ┌──────────────────────────────────────────────┐    │
│  │  后台采集线程 (_background_reader_loop)       │    │
│  │  - daemon 线程，Server 启动时创建             │    │
│  │  - 100ms 间隔非阻塞读取                       │    │
│  │  - 断连自动重连（3次/1秒）                    │    │
│  │  - 异常不退出，持续恢复                       │    │
│  └────────────────┬─────────────────────────────┘    │
│                   │ 写入                              │
│                   ▼                                  │
│  ┌──────────────────────────────────────────────┐    │
│  │  缓冲区 (deque, maxlen=1000)                  │    │
│  │  每条: {"timestamp": float, "line": str}      │    │
│  └────────────────┬─────────────────────────────┘    │
│                   │ 查询                              │
│                   ▼                                  │
│  get_recent_lines(n, since_sec)                      │
│                                                      │
│  connect() / disconnect() / start_background_...()   │
│  read_available_lines() / try_reconnect()            │
│  is_connected() / collection_active                 │
│  get_disconnect_count() / last_error                │
└──────────────────────────────────────────────────────┘
        ▲              ▲              ▲
        │              │              │
   serial_monitor  file_transfer  execute_program ...
```

**核心规则**：
- 所有工具通过 `SerialConnection()` 获取同一个实例，共享同一个底层 `serial.Serial` 对象
- 工具不直接 `import serial` 或创建连接，必须通过 `SerialConnection` 单例访问串口
- 连接建立后保持打开状态，**后台采集线程持续运行**，由工具链退出时统一关闭
- `read_available_lines()` 为非阻塞（`in_waiting` 检查），后台线程 100ms 间隔调用
- `get_recent_lines()` 从内存缓冲区查询，毫秒级返回，支持按数量和按时间窗口过滤

**缓冲区容量选择**：`maxlen=1000`。以 ESP32 115200bps、钢琴固件每秒 1-3 行 print 计算，1000 行覆盖约 5-15 分钟，足够调试会话回溯。内存占用约 150KB（含时间戳），可忽略不计。

### 3.3 与外部工具的共存约束

工具链运行时占用 COM3，**用户需确保不与其他工具同时使用**：
- 关闭 Thonny 的串口监视器
- 不使用 mpremote 的 `run` / `repl` 命令
- 关闭 Arduino IDE 的 Serial Monitor

MCP Server 启动时会在日志中打印 `"占用端口: COM3"`，断开时打印 `"释放端口: COM3"`，方便用户排查冲突。

---

## 四、错误处理设计原则

### 4.1 "永不崩溃"原则

工具链作为桥接 AI 和硬件的中间层，**任何底层异常都不应导致 MCP Server 进程崩溃**。原因：
- MCP Server 崩溃 → Claude 收到 `Connection closed` 错误 → 用户看到的是"工具挂了"而非"硬件出了问题"
- AI 有更好的错误理解能力，应该把结构化错误信息交给 AI 而非直接抛出异常

### 4.2 分级处理策略

```
Level 1: 操作级重试
  ├── 串口读/写遇到 SerialException
  ├── 自动重试 3 次，间隔 1 秒
  └── 重试成功 → 继续，对上层透明

Level 2: 连接级恢复（由后台采集线程执行）
  ├── 3 次重试均失败 → 标记连接丢失
  ├── 尝试完整重连（disconnect → connect）
  ├── 后台线程在每次循环中检查连接状态并自动重连
  └── 成功后继续采集，记录断连次数

Level 3: 结构化错误返回
  ├── 连接恢复也失败 → 向上返回 { "status": "error", "error_message": "..." }
  ├── AI 收到结构化错误 → 可据此给出用户友好的提示
  └── 工具函数绝不 raise，而是 return 带 status="error" 的字典
```

### 4.3 针对已知硬件问题的专项处理

**问题**：蜂鸣器 PWM 占空比过高导致 USB 供电瞬间跌落 → 串口中断（`SerialException`）。

已在固件侧修复（`duty=50`），但类似的瞬时断连风险仍可能因其他硬件原因偶发。工具链的策略：

1. **后台线程容错**：`_background_reader_loop` 的每次迭代都有完整的 try/except 保护，单次异常不会导致线程退出
2. **自动重连**：检测到断连后，后台线程调用 `try_reconnect()`（3次/1秒间隔），重连成功后无缝继续采集
3. **断连计数**：`get_disconnect_count()` 暴露累计断连次数，AI 可以据此判断"当前硬件是否稳定"
4. **数据完整性**：断连期间 ESP32 输出的数据（几毫秒内）不可恢复，但缓冲区的现有数据不会丢失
5. **优雅降级**：重连失败时 `status="partial"` + 返回已有数据，而非丢弃全部结果

### 4.4 日志与可观测性

所有工具模块使用 Python `logging` 模块，关键事件（连接/断开/重试/异常）记录在 `INFO` 和 `WARNING` 级别。MCP Server 启动时默认配置 `StreamHandler` 输出到 stderr（MCP 协议规定 stdout 用于 JSON-RPC 通信，日志必须走 stderr）。

---

## 五、目录结构

```
toolchain/
├── ARCHITECTURE.md          # 本文档
├── README.md                # 安装与使用说明
├── mcp_server.py            # MCP Server 入口（启动时建立连接+后台采集）
├── serial_connection.py     # 串口连接管理单例（含后台采集线程+缓冲区）
└── tools/
    ├── __init__.py
    ├── serial_monitor.py    # [✅ V2] 串口监控（查询后台缓存）
    ├── file_transfer.py     # [待实现] 文件传输
    ├── executor.py          # [待实现] 程序执行
    └── error_handler.py     # [待实现] 错误报告
```

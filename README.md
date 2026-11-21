# ERFlow

用自然语言生成可编辑的 **E-R 图** 与 **UML 用例图**。描述系统后，可在工作台改规格、拖拽微调布局，并导出 PNG / SVG / PDF / JSON。

欢迎页支持中 / 英文与浅色 / 深色主题。

## Features

- 自然语言生成 E-R 与 UML 用例图规格
- 可视化编辑实体 / 联系 / 参与者 / 用例 / include·extend·泛化
- 自动排版与拖拽微调；画布比例、字体与线宽可调
- 规格 JSON 导入导出；E-R 可保存实体与联系位置
- 多模型渠道（硅基流动、DeepSeek、New API、Ollama 等）
- 账号登录、邮箱验证码注册；按账号统计 Token 用量（含服务商分项）
- 网页渠道密钥按标签页会话隔离；命令行仍可用本机 `llm.local.json`
- 语义沙助手：使用问答、受控外联、草稿工具与执行记录（见 [`docs/assistant-execution-plane.md`](docs/assistant-execution-plane.md)）

## Stack

| Layer | Tech |
| --- | --- |
| Frontend | React 18 · TypeScript · Vite |
| Backend | FastAPI · Uvicorn · Matplotlib · NetworkX |
| Data | 本地 SQLite（账号 / 用量 / 准入，不入库提交） |

## Requirements

- Python 3.11+（推荐）
- Node.js 18+
- 可用的 LLM API（硅基流动、DeepSeek 或其他 OpenAI 兼容渠道）

## Quick start

### 1. Backend

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
python start_backend.py
```

后端默认监听 `http://127.0.0.1:8000`。

也可直接：

```bash
uvicorn api:app --host 127.0.0.1 --port 8000
```

### 2. Frontend

```bash
cd frontend
npm install
npm run dev
```

浏览器打开 `http://127.0.0.1:5173`。开发模式下 `/api` 会代理到后端 `8000` 端口。

首次使用：注册 / 登录 → 打开 **API 平台** 导入并启用自己的模型渠道 → 回到工作台出图。网页渠道保存在当前标签页的 `sessionStorage`，不会写入仓库。

### 3. CLI 模型配置（可选）

命令行调用生成器时，可使用本机 `llm.local.json`（已 gitignore）。网页账号需自行在 API 平台导入渠道，与 CLI 配置相互独立。

### 4. Use-case layout benchmark

用例图自动排版可用固定验收集比较改动前后的结果：

```bash
python -X utf8 benchmark_usecase.py --baseline benchmarks/usecase_baseline.json --output usecase_report.json
```

基准分为回归、独立评估和压力三组，含固定乱序版本。耗时只统计排版；同一机器和字体下可用 `--repeats` 重复测量。报告中的 `graphPlanar` 记录关系图是否平面，实际画法还受系统框和图元尺寸约束。

## Configuration

| File / Dir | Purpose |
| --- | --- |
| `llm.local.json` | 命令行本地模型配置（gitignore） |
| `smtp.local.json` | 注册验证码邮件 SMTP（gitignore） |
| `smtp.local.example.json` | SMTP 配置模板 |
| `auth.sqlite3` | 账号与会话（gitignore） |
| `token-usage.sqlite3` / `user-usage/` | 用量统计（gitignore） |
| `service-limits.sqlite3` | 同机并发准入（gitignore） |
| `assistant-traces.sqlite3` | 助手执行记录（gitignore） |

复制并编辑 SMTP 模板（需要邮箱验证码注册时）：

```bash
cp smtp.local.example.json smtp.local.json
```

### Web channels

- 在 **API 平台** 导入渠道；密钥按登录账号存在当前标签页 `sessionStorage`，刷新仍可用，关闭标签页后需重新导入。
- 退出、切换账号时清理旧账号的标签页密钥；其他已打开标签页收到登录状态变化后也会清理。渠道操作串行提交，超时 30 秒，防止旧响应覆盖新设置。
- 请求通过 `X-Erflow-Providers` 把头里的渠道交给后端；后端用请求级 ContextVar 隔离，生成与助手共用当前渠道。
- 排版请求不发送模型密钥。API 响应（包括准入错误）带 `Cache-Control: no-store`、`nosniff`；422 参数校验不回显输入值。

### Outbound model calls

- 模型地址须为公网 HTTPS、443 端口；拒绝内网、回环、链路本地与重定向。
- 服务器直连校验后的 IP，并验证原始域名的 TLS 证书。
- 系统 DNS 若返回 `198.18/15` 代理虚拟地址，会经 Cloudflare HTTPS DNS 查真实 A 记录后再固定 IP 连接。
- 生产环境请使用正常公网 DNS，并在出站防火墙限制内网与云元数据访问。

### Concurrency & deploy

- 同机多进程由 `service-limits.sqlite3` 协调。默认模型任务上限 4、排版上限 2，每账号每类任务同时 1 个。
- 可用环境变量 `ERFLOW_MODEL_CONCURRENCY` / `ERFLOW_RENDER_CONCURRENCY`（范围 1–16）。
- 速率：每账号实际模型调用 30 次/分（重试、续写也计数），排版 60 次/分，助手对话另限 60 次/分；渠道探测独立限流，登录注册及验证码每 IP 共 10 次/分。并发繁忙统一返回 429 与 `Retry-After`。
- 模型名额在实际 `llm_chat` 调用期间申请，纯本地 FAQ 和结构审查不占名额；同一生成任务两次模型调用之间会释放名额。渠道探测仍有独立并发保护。
- 助手可选的模型路由忙时回退规则路由，模型续跑忙时直接保留已完成的回复和操作；用户明确请求的模型工具忙时仍返回 429。
- 并发容量在进程启动时统一读取，调整配置后重启。排版内部 `ERFLOW_LAYOUT_WORKERS` 默认 1（串行），范围 1–16，小服务器建议保持默认。
- 认证接口始终按来源 IP 计数，不能通过更换登录 token 重置计数。应用只信任 ASGI 提供的客户端地址，反向代理转发地址需由服务器限定受信任代理。
- SQLite 准入与会话查验在线程池执行，避免数据库等待堵塞异步请求；请求体最大 256 KiB，上传限时 15 秒。现有并发租约有效期 240 秒，长任务仍需在现有生成/排版超时预算内结束。
- 部署需可写运行数据目录、HTTPS 与受信任反向代理；代理需接纳最长约 32 KB 的渠道请求头。多机扩容时请将 SQLite 准入换成共享服务。

回归检查：

```bash
python -m unittest discover -s tests -p test_multiuser.py
```

## Project layout

```
.
├── LICENSE                # MIT
├── api.py                 # FastAPI 入口
├── er_generator.py        # E-R 生成与排版
├── usecase_generator.py   # 用例图生成与排版
├── llm_providers.py       # 模型渠道
├── model_transport.py     # 出站地址校验与安全连接
├── request_scope.py       # 请求级渠道 / 账号上下文
├── request_limits.py      # 并发与速率准入
├── token_usage.py         # Token 用量
├── auth.py / mailer.py    # 登录注册与邮件
├── start_backend.py       # 后端启动（可自动重载）
├── assistant/             # 语义沙执行面
├── benchmarks/            # 用例排版基准
├── docs/                  # 设计与验收说明
├── examples/              # 选课 E-R / 图书借阅用例样例
├── tests/                 # 多用户等回归
└── frontend/              # Vite + React 工作台
```

## Scripts

| Command | Description |
| --- | --- |
| `python start_backend.py` | 启动后端（可 `--no-reload`） |
| `cd frontend && npm run dev` | 前端开发服务器 |
| `cd frontend && npm run build` | 类型检查并构建前端 |
| `python -X utf8 benchmark_usecase.py …` | 用例排版基准 |
| `python -m unittest discover -s tests -p test_multiuser.py` | 多用户回归 |

## License

本项目以 [MIT License](LICENSE) 发布。

第三方图标素材仍按其原许可证使用，见 `frontend/src/assets/providers/LOBE_ICONS_LICENSE`。

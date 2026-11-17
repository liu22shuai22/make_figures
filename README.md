# ERFlow

用自然语言生成可编辑的 **E-R 图** 与 **UML 用例图**。描述系统后，可在工作台改规格、拖拽微调布局，并导出 PNG / SVG / JSON。

欢迎页支持中 / 英文界面切换；主题与语言由欢迎页统一控制。

## Features

- 自然语言生成 E-R 图与 UML 用例图规格
- 可视化编辑实体 / 联系 / 参与者 / 用例 / include·extend·泛化
- 自动排版与拖拽微调，支持画布比例与 PNG / SVG 导出
- 规格 JSON 导入导出；E-R 可保存实体位置
- 多模型渠道（硅基流动、DeepSeek、New API、Ollama 等）
- 账号登录、邮箱验证码注册、Token 用量统计
- 语义沙助手：使用问答与草稿结构检查

## Stack

| Layer | Tech |
| --- | --- |
| Frontend | React 18 · TypeScript · Vite |
| Backend | FastAPI · Uvicorn · Matplotlib · NetworkX |
| Data | 本地 SQLite（账号 / 用量，不入库提交） |

## Requirements

- Python 3.11+（推荐）
- Node.js 18+
- 可用的 LLM API（硅基流动或其他 OpenAI 兼容渠道）

## Quick start

### 1. Backend

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
python start_siliconflow.py
```

后端默认监听 `http://127.0.0.1:8000`。首次启动会提示输入硅基流动 API Key。

也可直接：

```bash
uvicorn api:app --host 127.0.0.1 --port 8000
```

此时需自行配置模型渠道（环境变量或 API 平台页）。

### 2. Frontend

```bash
cd frontend
npm install
npm run dev
```

浏览器打开 `http://127.0.0.1:5173`。开发模式下 `/api` 会代理到后端 `8000` 端口。

### 3. Tests

```bash
python -m unittest discover -s tests -v
```

## Configuration

| File | Purpose |
| --- | --- |
| `llm.local.json` | 本地模型渠道与密钥（已 gitignore） |
| `smtp.local.json` | 注册验证码邮件 SMTP（已 gitignore） |
| `smtp.local.example.json` | SMTP 配置模板 |
| `auth.sqlite3` / `token-usage.sqlite3` | 本地运行时数据（已 gitignore） |

复制并编辑 SMTP 模板：

```bash
cp smtp.local.example.json smtp.local.json
```

也可在工作台打开 **API 平台** 接入 / 切换模型渠道，无需改代码。

## Project layout

```
.
├── api.py                 # FastAPI 入口
├── er_generator.py        # E-R 生成与排版
├── usecase_generator.py   # 用例图生成与排版
├── llm_providers.py       # 模型渠道
├── auth.py / mailer.py    # 登录注册与邮件
├── start_siliconflow.py   # 硅基流动一键启动
├── examples/              # 选课 E-R / 图书借阅用例样例
├── tests/
└── frontend/              # Vite + React 工作台
```

## Scripts

| Command | Description |
| --- | --- |
| `python start_siliconflow.py` | 启动后端（可 `--new-key` / `--no-reload`） |
| `cd frontend && npm run dev` | 前端开发服务器 |
| `cd frontend && npm run build` | 类型检查并构建前端 |
| `python -m unittest discover -s tests -v` | 运行单元测试 |

## License

暂未指定开源许可证。图标素材见 `frontend/src/assets/providers/LOBE_ICONS_LICENSE`。

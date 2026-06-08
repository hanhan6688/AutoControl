# Mobile-AI-TestOps

AI 驱动的移动端和 PC/Web 自动化测试平台。

## 功能特性

- **移动端测试**: 通过 Open-AutoGLM 执行 Android/iOS/HarmonyOS 自动化测试
- **PC/Web 测试**: 通过 agent-browser 执行浏览器自动化测试
- **AI 编排**: 自动将AutoGLM转换为执行任务书
- **判断 Agent**: 根据预期结果自动判断测试通过/失败
- **报告体系**: 生成 JSON + HTML 格式的测试报告
- **人工接管**: 支持登录、验证码、扫码等敏感步骤的手动处理

## 快速开始

### 环境要求

- Python 3.11+
- Node.js 18+
- ADB (Android Debug Bridge)

### 后端启动

```bash
cd backend
pip install -r requirements.txt
python -m uvicorn app.main:app --reload
```

也可以在项目根目录启动后端：

```bash
npm run dev:backend
```

### 前端 / Electron 启动

```bash
cd frontend
npm install
npm run dev
```

上面的命令只启动 Vite 浏览器模式。需要直接弹出 Electron 窗口时，在项目根目录执行：

```bash
npm install
npm run dev
```

常用启动命令：

| 命令 | 说明 |
|------|------|
| `npm run dev` | 根目录执行，启动 Vite + Electron，并自动查找/启动后端 |
| `npm run dev:browser` | 根目录执行，只启动前端浏览器模式 |
| `npm run dev:backend` | 根目录执行，只启动 FastAPI 后端 |
| `cd frontend && npm run dev` | 只启动 Vite，不启动 Electron |

### 访问地址

- 前端: http://localhost:5173
- 后端 API: http://localhost:8000
- API 文档: http://localhost:8000/docs

### 打包 exe

```bash
npm run package:exe
```

打包会先构建前端，再由 `desktop/electron-builder` 生成 Windows 安装包。当前打包资源包含前端 `dist`、后端源码、`scrcpy-win64`、`tools/agent-browser`。Python 运行环境仍建议由目标机器提前准备，或后续单独做内置 Python/runtime 打包。

## 配置

复制 `backend/.env.example` 到 `backend/.env` 并修改配置：

```bash
cp backend/.env.example backend/.env
```

主要配置项：

| 配置项 | 说明 |
|--------|------|
| DATABASE_URL | 数据库连接字符串 |
| AUTOGLM_BASE_URL | AutoGLM 服务地址 |
| CASE_PLANNER_PROVIDER | AutoGLM query 改写模型协议，支持 `minimax_auto`、`openai_compatible`、`anthropic_compatible`、`custom_openai` |
| CASE_PLANNER_BASE_URL | AI 编排服务地址 |
| CASE_PLANNER_MODEL | AI 编排模型名 |
| CASE_PLANNER_API_KEY | AI 编排 API Key |
| PC_AGENT_PROVIDER | PC/Web Agent 模型协议，默认 `minimax_auto` |
| PC_AGENT_BASE_URL | PC/Web Agent 模型地址，默认 `https://api.minimaxi.com/v1` |
| PC_AGENT_MODEL | PC/Web Agent 模型名，默认 `MiniMax-M2.7` |
| PC_AGENT_API_KEY | PC/Web Agent API Key |
| ANDROID_STREAM_PROVIDER | 安卓网页投屏 provider，默认 `scrcpy-h264`；`auto` 会优先 scrcpy，失败后只降级到 `minicap` |

## PC/Web 自动化

PC/Web 用例通过 agent-browser 执行，AI 只负责输出下一步结构化动作。PCAutoExecute 页面提供：

- 模型厂商/模型/API Key 配置
- 单任务逐步执行
- 人工登录/验证码暂停
- 每步截图和日志
- Leyoujia 测试/生产环境登录态保存/加载

Leyoujia 环境使用顺序：

1. 打开 `PC AutoExecute`
2. 选择 `测试环境 zero-ai-test` 或 `生产环境 zero-ai`
3. 点击 `打开登录页`
4. 在打开的登录页面手动完成扫码/登录
   - 测试环境登录页：`https://itest.leyoujia.com/jjslogin/index`
   - 生产环境登录页：`https://i.leyoujia.com/jjslogin/index`
5. 点击 `保存登录态`
6. 再运行目标 Web 用例
   - 测试环境目标：`https://zero-ai-test.leyoujia.com/`
   - 生产环境目标：`https://zero-ai.leyoujia.com/`

账号密码不要写进源码或报告；当前流程按扫码/手动登录后保存浏览器登录态处理。如果运行环境无法访问 Leyoujia 域名，系统会提示网络或登录态问题，不会让 AI 盲跑。

## 运维与清理

项目提供只读健康检查：

```bash
curl http://127.0.0.1:8000/api/diagnostic/project-health
```

报告和截图清理默认 dry-run：

```bash
curl -X POST http://127.0.0.1:8000/api/diagnostic/artifacts/cleanup ^
  -H "Content-Type: application/json" ^
  -d "{\"max_age_days\":30,\"dry_run\":true}"
```

确认候选列表无误后再设置 `"dry_run": false`。清理范围只限 `backend/static/reports` 和 `backend/static/uploads`，并保护 `.gitkeep`。

## 验证命令

```bash
python -m pytest backend\tests -q
cd frontend
npm run build
```

## 项目结构

```
Mobile-AI-TestOps
├── backend/           # FastAPI 后端
│   ├── app/
│   │   ├── routers/   # API 路由
│   │   ├── services/  # 业务服务
│   │   └── models.py  # 数据模型
│   └── tests/         # AutoGLM
├── frontend/          # Vue 3 前端
│   └── src/
│       ├── views/     # 页面组件
│       └── api.ts     # API 调用
├── tools/             # 外部工具
│   └── Open-AutoGLM/  # 移动端执行器
└── docs/              # 文档
```

## 版本

当前版本: v1.0

## License

MIT

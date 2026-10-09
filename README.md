# 人机恋 · Tether

一个本地优先、可更换模型的 AI 恋爱伴侣应用。它把不同人设、独立会话、可查看的长期记忆、关系状态和承诺追踪放在同一个界面里。默认不需要任何外部服务：没有 API Key 时使用本地 Demo Provider，接入一个 OpenAI-compatible LLM 后即可切换成真实对话。

## 现在能做什么

- 在 3 个预置人设之间切换，也可以在界面中创建新角色。
- 每个角色拥有独立会话和对话历史；点击“重来”会开启新的会话。
- 用“请记住……”或“记住……”明确写入长期记忆，记忆会在右侧展示并注入后续模型 Prompt。
- 记录关系状态：好感、信任、亲密、紧张、能量；每轮对话都会留下可解释的状态更新。
- 识别“我会……”等明确承诺，并把待兑现事项单独列出。
- 提供 JSON API、SSE 渐进式输出、OpenAI-compatible provider 和运行时设置接口。
- 前端由 FastAPI 直接提供，启动一个进程即可使用，不需要 Node 构建链。

## 启动

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
./run.sh
```

打开 <http://127.0.0.1:8000/>。接口文档在 <http://127.0.0.1:8000/docs>。

也可以直接执行：

```bash
python -m uvicorn backend.app.main:app --reload --port 8000
```

## 接入一个 LLM API

复制 `backend/.env.example` 的变量到当前 shell 或部署环境：

```bash
export LLM_API_KEY="你的 API Key"
export LLM_BASE_URL="https://api.openai.com/v1"  # 兼容 OpenAI Chat Completions 的服务
export LLM_MODEL="gpt-4o-mini"
./run.sh
```

也可以在页面右下角的“API 与偏好设置”里临时修改 Base URL 和模型。密钥只保存在后端进程内存中，SQLite 默认保存于 `backend/data/companion.sqlite3`（已被 `.gitignore` 忽略）。

## 目录

```text
frontend/           恋爱风格静态前端（HTML/CSS/JS）
backend/app/        FastAPI API、SQLite 数据层、LLM provider
ARCHITECTURE_DRAFT.md  调研后的产品与长期记忆架构
run.sh              单命令启动脚本
```

## API 主路径

- `GET /health`
- `GET/POST /api/personas`
- `GET/POST /api/sessions`
- `GET/POST /api/sessions/{id}/messages`
- `POST /api/sessions/{id}/messages/stream`（SSE）
- `GET/POST /api/sessions/{id}/memories`
- `GET /api/sessions/{id}/state`
- `GET/PATCH /api/sessions/{id}/promises`
- `GET/PATCH /api/settings/provider`

`/api/characters` 和 `/api/conversations` 也提供了兼容别名，方便后续接入更完整的角色卡或 Agent runtime。

## 参考的开源项目

实现时参考了以下公开项目的思路，没有复制它们的 GPL/AGPL 前端代码：

- [elizaOS/eliza](https://github.com/elizaOS/eliza)：provider、runtime、memory/action 分层。
- [letta-ai/letta](https://github.com/letta-ai/letta)：有状态 Agent 与跨会话长期记忆。
- [SillyTavern](https://github.com/SillyTavern/SillyTavern)：角色卡、lore/context 注入和多模型适配。
- [Open WebUI](https://github.com/open-webui/open-webui)：OpenAI-compatible provider 与本地部署体验。

## 当前边界

首版使用 SQLite 和保守的显式记忆抽取，SSE 是“先生成完整回复，再按片段输出”的兼容协议，不是假装成模型原生 token 流。后续可替换为真正的 `generate_stream`、向量检索、摘要/梦境沉淀和账号系统，而不改变前端 API 形状。

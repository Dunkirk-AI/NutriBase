# NutriBase 后端交接

项目为 FastAPI + DeepSeek 图像识别与营养估算服务。请先阅读 `main.py`、`prompt.txt`、`start.md`。

## 当前接口
- `POST /analyze`：multipart `file`（JPG/PNG）与 `weight_g`（正数）
- `GET /reports`：读取本地 JSON 报告
- `GET /docs`：Swagger 接口文档

## 当前优先任务
1. 检查前端无法调用公网后端的问题：CORS、端点字段名不一致、Cloudflare Tunnel、公网可达性和浏览器控制台错误。
2. 保持当前后端最小化、无需数据库。
3. 不要写入或暴露任何真实 API Key；从环境变量读取 `DEEPSEEK_API_KEY`。
4. 在 `README.md` 中写清本地启动、公网联调和 API 调用示例。
5. 修改完提交清晰的 diff；不要伪称已验证真实公网 tunnel。

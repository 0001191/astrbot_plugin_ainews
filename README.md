# AI 新闻聚合 (astrbot_plugin_ainews)

即时获取最重要的 AI 新闻，聚合多源：Hugging Face Daily Papers、NewsAPI、OpenAI/DeepMind RSS 等。

## 指令

- `/ainews` 或 `ainews`：获取最新 AI 新闻摘要（默认最多 10 条）
- `/ai新闻` 或 `ai新闻`：同上

## 数据源

- **Hugging Face Daily Papers**：每日论文摘要
- **NewsAPI.org**：需配置 API Key（[免费申请](https://newsapi.org/register)），免费版约 100 次/天
- **OpenAI 新闻**：RSS
- **DeepMind 博客**：RSS

## 配置（可选）

在 AstrBot 插件配置或 `_conf_schema.json` 中可设置：

- `newsapi_key`：NewsAPI 的 API Key，不填则跳过该源
- `max_items`：返回条数上限，默认 10

## 安装

在 AstrBot 内使用：`plugin i https://github.com/0001191/astrbot_plugin_ainews`

# lightcrawl 实测问题记录

测试时间: 2026-05-22
测试任务: 使用 lightcrawl 搜索"健康元近10年软件购置投入"

---

## 问题 1: 搜索后端无配置文件支持，API Key 只能通过环境变量注入

**严重程度**: 高

**现象**:
- `tvly` CLI 已通过 `tvly login` 认证，API Key 存储在 `~/.tavily/config.json`
- lightcrawl 的 `search` / `search-and-read` 只能从环境变量（`TAVILY_API_KEY`、`BRAVE_SEARCH_API_KEY`、`SERPER_API_KEY`）读取 key
- `~/.lightcrawl/` 目录下没有 `config.json`，没有任何本地配置文件机制
- 用户即使已经通过 `tvly login` 认证，仍需手动 `export TAVILY_API_KEY=$(cat ~/.tavily/config.json | jq -r .api_key)` 才能使用 lightcrawl 搜索

**建议**:
- lightcrawl 应读取 `~/.tavily/config.json` 作为 `TAVILY_API_KEY` 的 fallback
- 或支持 `lightcrawl auth add-backend tavily <key>` 存储 API key 到 `~/.lightcrawl/config.json`

**复现**:
```bash
$ .venv/bin/lightcrawl list-backends
# 所有 backend 都是 configured: false

$ .venv/bin/lightcrawl search "测试" --backend tavily
# NO_BACKEND_CONFIGURED: TAVILY_API_KEY is not set
```

---

## 问题 2: `list-backends` 没有配置引导

**严重程度**: 中

**现象**:
- `list-backends` 显示所有后端 `configured: false`，但不告诉用户如何配置
- 只有在实际搜索失败后，错误信息里才会给出建议（"set one of: BRAVE_SEARCH_API_KEY..."）
- 用户先运行 `list-backends` 看到未配置状态后，不知道下一步该做什么

**建议**: 在 `list-backends` 的输出中直接加入配置指引（需要设置哪个环境变量、或者如何通过 CLI 配置）

---

## 问题 3: 搜索结果的 snippet 质量差——出现导航 HTML

**严重程度**: 中

**现象**:
- 来自 `money.finance.sina.com.cn` 的搜索结果 snippet 是原始导航 HTML：
  ```
  [![新浪网](http://i1.sinaimg.cn/dy/images/header/2009/standardl2nav_sina_new.gif)](http://www.sina.com.cn/)...
  ```
- 这些 snippet 对用户没有任何信息价值，是内容提取管道未处理导航栏的结果

**建议**: 搜索结果摘要应从页面正文提取，而非直接从原始 HTML 截取；或者在 search backend 层面过滤掉纯导航文本

---

## 问题 4: 搜索结果 snippet 乱码

**严重程度**: 中

**现象**:
- 来自 `money.finance.sina.com.cn` 的财务数据页面，snippet 显示为乱码中文：
  ```
  ˾ƸĻʦڣ | | ͬʦͨϻ
  ```
- 推测是 character encoding mismatch（GB2312/GBK vs UTF-8）

**建议**: search backend 应检测并正确解码非 UTF-8 页面

---

## 问题 5: 内容提取污染——joincare.com 页面充斥导航菜单

**严重程度**: 中

**现象**:
- `fetch https://www.joincare.com/news_detail/59.html` 返回了 5300+ 字符的导航菜单文本
- 页面使用 `<script>` 动态渲染文章内容，但源码中不包含文章正文
- 自动 `<main>`/`<article>` scoping 无效，因为页面不使用这些语义标签
- `--selector` 参数存在但用户需要知道页面的具体 DOM 结构才能使用

**实际返回的有用内容**: 标题 + 一张图片 + 两个链接（上一页/下一页），没有文章正文

**建议**: 对于 SPA 页面，自动检测到内容/文本比例极低时，应自动升级到 L2（浏览器渲染）并给出提示

---

## 问题 6: SSE 年报 PDF 链接被重定向到 HTML 下载页

**严重程度**: 低

**现象**:
- `https://static.sse.com.cn/disclosure/listedinfo/announcement/c/new/2025-04-08/600380_20250408_UYT2.pdf`
- SSE（上海证券交易所）的 PDF 链接返回的是 HTML 下载页面，不是原始 PDF
- lightcrawl 正确报了 `UNSUPPORTED_CONTENT_TYPE: expected application/pdf; got text/html`
- 但错误信息没有建议用户该如何获取该 PDF（比如使用 browser 策略访问下载页）

**建议**: 当检测到 PDF URL 返回 HTML 时，提示用户尝试 `--strategy browser`

---

## 问题 7: 部分 PDF 标题提取为空

**严重程度**: 低

**现象**:
- `http://notice.10jqka.com.cn/api/pdf/9b836f7d322ef2cb.pdf` 的 `title` 字段为空字符串
- 该 PDF 第一页明确包含标题"健康元药业集团股份有限公司 2025 年年度报告"

**建议**: PDF 标题提取逻辑应尝试从文档开头提取（而非仅依赖 PDF metadata）

---

## 问题 8: `--read-top-n` 命名不一致

**严重程度**: 低

**现象**:
- `search-and-read` 使用 `--read-top-n` 控制读取条数
- 用户自然尝试 `--max-results`（更符合 CLI 惯例）
- 错误提示只显示 `unrecognized arguments: --max_results 5`，不提示正确的参数名

**建议**: 添加 `--max-results` 作为 `--read-top-n` 的别名，或至少在错误信息中提示正确参数名

---

## 问题 9: content overflow 到 dump 文件对用户透明，但截断标记不够明显

**严重程度**: 低

**现象**:
- `search-and-read` 返回的 `fetched_pages[0]` 标记 `content_truncated: true` 且 `tokens_returned: 4000`
- 但实际上只在 `dump_path` 字段中记录了溢出文件路径
- 响应中没有提示用户"内容被截断，完整内容在 dump 文件中"
- 对于 `search-and-read` 场景，用户很可能没注意到 `content_truncated` 字段

**建议**: 当 `content_truncated: true` 时，在响应顶层或页面级别给出显式提示

---

## 总结

| # | 问题 | 严重度 | 类别 |
|---|------|--------|------|
| 1 | API Key 只能通过环境变量配置，不支持 config 文件 | 高 | 配置体验 |
| 2 | list-backends 无配置引导 | 中 | 用户体验 |
| 3 | 搜索 snippet 含导航 HTML | 中 | 内容质量 |
| 4 | 搜索 snippet 中文乱码 | 中 | 内容质量 |
| 5 | joincare.com 页面内容被导航污染 | 中 | 内容提取 |
| 6 | SSE PDF 链接重定向到 HTML | 低 | 边界情况 |
| 7 | PDF 标题提取为空 | 低 | 内容提取 |
| 8 | --read-top-n 命名不直观 | 低 | CLI 设计 |
| 9 | 内容截断缺少显式提示 | 低 | 用户体验 |

# 开发难题与解决方案

> 记录项目开发过程中遇到的真实技术问题，用于面试时展示工程判断力。

---

## 1. LLM 重复调用同一个工具

**现象**：用户问"帮我搜一下悉尼的 fintech 后端实习"，`search_jobs` 被连续调用 3 次，响应时间是正常的 3 倍。

**第一反应（错的）**：在 system prompt 里加一句"每个工具只调用一次"。这是打地鼠——加了规则，换个场景还会复发，治标不治本。

**根因定位**：在 agent 循环里打了追踪日志，发现前两次调用的 tool result 是 `"ok": false, "error": "1 validation error"`。LLM 看到工具报错后重试——行为完全正确，不是模型问题。

继续追：打印每次调用的实际 arguments，发现 `filters` 参数被传成了 JSON 字符串 `"{\"location\": \"Sydney\"}"` 而不是 object。

**真正根因**：Pydantic 的 `model_json_schema()` 默认生成带 `$defs` + `$ref` 的 JSON Schema。Qwen 不能正确解析 `$ref` 引用，把嵌套 object 参数序列化成了字符串，导致 Pydantic 校验失败。

**解法**：在 `_build_tool_schemas()` 里将所有 `$defs`/`$ref` 递归展开成 inline schema 再传给 LLM。同时把 `filters: {location, work_type}` 展平成顶层参数，彻底规避嵌套 object 问题。

**结果**：`search_jobs` 从 3 次调用降为 1 次，响应时间减少约 2/3。

---

## 2. LLM 跳过工具直接输出幻觉内容

**现象**：用户搜悉尼软件实习，agent 有时不调 `search_jobs`，直接输出 Atlassian、Canva 等公司名——这些是 LLM 训练数据里的知名公司，不是数据库里的真实岗位。

**第一反应（错的）**：在 system prompt 加"求职问题必须调工具"。这是 prompt 打地鼠，换个问法还会绕过。

**根因定位**：LLM 决定是否调工具的依据是工具描述。`search_jobs` 的描述是 `"Search jobs using a natural language query."` ——太模糊，LLM 无法判断"调这个工具"和"直接从训练数据回答"哪个更好，于是凭训练知识回答。

**真正根因**：工具描述没有传达两个关键信息：① 这个工具连接的是实时数据库；② LLM 自身的训练数据没有当前岗位信息，用训练数据回答一定是错的。

工具描述是 LLM 和工具之间的**接口契约**，描述不准确 → LLM 做出错误决策。

**解法**：把描述改成："Search the live job postings database for real, current openings. You MUST call this tool whenever the user asks about job opportunities — your training data does not contain current listings and will be fabricated."

**结果**：LLM 在所有求职查询场景下均调用 `search_jobs`，不再产生幻觉岗位。

---

## 3. 为什么选择 Pydantic Protocol 而不是 ABC 定义 JobProvider

**背景**：接入 Adzuna API 时需要定义一个 `JobProvider` 接口，未来替换成 CareerHub 或其他数据源。

**选择**：用 `typing.Protocol` 而不是 `ABC`。

**原因**：`Protocol` 是结构子类型（structural subtyping）——任何实现了 `fetch_jobs` 方法的类都自动满足接口，不需要显式继承。这意味着未来接入 CareerHub 时，只要新类有正确的方法签名，不需要修改任何现有代码。`ABC` 则需要显式继承，对外部数据源适配器更侵入。

---

## 4. ChromaDB $ref 展开的工程决策

**背景**：修复 Qwen 无法解析 `$ref` 的 bug 时，有两种选项：
1. 在 `_build_tool_schemas()` 里递归展开 `$defs`/`$ref`
2. 手写每个工具的 JSON Schema，完全绕过 Pydantic 自动生成

**选择方案 1 的原因**：Pydantic 自动生成的 schema 是唯一真相来源，手写 schema 会造成双重维护负担——每次修改 input model 都要同步手写 schema，迟早出现不一致。展开逻辑写一次，所有工具都受益。

---

*最后更新：2026-05-02*

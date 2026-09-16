# generate-image / 生图

> 一条命令出图,**多 provider 可插拔 + 自动能力路由**。默认 `auto` 按请求能力从
> **OpenAI / 302.AI / OpenRouter / SiliconFlow / 火山方舟 Seedream / 147ai** 里挑一个已配置的,
> 显式 `-p` 始终覆盖自动选择。内置连接池 + 计费感知重试 + 限流 + 自适应并发。
> Saves a PNG to `~/Pictures/generate-image/`, previews inline in kitty.

<p align="center">
  <img src="docs/sample-funnel.jpg" alt="样例:漏斗压缩" width="380">
  <img src="docs/sample-layers.jpg" alt="样例:双层筛网" width="380">
</p>

> 上面两张是用本 skill 出的扁平矢量插图(`gpt-image-2`, 16:9)。当前默认模型已是 `gpt-image-2.5-flare`。

---

## 这是什么

`生图 / 画图 / 出图 / 搞张图` 的 Claude Code skill。把出图后端抽象成一张 **provider 注册表**
(`providers.py`),封装了比例控制、图生图、批量、本地保存,以及一套 **SOTA 可靠性层**
(`reliability.py`:计费感知重试 / Retry-After / token-bucket 限流 / AIMD 自适应并发 / 幂等键)。
另附一套绘本/系列插图 prompt 模板(`templates.md`)。

## Provider(`-p` / `--provider`)

| Provider | base_url | 出图端点 | 图生图 `--ref` | size 方言 | Key env |
|---|---|---|---|---|---|
| **`openai`**(auto 首选) | api.openai.com | `/v1/images/generations` | multipart edits | `size` **自定义 WxH 真控**(16 的倍数、1:3~3:1、边 ≤3840) | `OPENAI_API_KEY` |
| `302ai` | api.302.ai | `/v1/images/generations` | multipart edits | `size` **真认自定义 WxH**(实测 2048²=4.19MP);`quality` 也真认 | `AI302_API_KEY` |
| `openrouter` | openrouter.ai/api | `/v1/images` | chat image_url | 无(靠 `-r`) | `OPENROUTER_API_KEY` |
| `siliconflow` | api.siliconflow.cn | `/v1/images/generations` | image_prompt | `image_size` WxH(真控) | `SILICONFLOW_API_KEY` |
| `volcengine` | ark.cn-beijing.volces.com/api/v3 | `/images/generations` | Ark JSON `image[]`(本地文件自动 Base64) | `size: 2K` + `-r` 提示词 | `ARK_API_KEY` |
| `147ai` | nn.147ai.com | 双方言,随模型切换 | 两条线都支持 | **真控**,pro 模型可到 4K | `AI147_API_KEY` |

`base_url` / 默认模型可用 env 覆盖(`OPENAI_BASE_URL`、`OPENROUTER_DEFAULT_MODEL`…),
不改代码就能接入其它 OpenAI 兼容 provider。

## 用法

```bash
# 默认 auto 路由 / 16:9
./generate.py "夕阳下的金门大桥,油画风格"
./generate.py -r 9:16 "竖版手机壁纸"                       # 比例靠 -r,别写进 prompt

# 切 provider
./generate.py -p openai "品牌标志"
./generate.py -p siliconflow -m Qwen/Qwen-Image "高清插画"  # 真分辨率控制
./generate.py -p openrouter "一只赛博朋克猫"
./generate.py -p 302ai "扁平矢量海报"
./generate.py -p volcengine "中文信息图"                       # 默认 Seedream 5.0
./generate.py -p volcengine -m doubao-seedream-5-0-pro-260628 "商业海报"

# 垫图 / 图生图(五家都支持,机制不同)
./generate.py --ref /tmp/face.png "换成梵高风格"

# Seedream 原生连贯组图:一次请求返回最多 N 张
./generate.py -p volcengine --sequential --max-images 4 "四格连贯分镜"

# 147ai —— 方言随模型自动切换,无需额外配置
./generate.py -p 147ai "一只赛博朋克猫"                        # gemini-3-pro, 2K
GENIMAGE_IMAGE_SIZE=4K ./generate.py -p 147ai -r 21:9 "超宽壁纸"   # 实测 6336x2688
./generate.py -p 147ai -m gpt-image-2-high -r 1:1 "产品图"      # 2048², OpenAI 方言

# 批量 — 一行一条 prompt(空行/# 开头行跳过)
./generate.py --batch-file prompts.txt --concurrency 3 --rpm 60
```

`./generate.py --help` 看全部 flag;`./list_models.py` 遍历所有 provider 与模型。

## 安装 & 配置(uv 原生)

```bash
git clone https://github.com/TsekaLuk/generate-image.git ~/.claude/skills/generate-image
cd ~/.claude/skills/generate-image
uv sync                           # 建 .venv、装依赖 + 本包(读 uv.lock)
cp .env.example .env              # 只填你要用的 provider 的 key
```

跑图:`uv run generate-image "..."`(自动 sync)/ `uv run generate-image-models`。
顶层 `./generate.py`、`./list_models.py` 是薄启动器(把 `src/` 挂到 sys.path),依赖可导入时同样能跑。
非 uv 回退:`pip install .`。`pyproject.toml` 是唯一依赖来源,`uv.lock` 已提交锁版本。

`.env` 已被 `.gitignore`——**永远不要把 key 提交或贴进聊天**;泄露立刻吊销重发。
旧 `seedream-5-skill` 的 `~/.seedream-config.json` 仍可作为 `ARK_API_KEY` 只读后备；

### `147ai`(nn.147ai.com,站名 Nano Banana)

一个 base_url 前面挂了两套上游协议,`-m` 选的模型决定走哪条,`apply_model_dialect()`
自动切换:

| 模型前缀 | 端点 | 画幅控制 | img2img |
|---|---|---|---|
| `gemini-*`(默认) | `/v1/chat/completions` | `extra_body.google.image_config.{aspect_ratio, image_size}` | 同端点,图作 `image_url` 部件,且能定画幅 |
| `gpt-image-2-*` | `/v1/images/generations` | `size` 枚举真生效 | `/v1/images/edits` multipart |

**实测分辨率(2026-07,解码真实返回的 PNG,非文档抄写):**

| 模型 | tier | 16:9 | 1:1 | 21:9 |
|---|---|---|---|---|
| `gemini-3-pro-image-preview` | `4K` | 5504x3072(16.9MP) | 4096x4096 | 6336x2688 |
| `gemini-3-pro-image-preview` | `1K` | 1376x768 | — | — |
| `gemini-2.5-flash-image` | 1K/2K/4K **均无效** | 1344x768(1.0MP) | — | — |
| `gpt-image-2-low` | (无 tier) | 2048x1152 | 2048x2048 | — |

- **`image_size` 只在 pro 模型上生效**,flash 三档返回完全相同的 ~1MP 图。
  pro + `GENIMAGE_IMAGE_SIZE=4K` 是本 skill 分辨率天花板(16.9MP,官方 `size` 上限的 10.8 倍)。
- 画质档由模型名决定,不是 `quality` 参数:`gpt-image-2-low/-medium/-high`。
- 单价按模型差 10 倍(¥0.04~¥0.4),`--dry-run` 报准确数字。
- `n>1` 文档明说"收到但仍只出一张",多图走 `--count`。无 `seed`、无 `background`。

**⚠️ 背靠背请求会被切断连接**(实测必现):连续调用报
`[SSL: UNEXPECTED_EOF_WHILE_READING]`,冷却约 20 秒恢复,而且**这种失败照样计费**。
故本 provider 设为断连要重试(`retry_broken_transport`)+ 20 秒退避下限 + 并发 1 +
rpm 12 —— 不重试并不省钱,只是白付。gpt-image-2 线单次耗时 50~140 秒。

新配置优先写环境变量或本项目 `.env`。

## DAG 编排(`--dag-file`)—— 串行 / 并发 / 任意依赖图

依赖型 / 并行型流水线(B 用 A 的产物、同风格组图、先串后并、菱形、多父 join,**任意无环图**)
写一份任务图规格(YAML 或 JSON),引擎用标准库 `graphlib` 以最大并行度跑,并复用可靠性层。

- 每个 task:`id`、`prompt`,可选 `provider`/`model`/`ratio`/`background`/`name`。
- 建边 = `depends_on: [ids]` 与 ref `"@id"`(用该 task 产物当输入 → 隐式依赖)**取并集**;
  一个 task 写多个 `@ref` = **join**,把多张上游产物联图(多图)。
- `--on-failure skip`(默认:失败节点的后代跳过、其余照跑)或 `fail-fast`(中止未开始的)。
- 每个 task 产物 → `~/Pictures/generate-image/{name or id}.png`。

```yaml
# pipeline.yaml — A 生图;B 垫 A 重绘;C/D 从 A 分支;E 联 C+D
tasks:
  - {id: A, prompt: "黎明的灯塔，扁平矢量", ratio: "16:9"}
  - {id: B, prompt: "同场景改夜景",   refs: ["@A"]}
  - {id: C, prompt: "灯室特写",       refs: ["@A"]}
  - {id: D, prompt: "远景全貌",       refs: ["@A"]}
  - {id: E, prompt: "双联海报",       refs: ["@C", "@D"]}   # 多父 join
```

```bash
uv run generate-image --dag-file examples/bytedance-logos.yaml --concurrency 3   # 可跑示例(10 个 logo)
uv run generate-image --dag-file my-graph.json --on-failure fail-fast            # JSON 也行
```

完整可跑示例见 `examples/bytedance-logos.yaml`。`--batch-file` 就是"零边 DAG"的特例。

## Flow 编排(`--flow-file`)—— 验收、反馈与有界循环

DAG 负责并行数据依赖；Flow 负责有条件的状态转换。节点完成后返回命名 route，
例如 `accepted` / `rejected`，引擎只沿匹配的边继续。控制图允许有环，但任何有环
spec 都必须声明 `limits.max_steps`，并建议同时设置 `max_billed_calls` 与 `max_visits`。

内置节点：

- `image.describe`：读取目标参考图，反推出完整初始 prompt，并写入 Flow state。
- `image.generate`：复用现有五家生图 provider、重试与图生图实现。
- `image.review`：通过已注册的 `openai` / `openrouter` provider 调用
  OpenAI-compatible multimodal chat，按验收标准返回结构化
  `accepted`、`score`、`feedback`、`revised_prompt`；可同时传 `reference` 和
  `image` 做目标图/候选图比较。
- `prompt.refine`：把评审生成的新 prompt 写回 Flow state，本身不产生网络费用。

```bash
# 只检查图、路由与计费上限，不请求网络
uv run generate-image --flow-file examples/acceptance-loop.yaml --dry-run

# 最多两轮 generate + review；输出完整 attempt 历史
uv run generate-image --flow-file examples/acceptance-loop.yaml -n keyboard-loop
```

每次执行写入 `~/Pictures/generate-image/runs/<run-name>/`：图片位于
`<node>/attempt-NNN/image.png`，评审位于 `review/attempt-NNN/verdict.json`，根目录的
`journal.jsonl` 与 `state.json` 保存完整控制历史。已有同名 run 会拒绝覆盖。

Flow 当前刻意采用单路由控制语义；并行 fan-out / multi-parent join 继续使用 DAG。
完整配置见 [`examples/acceptance-loop.yaml`](examples/acceptance-loop.yaml)。

反推 prompt 的典型控制图是
`image.describe -> image.generate -> image.review(reference + candidate)`；评审拒绝时经
`prompt.refine` 回到 `image.generate`。目标图即使扩展名错误，也会按 PNG/JPEG 文件头
识别 MIME，避免把 JPEG 错标成 `image/png`。

## 可靠性(自动,无需手动重试)

- **计费感知重试**:`302ai` / 火山方舟成功失败都计费——429/408 直接重试(生成前被拒);
  5xx/超时**只在带幂等键时重试**(网关去重,不双扣);其余 4xx 不重试。
  `openrouter`/`siliconflow` 被拒不计费,5xx 放心重试。`volcengine` 未声明幂等语义,
  对 5xx/超时保守不重试,避免一次生成被重复计费。
- **Retry-After** 优先,否则 full-jitter 指数退避。
- **批量**:token-bucket 客户端限流 + AIMD 遇 429 自动降并发。

## 几个坑

- **比例用 `-r`,别写进 prompt**;写了会和注入的提示词打架。
- **官方 `size` 是真控**(1024×1024 / 1536×1024 / 1024×1536,经 `-r` 映射);中转是否真的兑现 `size` 因家而异。要更高分辨率用 `147ai` 的 4K 档或 `siliconflow` 的 `image_size`。想核实任意 provider 的真实行为,用探针:`uv run python -m generate_image.probe -p <provider>`(或 `generate-image-probe` 命令,联网 `uv sync` 后可用)。
- **`--ref` 各家机制不同**(OpenAI edits / chat / image_prompt / Ark Base64 `image[]`),效果会有差异。
- **Seedream 5.0 Pro** 的完整 Model ID 是 `doubao-seedream-5-0-pro-260628`;
  使用前必须在对应 `ARK_API_KEY` 所属账户开通。当前官方价为输出图 ¥0.3/张、首张输入图免费、
  后续输入图 ¥0.02/张(≤236 万像素档),以控制台最新定价为准。Pro 不接受
  `sequential_image_generation` 参数;原生连贯组图请使用默认 5.0 型号。
- **`--background transparent` 在 openai 官方 gpt-image 上受支持**,但火山方舟 Seedream 全系硬拒(脚本发请求前就拦下);走中转时以中转实测为准。
  要真透明改用**纯色 chroma key 背景 + 本地抠图**。
- **成功和失败都可能计费**(302ai / 火山方舟)——重试已内置且计费感知,别再手动盲重跑。
- 图里**别放长文字**(渲染不稳),标题后期叠。

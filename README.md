# generate-image / 生图

> 一条命令出图,**多 provider 可插拔**。默认走 **OpenAI** 官方 Images API(`gpt-image-2`),
> 一行 `-p` 切到 **302.AI / OpenRouter / SiliconFlow**。内置连接池 + 计费感知重试 + 限流 + 自适应并发。
> Saves a PNG to `~/Pictures/generate-image/`, previews inline in kitty.

<p align="center">
  <img src="docs/sample-funnel.jpg" alt="样例:漏斗压缩" width="380">
  <img src="docs/sample-layers.jpg" alt="样例:双层筛网" width="380">
</p>

> 上面两张是用本 skill 出的扁平矢量插图(`gpt-image-2`, 16:9)。

---

## 这是什么

`生图 / 画图 / 出图 / 搞张图` 的 Claude Code skill。把出图后端抽象成一张 **provider 注册表**
(`providers.py`),封装了比例控制、图生图、批量、本地保存,以及一套 **SOTA 可靠性层**
(`reliability.py`:计费感知重试 / Retry-After / token-bucket 限流 / AIMD 自适应并发 / 幂等键)。
另附一套绘本/系列插图 prompt 模板(`templates.md`)。

## Provider(`-p` / `--provider`)

| Provider | base_url | 出图端点 | 图生图 `--ref` | size 方言 | Key env |
|---|---|---|---|---|---|
| **`openai`**(默认) | api.openai.com | `/v1/images/generations` | multipart edits | `size`(1024²/1536×1024/1024×1536,真控) | `OPENAI_API_KEY` |
| `302ai` | api.302.ai | `/v1/images/generations` | multipart edits | `size` | `AI302_API_KEY` |
| `openrouter` | openrouter.ai/api | `/v1/images` | chat image_url | 无(靠 `-r`) | `OPENROUTER_API_KEY` |
| `siliconflow` | api.siliconflow.cn | `/v1/images/generations` | image_prompt | `image_size` WxH(真控) | `SILICONFLOW_API_KEY` |

`base_url` / 默认模型可用 env 覆盖(`OPENAI_BASE_URL`、`OPENROUTER_DEFAULT_MODEL`…),
不改代码就能接入其它 OpenAI 兼容 provider。比如任何支持 `gpt-image-2` 的 OpenAI 兼容中转,
只需 `OPENAI_BASE_URL=https://your-relay.example.com` + 对应 `OPENAI_API_KEY` 即可直接用默认 provider。

## 用法

```bash
# 默认 openai / gpt-image-2 / 16:9
./generate.py "夕阳下的金门大桥,油画风格"
./generate.py -r 9:16 "竖版手机壁纸"                       # 比例靠 -r,别写进 prompt

# 切 provider
./generate.py -p siliconflow -m Qwen/Qwen-Image "高清插画"  # 真分辨率控制
./generate.py -p openrouter "一只赛博朋克猫"
./generate.py -p 302ai "扁平矢量海报"

# 垫图 / 图生图(四家都支持,机制不同)
./generate.py --ref /tmp/face.png "换成梵高风格"

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
  - {id: A, prompt: "黎明的灯塔,扁平矢量", ratio: "16:9"}
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

## 可靠性(自动,无需手动重试)

- **计费感知重试**:`302ai` 成功失败都计费——429/408 直接重试(生成前被拒);
  5xx/超时**只在带幂等键时重试**(网关去重,不双扣);其余 4xx 不重试。
  `openai`/`openrouter`/`siliconflow` 被拒不计费,5xx 放心重试。
- **Retry-After** 优先,否则 full-jitter 指数退避。
- **批量**:token-bucket 客户端限流 + AIMD 遇 429 自动降并发。

## 几个坑

- **比例用 `-r`,别写进 prompt**;写了会和注入的提示词打架。
- **openai 官方 API 的 `size` 是真控**(1024×1024 / 1536×1024 / 1024×1536,经 `-r` 映射);
  没有 size 参数的 provider(openrouter)靠注入的比例提示词控。想核实任意 provider 的真实行为,
  用探针:`uv run python -m generate_image.probe -p <provider>`(或 `generate-image-probe` 命令,`uv sync` 后可用)。
- **`--ref` 各家机制不同**(OpenAI edits / chat / image_prompt),效果会有差异。
- **`--background transparent`** 在 openai 官方 gpt-image 模型上受支持;走中转时以中转实测为准
  (注册表的 `background_unsupported` 可按 provider/模型硬拒)。
- **有的 provider 成功和失败都计费**(302ai)——重试已内置且计费感知,别再手动盲重跑。
- 图里**别放长文字**(渲染不稳),标题后期叠。

# Contributing / 维护说明

本仓库是内部仓库 `ai-skills/generate-image`（GitLab，默认 provider 为公司网关
`mox`）的**公开去内网化版本**（默认 provider 换成官方 `openai`）。两边源码
基本同构，长期需要手动同步。本文档记录同步流程与两边差异点，供未来的人类
或 agent 参考。

## 两个仓库

| | 内部版 | 公开版（本仓库） |
| --- | --- | --- |
| 远程 | 内部 GitLab（私有，地址不在本文档记录） | `https://github.com/TsekaLuk/generate-image.git` |
| 本地路径 | 内部工作区路径（私有，不在本文档记录） | `~/workspace/code/personal/generate-image` |
| 默认 provider | `mox`（公司内部网关，`MOX_API_KEY`） | `openai`（`api.openai.com`，`OPENAI_API_KEY`） |
| 历史 | 完整内部提交历史 | 单一 squash 首发提交（不携带内网信息） |

> 内部远程地址、内部网关主机名、本地工作区路径均属于公司内部信息，
> 不应出现在本仓库的任何文件里。需要这些信息时，去内部版仓库自己的
> 文档或配置里查，不要复制粘贴进本仓库的提交历史。

**内部版是唯一的功能开发源头**：新 provider、新 CLI 特性、bug 修复都先在内部
版写、测、合并，再回移到公开版。不要反向在公开版单独开发新功能——那会导致
两边分叉、diff 越滚越大。

## mox → openai 的语义差异（同步时必须留意）

这两个 provider 描述的**不是同一个网关**，行为不完全相同，回移代码时不能
无脑照抄：

- `mox` 实测忽略 `size`/`quality`，固定输出 ~1254²≈1.57MP，画幅由 prompt 里
  的比例提示（`-r` 映射）决定；`openai` 官方 API 的 `size` 是真实生效的
  （`1024x1024` / `1536x1024` / `1024x1536`）。任何涉及 `OPENAI_RATIO_SIZE`
  或"实测尺寸行为"的注释/文档改动，先确认改的是哪个 provider 的真实行为，
  不要把 mox 的实测结论套到 openai 头上，反之亦然。
- 计费语义不同：`mox`/`302ai` 失败也计费（`bills_on_failure=True`，需要
  idempotency key 防止重试双花）；官方 `openai` API 失败不计费
  （`bills_on_failure=False`）。凡是改可靠性层（`reliability.py`）的重试/
  幂等逻辑，必须同时检查两边 provider 的 `bills_on_failure` 语义是否还成立。
- `background_unsupported`：`mox` 上的 `gpt-image-2` 实测硬拒绝
  `--background`（HTTP 400）；官方 API 的 `gpt-image-2/1` 支持
  `background=transparent`。这条差异已经在 `providers.py` 里体现为两个不同
  的 `background_unsupported` 集合——同步时不要把其中一边的集合复制粘贴到
  另一边。
- 内部版 `.env.example` 教用户从旧的 `AIGW_API_KEY` 改名到 `MOX_API_KEY`；
  这条迁移提示是内部历史遗留物，公开版没有、也不该有。
- 内部版还有一个组织内网关 `tds`（`requires_base_url=True`，没有可猜测的公共
  主机名）。公开版**不注册**它。`Provider.requires_base_url` 这个字段本身保留，
  两边同构；公开版没有 provider 用到它，靠 `test_provider_router.py` 里一个
  `dataclasses.replace` 出来的合成 provider 维持覆盖。

### 测试移植的三个固定改法

内部版测试大量依赖 mox 的语义，机械改 key 名会让断言悄悄失真。以下三类每次都要改：

| 内部版测试依赖 | 公开版怎么写 |
| --- | --- |
| `bills_on_failure=True` + 已知单价（`¥0.1/张`）的成本断言 | 改走 `-p 302ai`（公开版唯一同时满足这两点的 provider），并显式 `setenv AI302_API_KEY` |
| `background_unsupported` 非空（mox `gpt-image-2`） | 用 `volcengine`（Seedream 全系硬拒），或 `dataclasses.replace` 合成一个 `GUARDED` provider |
| `.env` / 环境变量泄漏 | `tests/conftest.py` 的 autouse fixture 已清空所有 provider 变量、stub 掉 `_find_dotenv` 与 `Path.home`；新测试不要再自己写一份局部清理 |

> 机械 `mox` → `openai` 全局替换会把内部网关主机名 `aigw.mox.ktvsky.com` 变成
> `aigw.openai.ktvsky.com` —— 仍然是内网派生串。替换后**务必**单独 grep 一遍
> 内网域名，不要只 grep provider 名。

## 从内部版回移改动到公开版

1. 在内部版本地路径确认改动已经过 `uv run --offline pytest -q` 验证。
2. 到公开版本地路径，手动应用等价改动（不要 `git cherry-pick`/`git pull`
   跨两个不共享历史的仓库；两边 remote 也从未 fetch 过对方）。
3. 逐文件过一遍下面的清单，把内部措辞替换成公开措辞：
   - provider 名 `mox` → `openai`；`MOX_API_KEY`/`MOX_BASE_URL`/
     `MOX_DEFAULT_MODEL` → `OPENAI_API_KEY`/`OPENAI_BASE_URL`/
     `OPENAI_DEFAULT_MODEL`。
   - 涉及 mox 实测行为的注释，按上一节的语义差异表重写，不要照搬。
   - README/SKILL.md 里如果新增了功能说明，同步补充中文对应段落（本仓库
     README 以中文为主）。
   - 新增测试如果原本 fixture 用 `MOX_API_KEY`，改成 `OPENAI_API_KEY`；
     涉及 `bills_on_failure=True` 场景的测试，改用 `302ai`（公开版里唯一
     保留失败计费语义的 provider）或 `dataclasses.replace(...)` 构造的
     synthetic provider，不要伪造一个行为对不上的 openai 测试。
4. 跑一遍内网词扫描，必须零命中（内部网关主机名、内部远程地址等具体字符串
   见内部版仓库自己的文档，不在本文件列出；扫描时把这些具体字符串换成你
   自己环境里的值）：
   ```bash
   grep -riE "mox|公司网关|公司内部" . --exclude-dir=.git --exclude-dir=.venv
   # 再单独 grep 一遍内部网关主机名 / 内部远程地址的具体字符串
   ```
5. 跑测试（offline，因为这里的网络对 PyPI 直连经常不通，走本地 uv 缓存）：
   ```bash
   uv sync --offline && uv run --offline pytest -q
   ```
   全绿再继续；出问题按上面"回移改动"的清单排查是不是漏改了 provider 语义。
6. 确认没有 `.env`、没有真实 key 混入（`git status` 检查一遍暂存区）。
7. 提交、push：
   ```bash
   git add -A && git commit -m "..."
   git push origin main   # 仅本仓库的唯一 remote
   ```
   公开版历史应保持干净、可读；不需要逐条搬运内部版的 commit 粒度。

## 安全红线

- **禁止**把内部版的 `.git`、`.env`、内部提交历史，或任何内部网关的主机名、
  远程地址、内部路径带进本仓库。`mox` 这个 provider 名本身可以出现（它只是
  一个标识符），但它背后的实际主机名/地址不可以。
- 涉及"把内网仓库发布/推送到公网"的操作，按当前 harness 的权限策略会被
  auto 模式拦截，需要用户在真实终端手动执行——这是预期行为，不要尝试绕过。
- 回移前，先用 `readlink -f` 确认两个仓库路径没有互相符号链接、没有指向
  同一份工作树，避免误操作互相覆盖或删除（历史上发生过一次，代价是一次
  完整的仓库恢复）。

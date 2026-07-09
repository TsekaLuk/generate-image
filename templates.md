# Storybook Illustration Templates

A curated set of prompt templates for generating **story-style illustration decks** — the visual language used by NotebookLM Video Overviews, children's picture books, and editorial narrative imagery.

## How to use this library

**Compose a prompt from two pieces:**

1. **Pick ONE style preset** (§ Styles below) — locks the visual language (palette, linework, medium). Reuse the same preset across the whole story deck for consistency.
2. **Pick ONE scene scaffold** (§ Scenes below) — locks the composition (shot type, framing, focus).

Then fill in `{{variables}}` with the story-specific content. Concat:

```
{{scene scaffold filled in}}
风格：{{style preset filled in}}
```

**Prompt framework used throughout** (from Nano Banana official guidance):
`Subject + Action + Setting + Style/medium + Composition + Lighting/color + Key details + Constraints(what to avoid)`

**Aspect ratio note**: pass via `-r`, don't write it into the prompt text (the `generate.py` script appends it).

---

## Styles — pick one and stick with it across all panels

### 1. `watercolor-storybook` — 经典水彩绘本

> NotebookLM "Watercolor" flavor. Soft washes, bleeding edges, hand-lettered feel. Best for gentle / heartwarming / nature stories.

```
水彩儿童绘本插画风格，手绘质感，颜料自然晕染的柔和边缘，米白色纸张纹理隐约可见，
主色调 {{暖橙 / 鸢尾蓝 / 薄荷 — 选 2-3 色}}，柔光晨雾氛围，留白大方，
轮廓线用淡棕细笔勾勒，避免数字化硬边、避免高饱和度
```

### 2. `crayon-cozy` — 蜡笔+彩铅 cozy

> The "cozy storybook" aesthetic popular on CreateVision / Pinterest. Colored-pencil strokes + subtle watercolor wash. Perfect for quiet/introspective stories.

```
蜡笔与彩色铅笔混合质感，笔触方向清晰可见，轻微水彩底色打底，
暖色调主导（奶油黄、柔粉、焦糖棕、苔藓绿），纸面颗粒感明显，
柔和漫射光，不使用渐变阴影，线条带有手绘抖动感，童书封面级别完成度
```

### 3. `ghibli-warm` — 吉卜力暖色手绘

> Studio Ghibli / Miyazaki-inspired. Rich hand-drawn detail, lush backgrounds, warm cinematic light. Best for adventure / coming-of-age / nostalgia.

```
吉卜力工作室手绘动画电影风格，精致的背景描绘，茂密的自然细节，
暖色黄昏或清晨顶光打在角色身上，柔和的空气透视，
人物造型圆润亲切，大面积手绘纹理，宫崎骏式浪漫氛围，
避免 3D 渲染感、避免过度锐利的数字线条
```

### 4. `papercraft-collage` — 立体剪纸拼贴

> NotebookLM "Paper-craft" style. Layered paper with visible edges and drop shadows — tactile, handmade feel. Best for educational / explainer content.

```
剪纸拼贴立体插画风格，每个元素都是独立的剪纸层，可见纸张边缘和细微投影，
纸张纹理清晰，颜色来自彩色卡纸（哑光质感，非印刷），
平面正视图或 3/4 视角，背景层次分明（2-3 层深度），
柔和顶光产生真实阴影，避免渐变、避免数码笔刷
```

### 5. `kawaii-pastel` — 卡哇伊粉彩

> NotebookLM "Kawaii" style. Bubble-round shapes, soft pastels, cute-core. Best for lifestyle / consumer / light-hearted topics.

```
日式卡哇伊粉彩插画风格，角色圆润 chibi 比例（头身比 1:1.5），
主色调粉嫩（奶油粉、薄荷蓝、淡黄、浅紫），极简面部表情（两个圆点眼+小嘴），
柔和无光源阴影，干净白底或单色柔和背景，腮红点缀，
整体治愈无攻击性，避免写实质感、避免暗色调
```

### 6. `flat-vector-editorial` — 扁平化编辑插画

> Clean modern vector (The Verge / Medium / Google Doodle school). Geometric shapes, limited palette, bold composition. Best for tech / concept / business narratives.

```
现代扁平化矢量插画风格，几何简化的人物和物体，无线稿描边，
色块干脆，主色调 3-4 色（互补撞色），少量细腻纹理点缀避免过于平面，
构图大胆有留白，平面正视图，柔和的几何阴影作色块叠加而非真实投影，
编辑类插画质感（Medium / Google Doodle 风），避免渐变、避免写实光影
```

---

## Scenes — pick one, fill in story content

### 7. `cover-hero` — 封面 / 主视觉（标题安全区）

- **长宽比**: `16:9` (video thumbnail) / `4:5` (book cover) / `1:1` (social)
- **模型推荐**: `Nano_Banana_Pro_4K_0`（封面值得花 0.18）

```
故事封面构图，主角 {{主角描述}} {{动作 / 情绪}}，
位于画面{{左 / 右 / 中}}下方，上方留出 30% 空白天空 / 留白区域用于承载标题，
背景是 {{地点 / 时间 / 天气}}，{{1-2 个象征性道具}}在画面中自然存在，
电影感构图，戏剧性光影，主体清晰可辨
```

**填充示例**（配 `watercolor-storybook` 风格）：

```
故事封面构图，主角一只戴红围巾的小熊背着行囊站立回望，
位于画面右下方，上方留出 30% 空白天空用于承载标题，
背景是深秋黄昏的山间小径，几片枫叶和一盏纸灯笼在画面中自然存在，
电影感构图，戏剧性光影，主体清晰可辨
风格：水彩儿童绘本插画风格，手绘质感，颜料自然晕染的柔和边缘，米白色纸张纹理隐约可见，主色调暖橙、鸢尾蓝、焦糖棕，柔光黄昏氛围，留白大方，轮廓线用淡棕细笔勾勒
```

### 8. `establishing-wide` — 场景建立大全景

> Use at the opening of a scene, or when introducing a new location. Rich background, small subject.

- **长宽比**: `16:9` / `21:9`
- **模型推荐**: `Nano_Banana_Pro_2K_0`（日常够用）/ `4K_0`（背景细节多时）

```
场景建立大全景，{{主角}}在画面{{位置}}以小尺寸出现（画幅的 1/6 左右），
环境是 {{详细地点描述 + 时间 + 天气}}，背景占据画面主导（70%+），
{{3-5 个环境细节}}丰富构图层次，画面有明确的远中近三层景深，
电影广角镜头感，主角的存在感通过姿态而非大小传达
```

### 9. `character-closeup` — 角色情绪特写

> Emotional beats. Use when the story needs a feeling, not information.

- **长宽比**: `4:5` / `3:4` / `1:1`
- **模型推荐**: `Nano_Banana_Pro_2K_0`

```
{{主角}}的半身 / 胸部以上特写，{{具体表情：眼神 + 嘴角 + 眉毛}}，
{{一个与情绪呼应的微小动作：手部 / 头部倾斜}}，
浅景深背景柔焦，只保留 {{1 个象征性元素}} 依稀可辨，
{{光源方向}}侧光勾勒面部轮廓，情绪是 {{一句话情绪锚点}}，
构图遵循三分法，主角眼睛位于上三分线
```

### 10. `introspective-mood` — 孤独 / 内心戏 / 氛围片

> The "quiet moment" shot. Character alone in a large, atmospheric space. High mood, low plot.

- **长宽比**: `9:16`（手机沉浸式）/ `16:9`
- **模型推荐**: `Nano_Banana_Pro_4K_0`（氛围片细节加分）

```
{{主角}}独自 {{动作：坐/站/望/走}}，在画面{{位置，通常偏下或偏侧}}，
处于极其空旷的 {{大场景}}中，周围大面积留白或单一氛围色，
{{一个抒情元素：远处的光点 / 飘落的物 / 窗外的景}}作为视觉呼应，
整体气氛 {{孤独 / 平静 / 期待 / 释然}}，
低对比度柔光，冷暖色调仅用一种，画面几乎没有喧嚣元素
```

---

## Character consistency across a deck（多张图同一角色怎么保持一致）

**核心原则**：固化身份，变化表演。

**每次 prompt 都要固化的身份锁**（写成一句，粘贴到每张图的"主角描述"位置）：
- 物种 / 性别 / 年龄
- 发型 / 发色 / 眼睛颜色
- **1 个绝对不变的标志物**（红围巾 / 挂件 / 某颜色外套）——这个是最关键的识别锚
- 体型比例（高瘦 / 圆润 / chibi 比例具体到头身比）

**每次 prompt 可以变化的**：
- 表情 / 姿势
- 视角（正面/侧面/背面/俯仰）
- 服装细节（但标志物必须保留）
- 光线 / 环境

**示例身份锁**：
```
一只约 5 岁形象的棕色小熊，圆润比例（头身比 1:2），
总是戴一条磨损的深红色羊毛围巾（绝对不变），
琥珀色圆眼睛，小巧的黑色鼻头
```

把这段粘到每张图的 `{{主角描述}}` 位置，角色一致性可以做到 80% 以上。剩下 20% 的漂移通过**上一张图作为 `--ref` 参考图**来进一步锁定。

**工作流建议**：
1. 先生第一张（通常是封面或角色立绘），作为后续所有图的 reference anchor
2. 从第二张开始，用 `--ref <第一张路径>` 传入
3. 每张图都在 prompt 开头重复完整的身份锁文字
4. 发现漂移时，用最近一张效果最好的图作为新 anchor，重启 reference chain

---

## Quick pairing guide（风格 × 场景 的经典搭配）

| 故事气质 | 推荐风格 | 推荐场景组合 |
|---|---|---|
| 温暖治愈童书 | `watercolor-storybook` | cover → establishing → closeup → introspective |
| 安静沉思文艺 | `crayon-cozy` | introspective × 3 + closeup |
| 冒险成长史诗 | `ghibli-warm` | cover → establishing(×2) → closeup → introspective |
| 知识科普动画 | `papercraft-collage` | cover → establishing → closeup (concept) |
| 生活方式 / 品牌 | `kawaii-pastel` | cover → closeup(×3) |
| 科技 / 商业叙事 | `flat-vector-editorial` | cover → establishing (metaphor) → closeup (data) |

---

## Known limits

- **文字渲染**：任何风格里模型都搞不定长英文 / 中文段落，标题建议后期 Photoshop 叠。如果必须内嵌，用短单词（< 4 词），接受 70% 成功率。
- **多角色同框**：超过 2 个主要角色时一致性会明显下降，尽量拆成多张单人图再后期合成。
- **精确比例**：用 `{{头身比}}`、`{{画幅占比 N/M}}` 这种明确指示比形容词更稳。

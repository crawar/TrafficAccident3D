# 事故智脑

六支队交通事故人工智能系统。上传一张事故现场航拍图后，可自动识别车辆和道路，人工校对后生成可交互的三维现场 HTML。

## 功能

- **识别**：用 YOLO 从航拍图中检出车辆（支持旋转框）。
- **校对编辑**：在「结果确认与编辑」中调整车辆、道路线、标记物（锥桶、行人、导向牌等），并填写简要案情。
- **运动路径**：为车辆设置行驶路径和速度，生成后可在三维场景中播放。
- **三维现场**：导出离线 HTML，支持测量距离、车辆编号、责任显示、事故报告。
- **AI 分析（可选）**：配置 DeepSeek 密钥后，可按交警专家角色生成责任分析与报告发言。仓库和安装包会带上已精炼的口径手册与案件结果；不包含 API 密钥。
- **研判分析**：主页上传事故台账 Excel，按列映射离线汇总成 Word「事故分析报告」，不调用 AI。

## 使用方法

### 1. 环境

需要已安装 [Miniconda](https://docs.conda.io/en/latest/miniconda.html) 或 Anaconda（Windows）。

在项目根目录双击 `create.bat`，会在本项目内创建 `env` 并安装依赖。完成后双击 `start.bat` 启动。

### 2. 权重文件（需手动下载）

仓库不包含权重。请用浏览器下载后，按下面的目录原样放置（不要改文件名）。

**YOLO（车辆识别）** — 放到 `downloads/` 目录：

| 文件 | 下载地址 |
|------|----------|
| `yolo11x.pt` | https://github.com/ultralytics/assets/releases/download/v8.3.0/yolo11x.pt |
| `yolo11x-obb.pt` | https://github.com/ultralytics/assets/releases/download/v8.3.0/yolo11x-obb.pt |

发布页：https://github.com/ultralytics/assets/releases/tag/v8.3.0

**中文 NER（离线脱敏人名/地址）** — 放到 `downloads/chinese_ner/` 目录：

模型页：https://huggingface.co/uer/roberta-base-finetuned-cluener2020-chinese

需要这 5 个文件（点文件名进入后点 Download）：

| 文件 | 下载地址 |
|------|----------|
| `config.json` | https://huggingface.co/uer/roberta-base-finetuned-cluener2020-chinese/resolve/main/config.json |
| `pytorch_model.bin` | https://huggingface.co/uer/roberta-base-finetuned-cluener2020-chinese/resolve/main/pytorch_model.bin |
| `vocab.txt` | https://huggingface.co/uer/roberta-base-finetuned-cluener2020-chinese/resolve/main/vocab.txt |
| `tokenizer_config.json` | https://huggingface.co/uer/roberta-base-finetuned-cluener2020-chinese/resolve/main/tokenizer_config.json |
| `special_tokens_map.json` | https://huggingface.co/uer/roberta-base-finetuned-cluener2020-chinese/resolve/main/special_tokens_map.json |

不要下载 `tf_model.h5`、`flax_model.msgpack`。只做数字、字母、身份证或手机号脱敏时可以不放 NER 权重。

### 3. 日常操作

1. 点击 **事故研讨**，选择现场航拍图。
2. 等待识别完成后，进入 **结果确认与编辑**。
3. 分别校对 **车辆**、**道路线**（这两项必填），按需要补充标记物、运动路径和案情。
4. 点击 **识别确认**，生成三维 HTML（保存在 `history/`）。
5. 用浏览器打开生成的 HTML，可测量、播放运动、查看责任和报告。

主页 **研判分析** 可选择事故台账 Excel（`.xlsx` / `.xls`），映射道路、类型、时间等列后离线生成 Word 报告，与所选 Excel 保存在同一文件夹。不需要 API 密钥。

系统设置里可切换识别模型、配置 AI、专家角色、测量端口和动画速度。

### 4. AI（可选）

复制 `config/ai_settings.example.json` 为 `config/ai_settings.json`，在软件「系统设置 → AI连接」中填入自己的 API 密钥。不要把带密钥的文件提交到 Git。

未配置密钥时，识别、校对和三维建模仍可正常使用，只是不会调用 AI 分析。

### 5. 打包（可选）

环境就绪后可运行 `build.bat`，产物在 `release/TrafficAccident3D/`。打包时会清空 API 密钥，但会带上设置文件、YOLO 权重，以及已精炼的口径手册和案件结果。

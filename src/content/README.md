# 文章编写方法

文章和配套源码统一放在 `src/content`：

```text
src/content/
├── articles/
│   └── my-app.md
└── sources/
    └── my-app/
        ├── app/
        ├── ros2/
        └── can-gateway/
```

文章文件名就是网址中的 slug。上例发布后的正文地址为：

```text
/app-lab/my-app/
```

源码文件会自动出现在文章左侧的“配套源码”中。点击文件名进入源码阅读页，不需要手工
创建源码页面。文本文件会显示语法高亮；wheel 等二进制文件会显示“无法阅读”和下载
按钮，原文件仍会完整保存在 GitHub 仓库中。

## 第一步：创建文章

在 `src/content/articles` 新建 Markdown 文件。普通文章使用：

```yaml
---
title: "文章标题"
description: "一句话说明读者完成后能得到什么。"
section: "embedded-hardware"
pubDate: "2026-08-30"
updatedDate: "2026-08-30"
sourceDir: "my-article"
---
```

App Lab 教程使用：

```yaml
---
title: "my-app：教程标题"
description: "一句话说明这个 App 解决的问题。"
section: "app-lab"
appId: "my-app"
order: 4
status: "verified"
pubDate: "2026-08-30"
updatedDate: "2026-08-30"
verifiedDate: "2026-08-30"
environment:
  - "Arduino VENTUNO Q"
capabilities:
  - "Custom Brick"
sourceDir: "my-app"
---
```

`sourceDir` 必须与 `src/content/sources` 下的目录名一致。文章没有程序源码时可以省略；
只要正文展示了实现代码，就必须提供对应源码目录。

## 第二步：放入源码

在 `src/content/sources/<sourceDir>` 中保存教程实际使用的完整源码，并保留项目中的相对
目录。推荐使用以下一级目录：

| 目录 | 内容 |
| --- | --- |
| `app/` | Arduino App、Brick、Python 和 Sketch |
| `ros2/` | 原生 ROS 2 包 |
| `can-gateway/` | Linux SocketCAN 网关 |

例如：

```text
src/content/sources/my-app/
├── app/
│   ├── app.yaml
│   ├── python/main.py
│   └── sketch/sketch.ino
└── ros2/
    ├── package.xml
    └── my_package/node.py
```

源码必须满足以下要求：

- 与文章中的命令和接口一致；
- 保存完整可运行文件，不只保存片段；
- 项目运行必需的 `.whl` 等二进制依赖也要保存，不能只写文件名或下载地址；
- 不保存 `.venv`、`build`、`install`、`.cache`、`__pycache__` 和日志；
- 令牌写成 `<随机令牌>`，不能提交真实令牌、密码、私钥或设备凭据；
- 教程升级接口后，同时更新源码、正文、`updatedDate` 和验证结果。

## 第三步：编写正文

正文只记录读者需要执行的最终方法，推荐顺序如下：

1. 实现结果；
2. 硬件和软件前提；
3. 文件目录；
4. 接口或通信协议；
5. 关键代码说明；
6. 构建与启动命令；
7. 手动验证方法；
8. 正常输出和常见失败原因；
9. 实测结论。

文章中的代码块用于解释关键部分，完整文件放在配套源码中。例如：

````markdown
`python/main.py` 创建一个电机对象：

```python
motor = ZdtX57SCan(motor_id=1)
```
````

不要写开发日志、尝试过程或无法复现的推测。命令要注明在哪个目录和终端执行，验证步骤
要给出读者可以对照的正常结果。

代码块必须在开头标注语言，博客会使用 Shiki 自动显示语法颜色。常用标记包括
`python`、`cpp`、`yaml`、`json`、`bash`、`text` 和 `markdown`。无法确定语言或只是
终端输出时使用 `text`，不要留空。

## 第四步：选择板块

| `section` | 页面板块 |
| --- | --- |
| `app-lab` | App Lab |
| `bricks` | Custom Bricks |
| `embedded-hardware` | 嵌入式与硬件 |
| `site-notices` | 博客公告 |

板块名称、说明、颜色和顺序集中定义在 `src/articleSections.ts`。增加新板块时，先修改该
文件，再在文章 frontmatter 中填写新的 `section` ID。

## 第五步：本地检查

在博客根目录执行：

```bash
npm run build
```

构建前会自动执行 `npm run validate:content`。只要实现代码缺少配套源码，或者源码目录含有
真实令牌、密钥、缓存和构建产物，构建就会停止并给出具体文件名。

构建成功后，需要检查：

- 正文页面可以打开；
- 左侧源码文件数量正确；
- 每个源码链接都能进入阅读页；
- 页面中没有真实令牌、密码或私钥；
- 文章卡片出现在正确板块。

需要预览时使用后台开发服务器：

```bash
npx astro dev --background
npx astro dev status
npx astro dev stop
```

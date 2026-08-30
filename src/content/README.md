# 文章编写说明

所有文章统一放在：

```text
src/content/articles/
```

文件名就是文章 slug，例如：

```text
src/content/articles/my-new-tutorial.md
```

## 通用文章模板

```yaml
---
title: "文章标题"
description: "一句话说明文章解决的问题。"
section: "embedded-hardware"
pubDate: "2026-08-30"
updatedDate: "2026-08-30"
---
```

## App Lab 教程模板

```yaml
---
title: "App 标题"
description: "一句话说明 App 实现的能力。"
section: "app-lab"
appId: "my-app-id"
order: 2
status: "verified"
pubDate: "2026-08-30"
updatedDate: "2026-08-30"
verifiedDate: "2026-08-30"
environment:
  - "Arduino VENTUNO Q"
capabilities:
  - "Custom Brick"
---
```

## 当前板块 ID

| section | 页面板块 |
| --- | --- |
| `app-lab` | App Lab |
| `embedded-hardware` | 嵌入式与硬件 |
| `site-notices` | 博客公告 |

板块的名称、说明、颜色和顺序集中定义在：

```text
src/articleSections.ts
```

增加新板块时，先在该文件中增加板块配置，再在文章 frontmatter 中填写对应的
`section` ID。

// 本文件由 tools/export_dsh_tools.py 自动生成，请勿手工编辑。
// 数据源：mcp_server.py 的 TOOLS。

export const ZJU_TOOLS = [
  {
    "name": "zju_parse_url",
    "description": "解析浙大智云课堂 (classroom.zju.edu.cn) 回放链接，提取 sub_id、course_id 与 tenant_code。",
    "parameters": {
      "url": {
        "description": "智云课堂回放 URL（例如 https://classroom.zju.edu.cn/livingroom?course_id=...&sub_id=...）或纯 sub_id 数字",
        "type": "string",
        "required": true
      }
    }
  },
  {
    "name": "zju_fetch_transcript",
    "description": "抓取智云课堂某节课的语音识别字幕（公开接口，无需登录）。默认 per_minute 带时间戳；长课用 chunked；同一节课只抓一次，per_segment 仅在确实需要秒级时间戳时用。",
    "parameters": {
      "url_or_sub_id": {
        "description": "回放 URL 或 sub_id",
        "type": "string",
        "required": true
      },
      "tenant_code": {
        "description": "租户代码，默认为 112 (浙大)",
        "default": "112",
        "type": "string"
      },
      "view_format": {
        "description": "返回视图格式：'per_minute'（推荐：按分钟整合，带 [时:分] 时间戳）、'per_segment'（逐句带秒级时间戳）、'chunked'（按约 11k 字符自动分块，便于长课分批总结）、'json'（原始数据段）",
        "default": "per_minute",
        "type": "string",
        "enum": [
          "per_minute",
          "per_segment",
          "chunked",
          "json"
        ]
      },
      "start_minute": {
        "description": "起始分钟（可选，例如只分析第 30 分钟后的内容）",
        "type": "integer"
      },
      "end_minute": {
        "description": "结束分钟（可选，例如分析到第 60 分钟为止）",
        "type": "integer"
      },
      "max_chars": {
        "description": "单次返回的字符上限（默认 60000）。超出会截断并在末尾标注，长课程建议改用 view_format=chunked",
        "default": 60000,
        "type": "integer"
      }
    }
  },
  {
    "name": "zju_fetch_slides",
    "description": "（可选投影模块）抓取智云课堂投影 PPT 截图清单。search-ppt 返回的是投影截图，不是文字层/OCR；download=true 时下载截图并合成 PDF（省略时跟随 enableSlides / embedSlideImages，即 ZJU_ENABLE_SLIDES / ZJU_EMBED_SLIDES）。需要登录态（Cookie 含 _token，由服务端本地解析，不接受也不回显 Cookie）。抓不到时返回诊断，可降级为纯字幕总结。dsh 的 enableSlides 关闭时本工具不注册。",
    "parameters": {
      "url_or_sub_id": {
        "description": "回放 URL（通常含 course_id）或 sub_id",
        "type": "string",
        "required": true
      },
      "course_id": {
        "description": "课程 ID；从完整回放 URL 自动解析。只输入纯 sub_id 时必须显式提供，否则接口可能返回空列表",
        "type": "string"
      },
      "tenant_code": {
        "description": "租户代码，默认为 112",
        "default": "112",
        "type": "string"
      },
      "download": {
        "description": "是否下载截图到工作区并合成 PDF。省略时跟随插件设置（dsh 的 embedSlideImages / 环境变量 ZJU_EMBED_SLIDES，默认关闭）；显式传 true/false 可覆盖。一节 1 小时的课通常有几十到几百张截图",
        "type": "boolean"
      },
      "output_dir": {
        "description": "截图与 PDF 的输出目录，相对当前工作区（默认 ppt-assets/<sub_id>）；必须在工作区内",
        "type": "string"
      },
      "dedup": {
        "description": "是否折叠连续字节完全相同的截图（默认 true，只影响 PDF 页数，下载的原图都会保留）",
        "default": true,
        "type": "boolean"
      }
    }
  },
  {
    "name": "zju_extract_courseware",
    "description": "从本地上传的课件（PPTX, DOCX, TXT, MD, CSV, JSON, PDF）中提取纯文本，用于注入 Agent 上下文以校准专业术语、公式与章节结构。只接受课件格式；出于隐私保护会拒绝凭据文件、浏览器数据与密钥材料。",
    "parameters": {
      "file_path": {
        "description": "课件文件的绝对路径或相对路径",
        "type": "string",
        "required": true
      },
      "max_chars": {
        "description": "最多提取字符数（默认 10000 字符）",
        "default": 10000,
        "type": "integer"
      }
    }
  },
  {
    "name": "zju_get_video_url",
    "description": "解析回放视频的 MP4 直链（本地下载或 Whisper 重识别）。需要登录态；服务端自动使用缓存 / ZJU_COOKIE / 本机 Edge，不接受也不回显 Cookie。",
    "parameters": {
      "url_or_sub_id": {
        "description": "回放 URL 或 sub_id",
        "type": "string",
        "required": true
      },
      "course_id": {
        "description": "课程 ID（可选，若从完整 URL 解析则自动包含）",
        "type": "string"
      },
      "tenant_code": {
        "description": "租户代码，默认为 112",
        "default": "112",
        "type": "string"
      }
    }
  },
  {
    "name": "zju_check_note",
    "description": "检查/修正已有讲义 Markdown 的公式与渲染规范（静态、不联网）。write_note 已自动检查，通常无需重复调用；只有手工改过文件时才用它修复。fix=true 自动修正机械问题并先备份；报告按问题类型聚合。pdf=true 时检查后重新排版一份同名 PDF。",
    "parameters": {
      "file_path": {
        "description": "讲义 Markdown 文件的绝对路径，或相对当前工作区的路径",
        "type": "string",
        "required": true
      },
      "fix": {
        "description": "是否自动修正可机械修复的问题并回写文件（默认 false，只检查）",
        "default": false,
        "type": "boolean"
      },
      "max_samples": {
        "description": "每类问题最多列出几个行号示例（默认 3，0 表示只报数量）",
        "default": 3,
        "type": "integer"
      },
      "pdf": {
        "description": "检查后是否重新排版同名 PDF（默认 false；write_note 已自动排版）",
        "type": "boolean"
      }
    }
  },
  {
    "name": "zju_write_note",
    "description": "写入讲义 Markdown：自动命名（知识总结-<日期>-<课程>-<主题>）、默认拒绝静默覆盖、写前修正公式、写后返回规范检查，并按设置自动排版同名 PDF——写文件、检查、出 PDF 一次完成。只写工作区内的 .md 文件。",
    "parameters": {
      "sub_id": {
        "description": "课程回放的 sub_id，用于追溯（不传 name 时也参与文件名）",
        "type": "string",
        "required": true
      },
      "content": {
        "description": "讲义 Markdown 全文",
        "type": "string",
        "required": true
      },
      "name": {
        "description": "讲义文件名（可省略 .md），由你按上课时间与本节内容命名，推荐 知识总结-<上课日期 YYYY-MM-DD>-<课程简称>-<本节主题>；拿不到上课日期时省略日期段，不要用当天日期顶替",
        "type": "string"
      },
      "slug": {
        "description": "课程简称（可选，仅在不传 name 时用于文件名）",
        "type": "string"
      },
      "directory": {
        "description": "工作区内的子目录（可选，例如 notes；不允许跳出工作区）",
        "type": "string"
      },
      "overwrite": {
        "description": "同名文件已存在时是否覆盖（默认 false，返回 exists 让人决定）",
        "default": false,
        "type": "boolean"
      },
      "fix": {
        "description": "写入前是否自动修正可机械修复的问题（默认 true）",
        "default": true,
        "type": "boolean"
      },
      "max_samples": {
        "description": "检查报告中每类问题最多列出几个行号示例（默认 3）",
        "default": 3,
        "type": "integer"
      },
      "pdf": {
        "description": "写入后是否排版同名 PDF（默认跟随插件设置 renderPdf；显式 true/false 可覆盖）",
        "type": "boolean"
      }
    }
  },
  {
    "name": "zju_read_browser_cookie",
    "description": "读取本机 Edge 的 classroom.zju.edu.cn 登录态（含父域 .zju.edu.cn 的 _token）到服务端内存；只返回名称与长度，绝不回显明文，无参数。",
    "parameters": {}
  },
  {
    "name": "zju_build_study_notes",
    "description": "把讲义变成 scholia 填空式学习笔记（Typst → PDF）。mode=draft 生成填空底稿（你补内容）；mode=compile 编译成 out.pdf + 逐页 PNG，并报告编译错误、方框预算与改不动的数学。需要本机 Typst（≥0.13）。只写工作区内的文件。",
    "parameters": {
      "mode": {
        "description": "draft=讲义转填空底稿（只搬运与改公式，不做内容判断）；compile=底稿转 Typst 并编译成 PDF",
        "default": "draft",
        "type": "string",
        "enum": [
          "draft",
          "compile"
        ]
      },
      "note_path": {
        "description": "讲义 Markdown 的路径（mode=draft 必填）",
        "type": "string"
      },
      "draft_path": {
        "description": "填空底稿 Markdown 的路径（mode=compile 必填）",
        "type": "string"
      },
      "output_dir": {
        "description": "输出目录，相对当前工作区（默认与源文件同目录；源文件在工作区外时写到工作区的 notes/ 下）",
        "type": "string"
      },
      "title": {
        "description": "封面标题（mode=draft；默认取讲义的第一个一级标题）",
        "type": "string"
      },
      "subtitle": {
        "description": "封面副标题（mode=draft，可选）",
        "type": "string"
      },
      "author": {
        "description": "封面作者（mode=draft，可选）",
        "type": "string"
      },
      "date": {
        "description": "封面日期（mode=draft，可选，例如 2026-11-02）",
        "type": "string"
      },
      "kicker": {
        "description": "封面上方的小字行（mode=draft，可选，例如课程代码）",
        "type": "string"
      },
      "theme": {
        "description": "配色主题（mode=compile，默认 light 淡彩极简）",
        "default": "light",
        "type": "string",
        "enum": [
          "light",
          "dark"
        ]
      },
      "make_png": {
        "description": "是否同时导出逐页 PNG（mode=compile，默认 true）。knot 的内容块数量错位不会报错，只能靠看图发现，所以建议保持开启",
        "default": true,
        "type": "boolean"
      },
      "pages": {
        "description": "只导出指定页的 PNG，例如 1-3（mode=compile，可选）",
        "type": "string"
      }
    }
  }
];

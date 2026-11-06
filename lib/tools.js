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
    "description": "抓取智云课堂某节课的语音识别字幕。先匿名；401/403 时自动用本机登录态重试一次。登录态只能来自本机 Edge 或 ZJU_COOKIE_FILE，不要传 Cookie。默认 per_minute 带时间戳；长课用 chunked；同一节课只抓一次，per_segment 仅在确实需要秒级时间戳时用。",
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
    "name": "zju_login",
    "description": "打开一个独立的浏览器登录窗口完成浙大登录（不接收密码，也不接收 Cookie）。用户在该窗口里正常登录后，窗口自动关闭，登录态安全保存在本机，后续字幕与投影自动复用。字幕/投影 401/403、ABE 导致 Edge Cookie 读不了、用户说「登录智云课堂」时调用。clear=true 清除本机登录态与独立登录窗口配置。",
    "parameters": {
      "url": {
        "description": "登录后要打开的课堂链接（可选，仅接受 https 的 *.zju.edu.cn；建议传用户给的这节课链接）",
        "type": "string"
      },
      "timeout_seconds": {
        "description": "等待用户完成登录的最长秒数（默认 300，范围 30–540）",
        "default": 300,
        "type": "integer"
      },
      "clear": {
        "description": "只清除本机保存的登录态与独立登录窗口配置，不打开窗口（默认 false）",
        "default": false,
        "type": "boolean"
      }
    }
  },
  {
    "name": "zju_read_browser_cookie",
    "description": "读取本机 Edge 的 classroom.zju.edu.cn 登录态（含父域 .zju.edu.cn 的 _token）到服务端内存；只返回名称与长度，绝不回显明文，无参数。Edge 启用 ABE 时会失败；这种情况改用 zju_login。",
    "parameters": {}
  },
  {
    "name": "zju_build_study_notes",
    "description": "把讲义变成 scholia 填空式学习笔记（Typst → PDF）。mode=draft 生成填空底稿（你补内容）；mode=patch 用 edits 一次写回多处挖空/标记；mode=compile 编译成 out.pdf + 逐页 PNG，并报告编译错误、方框预算与改不动的数学。需要本机 Typst（≥0.13）。只写工作区内的文件。",
    "parameters": {
      "mode": {
        "description": "draft=讲义转填空底稿（只搬运与改公式，不做内容判断）；patch=按 edits 一次写回底稿（批量挖空，省掉十几次单条编辑）；compile=底稿转 Typst 并编译成 PDF",
        "default": "draft",
        "type": "string",
        "enum": [
          "draft",
          "patch",
          "compile"
        ]
      },
      "edits": {
        "description": "mode=patch 的修改列表：每项 {old, new}，old 必须在底稿里恰好出现一次（重复时加长上下文，或加 all=true 全部替换）。一次最多 80 条",
        "type": "array",
        "items": {
          "type": "object",
          "properties": {
            "old": {
              "description": "原文（精确匹配，含标点）",
              "type": "string"
            },
            "new": {
              "description": "替换成的新文本",
              "type": "string"
            },
            "all": {
              "description": "原文出现多次时是否全部替换（默认 false）",
              "type": "boolean"
            }
          },
          "additionalProperties": false
        }
      },
      "note_path": {
        "description": "讲义 Markdown 的路径（mode=draft 必填）",
        "type": "string"
      },
      "draft_path": {
        "description": "填空底稿 Markdown 的路径（mode=patch / compile 必填）",
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
  },
  {
    "name": "zju_doctor",
    "description": "检查本机依赖并给出可执行结论：Python、Typst（版本 / 路径 / 来源 / 是否满足 ≥0.13）、随包中文字体与离线 Typst 包、缓存目录、登录窗口是否可用、本机是否保存了登录态；login=true 时额外验证登录态是否真的可用。install=true 时下载并校验安装 Typst（SHA256 固定，仅官方 Release；可用 ZJU_TYPST_AUTO_INSTALL=0 关闭自动安装）。PDF 失败或用户问「为什么没有 PDF」时先跑它；没有任何输出时先跑它，再调用一次 zju_login。",
    "parameters": {
      "install": {
        "description": "缺少 Typst 时是否立即下载安装（默认否；安装约 20 MB）",
        "default": false,
        "type": "boolean"
      },
      "login": {
        "description": "是否读取本机登录态检查可用性（默认否；不会回显凭据）",
        "default": false,
        "type": "boolean"
      }
    }
  }
];

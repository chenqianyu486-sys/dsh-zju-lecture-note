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
    "description": "抓取智云课堂某节课的语音识别字幕。该接口为浙大公开接口，无需登录或 Cookie 即可获取整节课的语音识别文本。支持按分钟/秒切片、分块输出以及字符上限截断。",
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
    "description": "抓取智云课堂该节课投影现场的 PPT 文字层与 OCR 记录。需要登录态：服务端会依次尝试内存缓存、ZJU_COOKIE 环境变量、ZJU_COOKIE_FILE 与本机 Edge；本工具不接受也不回显 Cookie。抓不到时会返回空提示，流水线可降级为纯字幕总结。",
    "parameters": {
      "url_or_sub_id": {
        "description": "回放 URL 或 sub_id",
        "type": "string",
        "required": true
      },
      "tenant_code": {
        "description": "租户代码，默认为 112",
        "default": "112",
        "type": "string"
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
    "description": "解析回放视频的 MP4 直链（用于本地下载或 Whisper 增强重识别）。需要有效登录态；服务端自动使用缓存的登录态 / ZJU_COOKIE / 本机 Edge，本工具不接受也不回显 Cookie。",
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
    "description": "检查已生成的讲义 Markdown 是否符合公式书写规范、能否正常渲染。静态检查，不联网：捕获表格列被裸竖线截断、行内公式未闭合、块级公式未独立成行、\\frac 缺花括号、单行 <details> 等会破坏渲染的问题。传 fix=true 时会先自动修正可机械修复的问题（单行 $$ 块、\\dfrac、\\frac 缺花括号、表格公式内的裸竖线、单行 <details>）并回写文件，再报告剩余问题。回写前会先把原文件备份成 <文件名>.bak（原子写，代码块内的示例不会被改写）。建议在写完讲义后、交付给用户前调用一次。",
    "parameters": {
      "file_path": {
        "description": "讲义 Markdown 文件的绝对路径或相对路径",
        "type": "string",
        "required": true
      },
      "fix": {
        "description": "是否自动修正可机械修复的问题并回写文件（默认 false，只检查）",
        "default": false,
        "type": "boolean"
      }
    }
  },
  {
    "name": "zju_read_browser_cookie",
    "description": "从本机 Microsoft Edge 读取已登录的 classroom.zju.edu.cn 登录态，并缓存在 MCP 服务端内存中供其他工具使用。只返回 Cookie 名称与长度，绝不回显明文；本工具没有任何参数。注意：Edge 正在运行时会锁住 Cookie 数据库；若本机 Edge 启用了应用绑定加密（ABE），退出 Edge 也无法在本地解密，应改用 ZJU_COOKIE_FILE 环境变量（不要粘贴到对话里）。",
    "parameters": {}
  }
];

# 投影抓取模块（可选附录）

> 本附录由 dsh 插件在 **`enableSlides`（启用 PPT 投影抓取）** 为 `true` 时追加到 Skill 中。
> 关闭时 `zju_fetch_slides` 不会被注册，也不应尝试读取登录态或下载截图。
> 字幕主链路（`zju_fetch_transcript` + `zju_extract_courseware`）不需要本附录。

## 1. 能力与边界

`zju_fetch_slides` 抓取智云课堂该节课的投影 PPT **截图清单**。`search-ppt` 接口返回的是
投影画面截图（`pptimgurl`），**不是文字层，也不提供 OCR**。需要阅读幻灯片内容时：

- 设置 `download=true` 下载截图并合成 PDF，交给支持视觉的模型查看；
- 宿主/模型不能看图时，只把截图当作索引，**不要臆造幻灯片文字**；
- 需要幻灯片原文时，优先请用户提供原始 `.pptx`，改用 `zju_extract_courseware`。

## 2. 调用方式

1. 优先把**完整回放 URL** 直接传给 `zju_fetch_slides`（它会自动解析 `sub_id` / `course_id`）；
   只有手里是纯 `sub_id` 时，才用 `zju_parse_url` 补一次 `course_id`。
2. 再调用：

   ```
   zju_fetch_slides(
       url_or_sub_id="<完整回放 URL>",
       course_id="<course_id>",
       download=true,
   )
   ```

   - 只传纯 `sub_id` 时**必须同时传 `course_id`**（完整回放 URL 会自动解析）；
   - `output_dir` 默认 `ppt-assets/<sub_id>/`，必须位于当前工作区内；
   - `dedup=true`（默认）只折叠**连续字节完全相同**的截图，只影响 PDF 页数，下载的原图都保留。

## 3. 下载与输出

`download=true` 时：

- 截图存到工作区 `ppt-assets/<sub_id>/images/slide-XXXX.jpg`（JPEG 原样写入）；
- 合成 `PPT-<sub_id>.pdf`；
- 返回里给出截图目录、PDF 路径，以及每页的**工作区相对路径**与引用示例。

整节课的截图可能有几十到几百张，下载可能需要数分钟。**整节课只下载一次**，不要循环重复下载。
`zju_fetch_slides` 在 dsh 里单独使用 600 秒超时，其他工具仍使用插件配置的超时。

## 4. 截图入讲义

开关：讲义插图模式（`embedSlideImages`，默认 `false`）。
开启后，从下载结果里挑 **3–8 张**最有讲解价值的页（定义、示意图、公式推导、例题），
在对应小节插入 Markdown 图片。路径按**讲义所在目录**写：

- 讲义在工作区根目录：`![第 12 页](ppt-assets/1988057/images/slide-0012.jpg)`
- 讲义在 `notes/`：`![第 12 页](../ppt-assets/1988057/images/slide-0012.jpg)`

如果模型不能查看图片：**不要臆造截图内容**；在讲义末尾加「课堂投影截图索引」，
列出页码与相对路径，正文仍以字幕与本地课件为准。

成本与质量：

- 只嵌入 3–8 张，不要把全部截图的二进制或整份 PDF 塞进上下文；
- 图片必须有正文解释（图注或一句话说明），不能只堆图；
- `zju_check_note` 不检查图片路径是否存在，写完后自己确认引用的文件确实在 `ppt-assets/` 下；
- 相对路径只在工作区内有效；要离线分享或换机器，直接发 `PPT-<sub_id>.pdf`。

讲义插图模式关闭时：不要主动下载或插入截图；用户明确要求画面时，
可以按需调用 `download=true`，并在文末放截图索引。

## 5. 登录态与隐私

投影接口需要登录态，且 Cookie 中必须包含 `_token`：

- 服务端自动尝试：内存缓存 → `ZJU_COOKIE` 环境变量 → `ZJU_COOKIE_FILE` → 本机 Edge；
- 从 Cookie 的父域 `.zju.edu.cn` 会话中解析 `_token`，再加 `Authorization: Bearer`；
- 若本机 Edge 正在运行，Cookie 数据库会被独占锁定：提示用户**完全退出 Edge**（含后台驻留进程）后重试，
  或在宿主配置里设置 `ZJU_COOKIE` / `ZJU_COOKIE_FILE`；
- **不要让用户把 Cookie 粘贴进对话**，也不要把 Cookie 写进讲义或命令参数；
- 工具不接受 cookie 参数，也不会回显明文；登录辅助模块开启时，`zju_read_browser_cookie`
  也只返回名称与长度。

## 6. 抓不到时

按失败原因给出一个可行动作，不要罗列互相矛盾的猜测：

- 没有登录态 / 登录失效 → 引导用户设置 `ZJU_COOKIE_FILE` 或退出 Edge 后重试；
- 没有返回截图列表 → 确认回放链接带 `course_id`，或换一条更完整的链接；
- 仍然失败 → **平滑降级为纯字幕总结**：跳过 PPT，直接用 `zju_fetch_transcript` 的字幕生成讲义。

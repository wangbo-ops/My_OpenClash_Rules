# My OpenClash Rules

在 Aethersailor《规则标准版》基础上生成个人订阅转换模板，每天检查上游并重新应用个人设置。

## 定制内容

- PayPal 规则放在国外媒体和国外电商规则之间。
- 新增 `💳 PayPal` 手动组，放在微软服务和游戏平台组之间。全球直连第一，支持所有地区组及全部单个节点，家宽节点为最后一个候选项。
- 新增 `🏠 家宽节点` 手动组，放在韩国节点和全球直连组之间：匹配家宽、家庭宽带、住宅及不区分大小写的 Residential。
- 香港、美国、日本、新加坡、台湾、韩国组改为 `select`，保留最新上游匹配正则，移除自动测速尾部参数。
- 除全球直连、非标端口、各国家/地区节点组及家宽组自身外，其余代理组均以 `[]🏠 家宽节点` 作为最后一个候选项；已有的家宽引用移到最后并去重。国家/地区节点组按 `select_groups` 和带双字母旗帜、以“节点”结尾的组名识别。
- `♻️ 自动选择` 保留 `url-test` 类型、节点匹配和测速参数，家宽候选项放在测速 URL 和间隔之前，遵循 [subconverter 格式](https://github.com/tindy2013/subconverter/blob/master/README-cn.md#配置文件)。地区组仍包含该地区的家宽节点；家宽组可包含不同地区，依据名称分类，且不引用自身。

## 启用

1. 在 GitHub 的 `wangbo-ops` 账号下创建公开仓库 `My_OpenClash_Rules`，默认分支为 `main`，勾选 README 以初始化分支。
2. 将本代码包的文件按原目录结构提交到仓库根目录，包含 `.github/workflows/update.yml`。不要把最外层目录作为仓库中的额外一层。
3. 提交脚本或设置会自动触发首次工作流。也可在 Actions → Update personal OpenClash template → Run workflow 手动运行。
4. 确认运行成功后，在订阅转换网站的远程配置中填写下面的 Raw 地址。

```text
https://raw.githubusercontent.com/wangbo-ops/My_OpenClash_Rules/main/cfg/Custom_Clash.ini
```

此地址仅在仓库和文件实际上传后生效。它是转换模板地址，不是机场节点订阅地址。使用现有节点订阅完成转换后，更新 OpenClash 订阅并检查实际分流。

## 更新策略

定时设置为 UTC 21:30，即北京时间次日 05:30（每天一次）；支持手动触发，修改脚本、设置、测试或工作流也会触发。

工作流读取上游 main 的准确提交 SHA，再按 SHA 获取模板。它只将模板当作数据读取，不执行上游代码、不同步上游工作流。

生成前先测试异常处理，生成时检查规则顺序、重复组名、引用完整性、引用环、组类型和未定制内容的保留情况。只有校验成功才提交三项生成结果：模板、上游快照、版本记录。没有变化不制造重复提交。

上游组名缺失、结构变化、增加同名 PayPal/家宽组或已有 PayPal 规则时，工作流停止发布，保留上一份模板。不存在任何强制同步或强制推送操作。设置以 `custom/settings.json` 为准，不会从上游覆盖。

GitHub 调度可能延迟或被丢弃；公共仓库连续 60 天没有活动时定时任务会停用，需要在 Actions 中重新启用。GitHub 的通知设置可用于接收失败通知。工作流使用内置 GITHUB_TOKEN 的 contents: write 权限，无需将个人访问令牌写入文件；仓库或组织策略仍可能限制写入。

### 失败通知

在 GitHub [Settings → Notifications](https://github.com/settings/notifications) 的 System → Actions 中启用 Email，可同时启用 On GitHub，并勾选 Only notify for failed workflows 后保存。参见 [官方设置说明](https://docs.github.com/en/subscriptions-and-notifications/how-tos/managing-github-actions-notifications)。

定时工作流通知发送给最后修改 cron 的用户，参见 [schedule 文档](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)。需要该用户启用相应通知；仓库代码无法代替账号通知设置。失败通知覆盖已启动但失败的运行；任务未被调度或被停用时，不能依赖失败通知发现漏跑。

## 调整个人设置

修改 `custom/settings.json`，不要手改生成的 `cfg/Custom_Clash.ini`。

- `select_groups`：需要手动选择的上游组名。当前按用户示例包含韩国。
- `residential.filter`：家宽节点名称匹配正则。
- `paypal.choices`：PayPal 候选组及顺序。家宽组自动移到全部候选项最后；其余组中第一项为没有历史选择时的初始选择。
- `paypal.include_all_nodes`：是否同时显示全部单个节点。

不要向这个公开模板仓库提交机场订阅链接、节点密码或 Token。

## 本地检查

仅需 Python 3.10+ 标准库。

```bash
python3 -m unittest discover -s tests -v
python3 scripts/build.py
```

第二条命令需要联网获取上游。离线重建可使用快照和 `upstream-version.json` 中的 commit：

```bash
python3 scripts/build.py --source vendor/Custom_Clash.ini --upstream-sha <commit>
```

本仓库校验模板生成及保护逻辑，不等价于真实机场订阅转换和路由器运行验收。GeoSite 数据须包含 paypal 分类。转换成功后检查 PayPal 规则及家宽节点匹配结果。

## 来源和许可

上游：[Aethersailor/Custom_OpenClash_Rules](https://github.com/Aethersailor/Custom_OpenClash_Rules)。衍生模板和本仓库文件使用 CC BY-SA 4.0，见 `LICENCE` 和 `NOTICE.md`。

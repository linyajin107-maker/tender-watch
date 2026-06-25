# GitHub Pages + PushPlus 部署步骤

## 1. 上传到 GitHub

在 Chrome 里打开 GitHub，新建一个仓库，例如：

`tender-watch`

把当前项目文件上传到仓库。

不要上传 `.env`，里面有你的 PushPlus Token。

## 2. 开启 GitHub Pages

进入仓库：

Settings → Pages

设置：

- Source：Deploy from a branch
- Branch：main
- Folder：/docs

保存后，GitHub 会生成一个公网地址：

`https://你的用户名.github.io/tender-watch/`

微信访问地址：

`https://你的用户名.github.io/tender-watch/wechat/`

## 3. 配置 PushPlus Secret

进入仓库：

Settings → Secrets and variables → Actions → Secrets

新增：

`PUSHPLUS_TOKEN`

值填你的 PushPlus 用户 token。

## 4. 配置页面地址变量

进入：

Settings → Secrets and variables → Actions → Variables

新增：

`TENDER_PAGE_URL`

值填：

`https://你的用户名.github.io/tender-watch/wechat/`

## 5. 开启 Actions 写入权限

进入：

Settings → Actions → General → Workflow permissions

选择：

`Read and write permissions`

这样监控脚本才能把 `tender_monitor_seen.json` 提交回仓库，避免重复推送旧线索。

## 6. 手动测试一次

进入仓库：

Actions → Tender Monitor → Run workflow

如果 PushPlus 收到提醒，说明配置成功。

之后 GitHub 会每天北京时间 08:30 自动检查。

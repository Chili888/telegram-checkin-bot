# Telegram Group Check-in Bot PRO

面向 **任意群组可添加** 的打卡机器人（支持多语言与工作时段、休息计时和自动报表）

## 📋 核心功能
- ✅ 🌐 多语言支持（中/英/越），群级设置 `/lang zh|en|vi`
- ✅ ⏰ 群组专属时区 `/settz <IANA时区>`，如 `Asia/Phnom_Penh`
- ✅ 🏢 自定义工作时间 `/workhours 09:00-18:00`
- ✅ 🚬 吸烟休息限制（⏱️ 超时2分钟自动提醒） `/smoke start|stop`
- ✅ 🚽 如厕休息限制（⏱️ 超时2分钟自动提醒） `/toilet start|stop`
- ✅ 📊 自定义报告时间 `/setreport 18:00`（群时区）
- ✅ 📈 每日自动统计报表：在设定时间自动推送当日总打卡、Top榜、休息统计

并且保留：
- /checkin 打卡（每天一次）
- /leaderboard [7|30|all] 排行（默认 7 天）
- /stats [@user] 个人统计
- /export 导出 CSV（管理员）

## 一键部署（Render）
- Build Command: `pip install -r requirements.txt`
- Start Command: `python -m app.main`
- 环境变量：`BOT_TOKEN`, `BASE_URL`, `WEBHOOK_SECRET`（Webhook 模式）；`ENABLE_POLLING=true`（本地调试）

## 命令总览
- /start, /help
- /lang zh|en|vi
- /settz <IANA时区>
- /workhours HH:MM-HH:MM
- /setreport HH:MM
- /checkin
- /smoke start|stop
- /toilet start|stop
- /leaderboard [7|30|all]
- /stats [@user]
- /export

## 数据存储
- SQLite（aiosqlite），文件 `./data/checkins.sqlite`，包含：签到、设置（时区/语言/工作时段/报表时间）、休息记录（吸烟/如厕，开始与停止时间）

## 许可证
MIT

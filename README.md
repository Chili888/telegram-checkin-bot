# Telegram Group Check-in Bot PRO — Custom Keyword Triggers

特性：
- 自定义关键词触发 `/addtrigger 关键词 动作`
- 查看触发词 `/listtriggers`
- 删除触发词 `/deltrigger 关键词`
- 动作可选：`checkin`、`smoke_start`、`smoke_stop`、`toilet_start`、`toilet_stop`
- 支持中/英/越命令与回复，Webhook/轮询皆可
- 多群可用，触发词按群隔离存储（SQLite）

使用前在 @BotFather 里：`/setprivacy` → 选择 **Disable**，让机器人能读取群聊文本

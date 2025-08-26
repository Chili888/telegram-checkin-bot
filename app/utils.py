from typing import Optional, Dict

LANG_PACK: Dict[str, Dict[str, str]] = {
    "zh": {
        "hello": "我是群打卡机器人",
        "help": (
            "指令：\n"
            "/checkin 今日打卡\n"
            "/leaderboard [7|30|all] 排行榜（默认7天）\n"
            "/stats [@user] 个人统计\n"
            "/lang zh|en|vi 设置语言\n"
            "/settz <IANA时区> 设置时区，如 Asia/Phnom_Penh\n"
            "/workhours HH:MM-HH:MM 设置工作时间\n"
            "/setreport HH:MM 设置日报时间\n"
            "/smoke start|stop 吸烟开始/结束（超2分钟提醒）\n"
            "/toilet start|stop 如厕开始/结束（超2分钟提醒）\n"
            "/export 导出CSV（管理员）"
        ),
        "btn_checkin": "一键打卡 ✅",
        "checked_today": "你今天已经在 {tz} 时区打过卡啦 ✅",
        "checkin_ok": "打卡成功 ✅（时区：{tz}）",
        "no_data": "还没有数据",
        "lb_title_days": "排行榜（最近 {days} 天）",
        "lb_title_all": "排行榜（全部）",
        "settz_ok": "本群时区已设置为：{tz}",
        "settz_admin": "仅群管理员可以设置时区",
        "invalid_tz": "无效时区，请参考 tz database",
        "csv_ok": "CSV 已生成",
        "csv_empty": "暂无数据可导出",
        "lang_ok": "语言已设置为：{lang}",
        "admin_only": "仅群管理员可用",
        "work_set": "工作时间已设置为：{hours}（群时区）",
        "report_set": "日报时间已设置为：{time}（群时区）",
        "smoke_started": "吸烟休息开始，超过2分钟会提醒你结束",
        "smoke_stopped": "吸烟休息结束，持续 {mins} 分钟",
        "toilet_started": "如厕休息开始，超过2分钟会提醒你结束",
        "toilet_stopped": "如厕休息结束，持续 {mins} 分钟",
        "break_reminder": "⏰ 已超过 2 分钟，请尽快结束 {kind} 休息并返回工作",
        "report_title": "📈 今日统计报表（{date}，时区 {tz}）",
        "report_sections": "打卡人数：{checkins}\n吸烟休息：{smoke_cnt} 次；总时长 {smoke_min} 分钟\n如厕休息：{toilet_cnt} 次；总时长 {toilet_min} 分钟\nTop 打卡：\n{top}",
        "unknown_cmd": "参数无效或用法错误",
    },
    "en": {
        "hello": "I am the group check-in bot",
        "help": (
            "Commands:\n"
            "/checkin Check in today\n"
            "/leaderboard [7|30|all]\n"
            "/stats [@user]\n"
            "/lang zh|en|vi\n"
            "/settz <IANA TZ>\n"
            "/workhours HH:MM-HH:MM\n"
            "/setreport HH:MM\n"
            "/smoke start|stop (2-min reminder)\n"
            "/toilet start|stop (2-min reminder)\n"
            "/export (admin)"
        ),
        "btn_checkin": "Check in ✅",
        "checked_today": "You already checked in today (tz {tz}) ✅",
        "checkin_ok": "Checked in ✅ (tz {tz})",
        "no_data": "No data yet",
        "lb_title_days": "Leaderboard (last {days} days)",
        "lb_title_all": "Leaderboard (all time)",
        "settz_ok": "Group timezone set to: {tz}",
        "settz_admin": "Admins only",
        "invalid_tz": "Invalid timezone, please see tz database",
        "csv_ok": "CSV generated",
        "csv_empty": "No data to export",
        "lang_ok": "Language set to: {lang}",
        "admin_only": "Admins only",
        "work_set": "Work hours set to: {hours} (group TZ)",
        "report_set": "Report time set to: {time} (group TZ)",
        "smoke_started": "Smoking break started, a reminder will fire after 2 minutes",
        "smoke_stopped": "Smoking break stopped, lasted {mins} minutes",
        "toilet_started": "Toilet break started, a reminder will fire after 2 minutes",
        "toilet_stopped": "Toilet break stopped, lasted {mins} minutes",
        "break_reminder": "⏰ Over 2 minutes. Please end your {kind} break and get back to work",
        "report_title": "📈 Daily Report ({date}, tz {tz})",
        "report_sections": "Check-ins: {checkins}\nSmoking: {smoke_cnt} times; {smoke_min} minutes\nToilet: {toilet_cnt} times; {toilet_min} minutes\nTop:\n{top}",
        "unknown_cmd": "Invalid arguments or usage",
    },
    "vi": {
        "hello": "Mình là bot điểm danh cho nhóm",
        "help": (
            "Lệnh:\n"
            "/checkin Điểm danh hôm nay\n"
            "/leaderboard [7|30|all]\n"
            "/stats [@user]\n"
            "/lang zh|en|vi\n"
            "/settz <múi giờ IANA>\n"
            "/workhours HH:MM-HH:MM\n"
            "/setreport HH:MM\n"
            "/smoke start|stop (nhắc sau 2 phút)\n"
            "/toilet start|stop (nhắc sau 2 phút)\n"
            "/export (quản trị viên)"
        ),
        "btn_checkin": "Điểm danh ✅",
        "checked_today": "Bạn đã điểm danh hôm nay (múi giờ {tz}) ✅",
        "checkin_ok": "Điểm danh thành công ✅ (múi giờ {tz})",
        "no_data": "Chưa có dữ liệu",
        "lb_title_days": "Bảng xếp hạng ({days} ngày gần nhất)",
        "lb_title_all": "Bảng xếp hạng (tất cả)",
        "settz_ok": "Đã đặt múi giờ nhóm: {tz}",
        "settz_admin": "Chỉ quản trị viên",
        "invalid_tz": "Múi giờ không hợp lệ",
        "csv_ok": "Đã tạo CSV",
        "csv_empty": "Không có dữ liệu để xuất",
        "lang_ok": "Đã đặt ngôn ngữ: {lang}",
        "admin_only": "Chỉ quản trị viên",
        "work_set": "Đã đặt giờ làm: {hours} (múi giờ nhóm)",
        "report_set": "Đã đặt giờ báo cáo: {time} (múi giờ nhóm)",
        "smoke_started": "Bắt đầu nghỉ hút thuốc, sẽ nhắc sau 2 phút",
        "smoke_stopped": "Kết thúc nghỉ hút thuốc, kéo dài {mins} phút",
        "toilet_started": "Bắt đầu nghỉ vệ sinh, sẽ nhắc sau 2 phút",
        "toilet_stopped": "Kết thúc nghỉ vệ sinh, kéo dài {mins} phút",
        "break_reminder": "⏰ Hơn 2 phút rồi, vui lòng kết thúc nghỉ {kind} và quay lại làm việc",
        "report_title": "📈 Báo cáo ngày ({date}, múi giờ {tz})",
        "report_sections": "Điểm danh: {checkins}\nHút thuốc: {smoke_cnt} lần; {smoke_min} phút\nVệ sinh: {toilet_cnt} lần; {toilet_min} phút\nTop:\n{top}",
        "unknown_cmd": "Tham số không hợp lệ",
    },
}

def t(lang: str, key: str, **kwargs) -> str:
    pack = LANG_PACK.get(lang, LANG_PACK["zh"])
    s = pack.get(key, key)
    if kwargs:
        try:
            return s.format(**kwargs)
        except Exception:
            return s
    return s

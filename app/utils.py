from typing import Dict

LANG_PACK: Dict[str, Dict[str, str]] = {
    "zh": {
        "btn_checkin":"一键打卡 ✅",
        "checked_today":"你今天已经在 {tz} 时区打过卡啦 ✅",
        "checkin_ok":"打卡成功 ✅（时区：{tz}）",
        "admin_only":"仅群管理员可用",
        "trigger_added":"已添加触发词：{kw} → {act}",
        "trigger_exists":"触发词已存在：{kw}",
        "trigger_deleted":"已删除触发词：{kw}",
        "trigger_not_found":"未找到触发词：{kw}",
        "triggers_header":"本群触发词（共 {n} 项）：",
        "triggers_item":"- {kw} → {act}",
        "no_triggers":"暂无触发词",
        "usage_add":"用法：/addtrigger 关键词 动作\n动作：checkin / smoke_start / smoke_stop / toilet_start / toilet_stop",
        "usage_del":"用法：/deltrigger 关键词",
    },
    "en": {
        "btn_checkin":"Check in ✅",
        "checked_today":"You already checked in today (tz {tz}) ✅",
        "checkin_ok":"Checked in ✅ (tz {tz})",
        "admin_only":"Admins only",
        "trigger_added":"Trigger added: {kw} → {act}",
        "trigger_exists":"Trigger already exists: {kw}",
        "trigger_deleted":"Trigger deleted: {kw}",
        "trigger_not_found":"Trigger not found: {kw}",
        "triggers_header":"Triggers in this group ({n}):",
        "triggers_item":"- {kw} → {act}",
        "no_triggers":"No triggers yet",
        "usage_add":"Usage: /addtrigger <keyword> <action>\nActions: checkin / smoke_start / smoke_stop / toilet_start / toilet_stop",
        "usage_del":"Usage: /deltrigger <keyword>",
    },
    "vi": {
        "btn_checkin":"Điểm danh ✅",
        "checked_today":"Bạn đã điểm danh hôm nay (múi giờ {tz}) ✅",
        "checkin_ok":"Điểm danh thành công ✅ (múi giờ {tz})",
        "admin_only":"Chỉ quản trị viên",
        "trigger_added":"Đã thêm kích hoạt: {kw} → {act}",
        "trigger_exists":"Đã tồn tại: {kw}",
        "trigger_deleted":"Đã xoá: {kw}",
        "trigger_not_found":"Không tìm thấy: {kw}",
        "triggers_header":"Từ khoá kích hoạt trong nhóm ({n}):",
        "triggers_item":"- {kw} → {act}",
        "no_triggers":"Chưa có từ khoá",
        "usage_add":"Cú pháp: /addtrigger <từ> <hành động>\nHành động: checkin / smoke_start / smoke_stop / toilet_start / toilet_stop",
        "usage_del":"Cú pháp: /deltrigger <từ>",
    },
}

def t(lang: str, key: str, **kwargs) -> str:
    pack = LANG_PACK.get(lang, LANG_PACK["zh"])
    s = pack.get(key, key)
    return s.format(**kwargs) if kwargs else s

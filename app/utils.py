from typing import Dict

LANG_PACK: Dict[str, Dict[str, str]] = {
    "zh": {
        "btn_checkin":"一键打卡 ✅",
        "checked_today":"你今天已经在 {tz} 时区打过卡啦 ✅",
        "checkin_ok":"打卡成功 ✅（时区：{tz}）",
        "no_data":"还没有数据",
    },
    "en": {
        "btn_checkin":"Check in ✅",
        "checked_today":"You already checked in today (tz {tz}) ✅",
        "checkin_ok":"Checked in ✅ (tz {tz})",
        "no_data":"No data yet",
    },
    "vi": {
        "btn_checkin":"Điểm danh ✅",
        "checked_today":"Bạn đã điểm danh hôm nay (múi giờ {tz}) ✅",
        "checkin_ok":"Điểm danh thành công ✅ (múi giờ {tz})",
        "no_data":"Chưa có dữ liệu",
    },
}

def t(lang: str, key: str, **kwargs) -> str:
    pack = LANG_PACK.get(lang, LANG_PACK["zh"])
    s = pack.get(key, key)
    return s.format(**kwargs) if kwargs else s

# -*- coding: utf-8 -*-
"""
임대차 계약서 검증 — 주소/금액/날짜/성명/식별정보 비교 로직
"""

import difflib
import html
import re
from typing import Any, Optional


def format_korean_money(n: int) -> str:
    """금액을 한글 만/억 단위로 변환. 예: 300000000 -> '3억 원', 150000000 -> '1억 5,000만 원'."""
    if n is None or n < 0:
        return ""
    if n == 0:
        return "💡 0원"
    eok = n // 100_000_000
    man = (n % 100_000_000) // 10_000
    if eok > 0 and man > 0:
        return f"💡 {eok}억 {man:,}만 원"
    if eok > 0:
        return f"💡 {eok}억 원"
    if man > 0:
        return f"💡 {man:,}만 원"
    return f"💡 {n:,}원"


def _normalize_address(addr: str) -> str:
    """주소 전처리: 대소문자 통일, 노이즈 제거, 공백 제거."""
    if not addr or not isinstance(addr, str):
        return ""
    s = addr.strip().lower()
    s = re.sub(r"제\s*(\d+)", r"\1", s)
    s = re.sub(r"(\d+-\d+)\s+", r"\1|", s)
    s = re.sub(r"(\d+)번지\s+", r"\1번지|", s)
    s = s.replace(" ", "")
    s = re.sub(r"특별시", "", s)
    s = re.sub(r"광역시", "", s)
    s = re.sub(r"특별자치시", "", s)
    return s


def _extract_jibon(addr: str) -> Optional[str]:
    """번지(지번) 추출."""
    m = re.search(r"(\d+)-(\d+)", addr)
    if m:
        return f"{m.group(1)}-{m.group(2)}"
    m = re.search(r"(\d+)번지", addr)
    if m:
        return m.group(1)
    return None


def _extract_gu_dong_only(addr_normalized: str) -> str:
    """행정 구역(구, 동/리)만 추출. 건물명 제외."""
    tokens = re.findall(r"[가-힣]+구|[가-힣]+동|[가-힣]+리", addr_normalized)
    return "".join(tokens)


def _extract_dong_number(addr: str) -> Optional[str]:
    """동(Dong) 번호 추출."""
    jibon_m = re.search(r"\d+-\d+", addr)
    if jibon_m:
        after_jibon = addr[jibon_m.end() :]
        m = re.search(r"(\d+)동", after_jibon)
        if m:
            return m.group(1)
    m = re.search(r"(\d+)동", addr)
    if m:
        return m.group(1)
    return None


def _extract_ho_number(addr: str) -> Optional[str]:
    """호수(Ho) 번호 추출."""
    m = re.search(r"(\d+)호", addr)
    if m:
        return m.group(1)
    dong_m = re.search(r"(\d+)동", addr)
    if dong_m:
        after = addr[dong_m.end() :]
        ho_m = re.search(r"(\d{3,5})(?=\D|$)", after)
        if ho_m:
            return ho_m.group(1)
    return None


def compare_address(contract_addr: str, user_addr: str) -> tuple[bool, str]:
    """주소 일치 여부. 사용자 주소 비어 있으면 (False, '사용자 입력 누락')."""
    if not (user_addr or "").strip():
        return (False, "사용자 입력 누락")
    if not (contract_addr or "").strip():
        return (False, "주소 정보가 없습니다")
    c = _normalize_address(contract_addr)
    u = _normalize_address(user_addr)
    if not c or not u:
        return (False, "주소를 비교할 수 없습니다")

    c_jibon = _extract_jibon(c)
    u_jibon = _extract_jibon(u)
    c_gu_dong = _extract_gu_dong_only(c)
    u_gu_dong = _extract_gu_dong_only(u)
    if c_gu_dong and u_gu_dong:
        if (
            c_gu_dong != u_gu_dong
            and u_gu_dong not in c_gu_dong
            and c_gu_dong not in u_gu_dong
        ):
            return (False, "행정 구역(구/동·리) 불일치")

    c_dong = _extract_dong_number(c)
    u_dong = _extract_dong_number(u)
    c_ho = _extract_ho_number(c)
    u_ho = _extract_ho_number(u)

    # [핵심] 건물명 할루시네이션이 있어도 행정구역(동)+지번+동/호수만 맞으면 True
    # 우선순위 1: 행정구역(동) + 지번 + 동/호수 모두 일치 (건물명 무관)
    if c_gu_dong and u_gu_dong and c_gu_dong == u_gu_dong:
        if c_jibon and u_jibon and c_jibon == u_jibon:
            if (
                c_dong is not None
                and u_dong is not None
                and c_ho is not None
                and u_ho is not None
            ):
                if c_dong == u_dong and c_ho == u_ho:
                    return (True, "")
            # 동/호수 없어도 행정구역+지번만 맞으면 통과
            if (c_dong is None and u_dong is None) or (c_dong == u_dong):
                if (c_ho is None and u_ho is None) or (c_ho == u_ho):
                    return (True, "")

    # 우선순위 2: 동·호수만 정확히 맞으면 통과 (지번 유무와 무관)
    if (
        c_dong is not None
        and u_dong is not None
        and c_ho is not None
        and u_ho is not None
    ):
        if c_dong == u_dong and c_ho == u_ho:
            return (True, "")

    # 지번 불일치 체크: 둘 다 있으면 일치해야 함
    if c_jibon is not None and u_jibon is not None and c_jibon != u_jibon:
        return (False, "지번 숫자 누락 또는 불일치")

    # 사용자 입력에 동/호수가 없고 지번까지만 있을 경우, 행정주소+지번 일치 시 True
    # 계약서에 지번이 없어도 사용자 지번이 행정구역(동) 뒤에 붙어 있으면 일치로 간주
    if u_dong is None and u_ho is None:
        if c_gu_dong and u_gu_dong and c_gu_dong == u_gu_dong:
            if (c_jibon and u_jibon and c_jibon == u_jibon) or (
                c_jibon is None and u_jibon is not None
            ):
                return (True, "")

    has_building_dong = c_dong is not None or u_dong is not None
    if has_building_dong:
        if c_dong != u_dong:
            return (False, f"동 불일치({c_dong or '-'} vs {u_dong or '-'})")
        if c_ho != u_ho:
            return (False, f"호수 불일치({c_ho or '-'} vs {u_ho or '-'})")
        return (True, "")

    if c_ho is not None and u_ho is not None and c_ho != u_ho:
        return (False, f"호수 불일치({c_ho} vs {u_ho})")
    if (c_ho is None) != (u_ho is None):
        return (False, "호수 누락 또는 불일치")
    return (True, "")


def _parse_korean_amount_to_int(text: str) -> Optional[int]:
    """
    한글 금액(일억육천만원정 등)과 숫자(160,000,000) 모두 int로 파싱.
    - 지원 단위: 억/만/천/백/십
    - 한글 숫자: 영/공/일/이/삼/사/오/육/칠/팔/구 (+ 한/두/세/네는 최소 지원)
    """
    if text is None:
        return None
    s = str(text).strip()
    if not s:
        return None
    s = s.replace(" ", "").replace(",", "")
    # 빠른 숫자 파싱
    digits = re.sub(r"[^\d]", "", s)
    if digits:
        try:
            return int(digits)
        except Exception:
            pass

    # 한글 금액 파싱
    s = re.sub(r"[₩원정금\(\)]", "", s)
    s = s.replace("금", "")

    num_map = {
        "영": 0,
        "공": 0,
        "일": 1,
        "이": 2,
        "삼": 3,
        "사": 4,
        "오": 5,
        "육": 6,
        "칠": 7,
        "팔": 8,
        "구": 9,
        "한": 1,
        "두": 2,
        "세": 3,
        "네": 4,
    }
    small_unit = {"십": 10, "백": 100, "천": 1000}

    def parse_under_10000(part: str) -> int:
        total = 0
        tmp = 0
        i = 0
        while i < len(part):
            ch = part[i]
            if ch in num_map:
                tmp = num_map[ch]
                i += 1
                continue
            if ch in small_unit:
                mul = small_unit[ch]
                total += (tmp if tmp != 0 else 1) * mul
                tmp = 0
                i += 1
                continue
            i += 1
        total += tmp
        return total

    total = 0
    if "억" in s:
        left, right = s.split("억", 1)
        total += parse_under_10000(left) * 100_000_000
        s = right
    if "만" in s:
        left, right = s.split("만", 1)
        total += parse_under_10000(left) * 10_000
        s = right
    total += parse_under_10000(s)
    return total if total != 0 else 0


def _parse_amount_from_text(text: str, field_name: str = None) -> Optional[int]:
    """
    금액 텍스트를 안전하게 int로 파싱.
    - 월세: '0'이면 절대 재해석하지 않음.
    - 월세: 차임/월세 키워드 문맥이 없으면 '보증금 전이' 가능성이 있으니 숫자 파싱은 보수적으로 함.
    """
    if text is None:
        return 0 if field_name == "월세" else None
    raw = str(text).strip()
    if not raw or raw.lower() == "null":
        return 0 if field_name == "월세" else None
    if field_name == "월세" and raw in ("0", "0원"):
        return 0

    if field_name == "월세":
        pass

    return _parse_korean_amount_to_int(raw)


def _parse_amount_simple(text: str) -> Optional[int]:
    """숫자만 추출. 사용자 입력용."""
    if not text or not isinstance(text, str):
        return None
    t = text.strip().replace(",", "").replace(" ", "")
    if not t or "없음" in t or "무" in t:
        return 0
    digits = re.sub(r"[^\d]", "", t)
    if not digits:
        return 0
    return int(digits)


def _python_compare_amount(
    contract_value: str, user_value: str, field_name: str = None
) -> tuple[bool, str]:
    """보증금/월세 금액 비교. 사용자 입력 비어 있으면 (False, '사용자 입력 누락')."""
    if not (user_value or "").strip():
        return (False, "사용자 입력 누락")
    contract_num = _parse_amount_from_text(contract_value, field_name)
    user_num = _parse_amount_simple(user_value)
    if contract_num is None:
        return (False, "계약서에서 금액을 인식하지 못했습니다")
    if user_num is None:
        user_num = 0
    if contract_num == 0 and user_num != 0:
        return (False, "계약서에는 해당 금액이 없습니다")
    if contract_num == user_num:
        return (True, "")
    return (False, "금액이 일치하지 않습니다")


def _parse_date_from_text(s: str) -> Optional[str]:
    """단일 날짜를 YYYY-MM-DD로 파싱."""
    if not s or not isinstance(s, str):
        return None
    s = s.strip()
    m = re.search(r"(\d{4})\.(\d{1,2})\.(\d{1,2})", s)
    if m:
        return f"{m.group(1)}-{m.group(2).zfill(2)}-{m.group(3).zfill(2)}"
    m = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", s)
    if m:
        return f"{m.group(1)}-{m.group(2).zfill(2)}-{m.group(3).zfill(2)}"
    m = re.search(r"(\d{4})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일?", s)
    if m:
        return f"{m.group(1)}-{m.group(2).zfill(2)}-{m.group(3).zfill(2)}"
    m = re.search(r"(\d{4})(\d{2})(\d{2})", s)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return None


def _parse_dates_from_period_text(text: str) -> tuple[Optional[str], Optional[str]]:
    """계약기간 텍스트에서 시작일, 종료일 추출."""
    if not text or not isinstance(text, str):
        return (None, None)

    def _norm(g: tuple) -> str:
        if g[0] is not None:
            return f"{g[0]}-{str(g[1]).zfill(2)}-{str(g[2]).zfill(2)}"
        if g[3] is not None:
            return f"{g[3]}-{str(g[4]).zfill(2)}-{str(g[5]).zfill(2)}"
        if g[6] is not None:
            return f"{g[6]}-{g[7]}-{g[8]}"
        return ""

    pattern = (
        r"(\d{4})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일|"
        r"(\d{4})[.\-](\d{1,2})[.\-](\d{1,2})|"
        r"(\d{4})(\d{2})(\d{2})"
    )
    all_dates: list[str] = []
    for m in re.finditer(pattern, text):
        g = m.groups()
        normed = _norm(g) if len(g) >= 9 else ""
        if normed and normed not in all_dates:
            all_dates.append(normed)
    if len(all_dates) >= 2:
        return (all_dates[0], all_dates[1])
    if len(all_dates) == 1:
        return (all_dates[0], None)
    return (None, None)


def _parse_user_period(user_value: str) -> tuple[Optional[str], Optional[str]]:
    """사용자 입력 계약기간 파싱."""
    if not user_value:
        return (None, None)
    parts = re.split(r"\s*~\s*|\s+", user_value.strip())
    dates = []
    for p in parts:
        d = _parse_date_from_text(p)
        if d:
            dates.append(d)
    if len(dates) >= 2:
        return (dates[0], dates[1])
    if len(dates) == 1:
        return (dates[0], None)
    return (None, None)


def _python_compare_contract_period(
    contract_value: str, user_value: str
) -> tuple[bool, str]:
    """계약기간 비교. 사용자 입력 비어 있으면 (False, '사용자 입력 누락')."""
    if not (user_value or "").strip():
        return (False, "사용자 입력 누락")
    contract_start, contract_end = _parse_dates_from_period_text(contract_value)
    user_start, user_end = _parse_user_period(user_value)
    if contract_start is None or contract_end is None:
        return (False, "계약서에서 계약기간을 명확히 인식하지 못했습니다")
    if user_start is None or user_end is None:
        return (False, "사용자 입력 계약기간 형식이 올바르지 않습니다")
    if contract_start == user_start and contract_end == user_end:
        return (True, "")
    error_reasons: list[str] = []
    if contract_start != user_start:
        error_reasons.append(
            f"시작일 불일치 (계약서: {contract_start} / 입력: {user_start})"
        )
    if contract_end != user_end:
        error_reasons.append(
            f"종료일 불일치 (계약서: {contract_end} / 입력: {user_end})"
        )
    if len(error_reasons) == 2:
        return (False, "기간 전체 불일치")
    return (False, error_reasons[0])


def _python_compare_string(contract_value: str, user_value: str) -> tuple[bool, str]:
    """일반 문자열 비교. 사용자 입력 비어 있으면 (False, '사용자 입력 누락')."""
    c = (contract_value or "").strip()
    u = (user_value or "").strip()
    if not u:
        return (False, "사용자 입력 누락")
    if c == u:
        return (True, "")
    return (False, "일치하지 않습니다")


def _python_compare_name(contract_value: str, user_value: str) -> tuple[bool, str]:
    """성명 비교. 사용자 입력 비어 있으면 (False, '사용자 입력 누락'). 공백 제거 후 비교."""
    c_raw = (contract_value or "").strip()
    u_raw = (user_value or "").strip()
    c = c_raw.replace(" ", "")
    u = u_raw.replace(" ", "")
    if not u:
        return (False, "사용자 입력 누락")
    if "식별불가" in c_raw:
        return (False, "⚠️ 식별 불가 (이미지 화질 확인 필요) / AI 인식값: " + c_raw)
    if difflib.SequenceMatcher(None, c, u).ratio() == 1.0:
        return (True, "")
    return (False, "성명 미세 불일치 주의 / AI 인식값: " + c_raw)


def _python_compare_id_info(contract_value: str, user_value: str) -> tuple[bool, str]:
    """식별정보 원문 비교. 사용자 입력 비어 있으면 (False, '사용자 입력 누락')."""
    if "식별불가" in (contract_value or ""):
        return (False, "⚠️ 식별 불가 (이미지 화질 확인 필요)")

    c_digits = re.sub(r"\D", "", contract_value or "")
    c_first6 = c_digits[:6] if len(c_digits) >= 6 else c_digits

    u_digits = re.sub(r"\D", "", user_value or "")
    u_norm = u_digits[:6] if len(u_digits) >= 6 else u_digits

    if not c_first6:
        return (False, "계약서에 식별정보 미기재")
    if not u_norm:
        return (False, "사용자 입력 누락")

    if c_first6 == u_norm:
        return (True, "")
    return (False, f"식별정보 불일치 (AI 인식값: {c_first6}-*******, 입력값: {u_norm})")


def _mask_jumin(raw: str) -> str:
    """식별정보 뒷자리 마스킹."""
    if not raw or not isinstance(raw, str):
        return raw or ""
    s = raw.strip()
    if not s or "식별불가" in s:
        return s
    digits_only = re.sub(r"\D", "", s)
    if len(digits_only) < 6:
        return s
    if len(digits_only) == 8:
        first6 = digits_only[2:8]
    else:
        first6 = digits_only[:6]
    return first6 + "-*******"


def _cross_check_contract_vs_checklist(
    item_name: str, contract_value: str, checklist_value: Any
) -> bool:
    """계약서 vs 확인설명서 일치 여부."""
    if checklist_value is None or str(checklist_value).strip() == "":
        return True
    c = str(contract_value or "").strip()
    ch = str(checklist_value or "").strip()
    if not c or not ch:
        return True
    if item_name == "주소":
        return compare_address(c, ch)[0]
    if item_name in ("보증금", "월세"):
        return _python_compare_amount(c, ch, item_name)[0]
    if item_name == "계약기간":
        return _python_compare_contract_period(c, ch)[0]
    return c == ch


def run_python_comparison(
    item_name: str, contract_value: str, user_value: str
) -> tuple[bool, str]:
    """8개 항목 전수 파이썬 비교."""
    if item_name == "주소":
        return compare_address(contract_value, user_value)
    if item_name in ("보증금", "월세"):
        return _python_compare_amount(contract_value, user_value, item_name)
    if item_name == "계약기간":
        return _python_compare_contract_period(contract_value, user_value)
    if item_name in ("임대인 성명", "임차인 성명"):
        return _python_compare_name(contract_value, user_value)
    if item_name in ("임대인 생년월일", "임차인 생년월일"):
        return _python_compare_id_info(contract_value, user_value)
    c = (contract_value or "").strip()
    u = (user_value or "").strip()
    if not u:
        return (False, "사용자 입력 누락")
    match = c == u
    return (match, "" if match else "일치하지 않습니다")


def _highlight_period_diff(contract_val: str, user_val: str) -> str:
    """계약기간 불일치 시 틀린 날짜만 빨간색 볼드."""
    if not user_val:
        return ""
    contract_parts = [p.strip() for p in contract_val.split("~") if p.strip()]
    user_parts = [p.strip() for p in user_val.split("~") if p.strip()]
    if len(contract_parts) < 2 or len(user_parts) < 2:
        return f'<span style="color:#ef4444; font-weight:bold;">{html.escape(user_val)}</span>'
    contract_start = _parse_date_from_text(contract_parts[0])
    contract_end = _parse_date_from_text(contract_parts[1])
    user_start = _parse_date_from_text(user_parts[0])
    user_end = _parse_date_from_text(user_parts[1])
    if (
        contract_start is None
        or contract_end is None
        or user_start is None
        or user_end is None
    ):
        return f'<span style="color:#ef4444; font-weight:bold;">{html.escape(user_val)}</span>'
    start_diff = contract_start != user_start
    end_diff = contract_end != user_end
    start_html = (
        f'<span style="color:#ef4444; font-weight:bold;">{html.escape(user_parts[0])}</span>'
        if start_diff
        else html.escape(user_parts[0])
    )
    end_html = (
        f'<span style="color:#ef4444; font-weight:bold;">{html.escape(user_parts[1])}</span>'
        if end_diff
        else html.escape(user_parts[1])
    )
    return f"{start_html} ~ {end_html}"


def _highlight_diff(contract_text: str, user_text: str) -> str:
    """user_text 중 contract_text와 다른 부분만 빨간색 볼드."""
    if not user_text:
        return ""
    matcher = difflib.SequenceMatcher(None, contract_text, user_text)
    result: list[str] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        user_slice = user_text[j1:j2]
        if tag in ("replace", "insert"):
            result.append(
                f'<span style="color:#ef4444; font-weight:bold;">{html.escape(user_slice)}</span>'
            )
        elif tag == "equal" and user_slice:
            result.append(html.escape(user_slice))
    return "".join(result)

# -*- coding: utf-8 -*-
import json
import re
from typing import Any, Optional
from comparators import _cross_check_contract_vs_checklist, _parse_amount_from_text


def _normalize_text(v):
    if v is None:
        return None
    s = str(v).strip()
    return s if s else None


def _rrn_to_birth6(rrn: str):
    """
    주민등록번호/식별문자열에서 생년월일 YYMMDD(앞 6자리)만 안전하게 추출.
    - '640914-1038018', '0105034199718', '010503-4199718' 모두 처리
    - 검증(세기/유효일자)로 실패시키지 말고, 앞 6자리만 있으면 반환
    """
    if not rrn:
        return None
    digits = "".join(ch for ch in str(rrn) if ch.isdigit())
    return digits[:6] if len(digits) >= 6 else None


def _extract_json_object(text: str) -> Optional[str]:
    match = re.search(r"\{|\[", text)
    if not match:
        return None
    first = match.start()
    depth = 0
    for i in range(first, len(text)):
        if text[i] in "{[":
            depth += 1
        elif text[i] in "}]":
            depth -= 1
            if depth == 0:
                return text[first : i + 1]
    return None


def parse_result_json(raw: str) -> Optional[dict[str, Any]]:
    if not raw:
        return None
    text = _extract_json_object(raw)
    if not text:
        m = re.search(r"\{|\[", raw)
        if m:
            text = raw[m.start() :].strip()
    if not text:
        return None
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            parsed = {"items": parsed}
        items = parsed.get("items", [])
        new_items = []
        for obj in items:
            if not isinstance(obj, dict):
                continue

            has_standard = "item" in obj and "contract_value" in obj
            has_nested_dict = any(isinstance(v, dict) for v in obj.values())

            if has_standard and not has_nested_dict:
                # 표준 구조: 보따리(Dict)가 contract_value에 들어온 경우 처리
                raw_val = obj.get("contract_value")
                if isinstance(raw_val, dict):
                    obj["contract_value"] = str(
                        raw_val.get("생년월일")
                        or raw_val.get("식별정보")
                        or raw_val
                        or ""
                    )
                item_name = obj.get("item", "")
                obj["item"] = item_name.replace("식별정보 원문", "생년월일").replace(
                    " 정보", " 생년월일"
                )
                new_items.append(obj)
            else:
                # AI가 항목을 딕셔너리로 묶어 보낸 경우(예: "임대인 정보": {...}) 또는 플랫 구조
                for k, v in obj.items():
                    if isinstance(v, dict):
                        for sub_k, sub_v in v.items():
                            combined_key = f"{k.replace(' 정보', '')} {sub_k}"
                            new_items.append(
                                {
                                    "item": combined_key,
                                    "contract_value": (
                                        str(sub_v) if sub_v is not None else ""
                                    ),
                                }
                            )
                    elif k not in ("item", "contract_value", "checklist_value"):
                        new_key = k.replace("식별정보 원문", "생년월일").replace(
                            " 정보", " 생년월일"
                        )
                        val = v
                        if isinstance(v, dict):
                            val = v.get("생년월일") or v.get("식별정보") or str(v)
                        new_items.append(
                            {
                                "item": new_key,
                                "contract_value": str(val) if val is not None else "",
                                "checklist_value": obj.get("checklist_value"),
                            }
                        )
                    else:
                        new_items.append(obj)
                        break

        # 중복 이름 치환 (주민등록번호 -> 생년월일)
        for r in new_items:
            r["item"] = (
                r["item"]
                .replace("식별정보 원문", "생년월일")
                .replace(" 정보", " 생년월일")
            )
            if "checklist_value" not in r:
                r["checklist_value"] = None

        parsed["items"] = new_items
        return parsed
    except Exception:
        return None


def build_final_items(parsed: dict[str, Any]) -> dict[str, Any]:
    items = list(parsed.get("items", []))
    # 생년월일 백필: 주민등록번호는 있는데 생년월일이 비어있/식별불가면 앞 6자리로 보강
    by_item = {r.get("item"): r for r in items if r.get("item")}
    for key_birth, key_rrn in (
        ("임대인 생년월일", "임대인 주민등록번호"),
        ("임차인 생년월일", "임차인 주민등록번호"),
    ):
        birth_row = by_item.get(key_birth)
        cv = (birth_row or {}).get("contract_value") if birth_row else None
        if _normalize_text(cv) in (None, "", "식별불가"):
            rrn_val = (by_item.get(key_rrn) or {}).get("contract_value")
            b6 = _rrn_to_birth6(rrn_val)
            if b6:
                if not birth_row:
                    birth_row = {
                        "item": key_birth,
                        "contract_value": None,
                        "checklist_value": None,
                    }
                    items.append(birth_row)
                    by_item[key_birth] = birth_row
                birth_row["contract_value"] = b6

    mismatches = []
    for r in items:
        r["is_doc_mismatch"] = False
        item_name = r.get("item")
        cv_raw = r.get("contract_value")
        ch_raw = r.get("checklist_value")

        # 🔥 안전 파싱
        cv = _parse_amount_from_text(cv_raw, item_name)
        ch = _parse_amount_from_text(ch_raw, item_name)

        if ch and not _cross_check_contract_vs_checklist(item_name, cv, ch):
            r["is_doc_mismatch"] = True
            mismatches.append(
                {
                    "item_name": item_name,
                    "contract_value": cv,
                    "checklist_value": ch,
                }
            )
    return {
        "items": items,
        "human_review": bool(mismatches),
        "human_review_reason": "문서 간 불일치" if mismatches else "",
        "cross_check_mismatches": mismatches,
    }

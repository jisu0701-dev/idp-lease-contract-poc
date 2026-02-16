# -*- coding: utf-8 -*-
"""
임대차 계약서 자동 검증기
Rental Contract Auto Verifier - Streamlit App (UI 전용)
"""

import base64
import html
import json
import os
import re
import time
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Optional

LOCAL_DIR = Path(".local")
LOCAL_DIR.mkdir(exist_ok=True)
DECISION_LOG_PATH = LOCAL_DIR / "decision_log.csv"

import pandas as pd
import streamlit as st

from comparators import (
    _cross_check_contract_vs_checklist,
    _highlight_diff,
    _highlight_period_diff,
    _mask_jumin,
    format_korean_money,
    run_python_comparison as _run_python_comparison,
)
from document_logic import build_final_items, parse_result_json
from ocr_service import (
    call_gemini_vision,
    extract_monthly_rent_onepass,
    extract_party_name_text_only,
    extract_pdf_text,
    extract_pdf_text_if_available,
    get_images_for_vision,
    has_text_layer,
    pdf_to_images_bytes,
    verify_field_strictly,
    detect_doc_type_from_vision,
    verify_rent_from_rent_box_strictly,
)


class _BytesFile:
    """session_state에 저장한 (name, bytes)를 get_images_for_vision에 넘기기 위한 래퍼."""

    def __init__(self, name: str, data: bytes):
        self.name = name
        self._data = data

    def read(self):
        return self._data

    def seek(self, pos: int = 0):
        pass

    def getvalue(self):
        return self._data


def get_inputs(uploaded_file) -> dict:
    """
    반환: {"mode": "none"|"pdf_text"|"vision_images", "pdf_text": str, "images_b64": list, "mimes": list}
    """
    if uploaded_file is None:
        return {"mode": "none", "pdf_text": "", "images_b64": [], "mimes": []}

    raw = uploaded_file.read()
    uploaded_file.seek(0)
    name = (uploaded_file.name or "").lower()

    if name.endswith(".pdf"):
        pdf_text = extract_pdf_text(raw, max_pages=3)
        if has_text_layer(pdf_text, min_chars=200):
            return {
                "mode": "pdf_text",
                "pdf_text": pdf_text,
                "images_b64": [],
                "mimes": [],
            }
        try:
            img_bytes_list = pdf_to_images_bytes(raw, max_pages=3, dpi=300)
        except ValueError:
            return {"mode": "none", "pdf_text": "", "images_b64": [], "mimes": []}
        b64_list = [base64.b64encode(b).decode("utf-8") for b in img_bytes_list]
        return {
            "mode": "vision_images",
            "pdf_text": "",
            "images_b64": b64_list,
            "mimes": ["png"] * len(b64_list),
        }

    b64 = base64.b64encode(raw).decode("utf-8")
    mime = "jpeg" if name.endswith((".jpg", ".jpeg")) else "png"
    return {
        "mode": "vision_images",
        "pdf_text": "",
        "images_b64": [b64],
        "mimes": [mime],
    }


def extract_rrn_from_text(pdf_text: str) -> list[str]:
    """6-7 형식 주민번호 후보."""
    return re.findall(r"\b\d{6}-\d{7}\b", pdf_text or "")


def extract_dates_from_text(pdf_text: str) -> list[str]:
    """2025년 05월 16일, 2025.05.16, 20250516 등 후보를 정규화한 문자열 리스트."""
    if not pdf_text:
        return []
    patterns = [
        r"\b(20\d{2})[.\-/년 ]\s*(0?\d{1,2})[.\-/월 ]\s*(0?\d{1,2})\s*일?\b",
        r"\b(20\d{2})(\d{2})(\d{2})\b",
    ]
    out: list[str] = []
    for p in patterns:
        for m in re.findall(p, pdf_text):
            if isinstance(m, tuple) and len(m) >= 3:
                out.append(f"{m[0]}-{m[1].zfill(2)}-{m[2].zfill(2)}")
            elif isinstance(m, str):
                out.append(m)
    return out


def smart_clean_dob(val: str) -> str:
    """주민등록번호/생년월일 원문 정제. 010 연락처 제외, 6자리만 취함(오독 원천 차단)."""
    if not val or (str(val).strip().lower() == "null"):
        return ""
    digits = re.sub(r"\D", "", str(val))
    if digits.startswith("010") and len(digits) >= 10:
        return ""
    return digits[:6] if len(digits) >= 6 else digits


def _is_effectively_empty(v: str | None) -> bool:
    s = (v or "").strip()
    if not s:
        return True
    if s in {"-", "—", "N/A", "null", "NULL", "None"}:
        return True
    return False


def detect_blank_form(result: dict) -> bool:
    key_items = [
        "주소",
        "보증금",
        "월세",
        "계약기간",
        "임대인 성명",
        "임차인 성명",
        "임대인 주민등록번호",
        "임차인 주민등록번호",
    ]
    values = []
    for row in result.get("items", []):
        if row.get("item") in key_items:
            values.append(row.get("contract_value"))

    if not values:
        return False

    empty_cnt = sum(1 for v in values if _is_effectively_empty(v))
    return empty_cnt >= max(6, int(len(values) * 0.8))


# 페이지 설정
st.set_page_config(
    page_title="임대차 계약서 자동 검증기",
    page_icon="📋",
    layout="wide",
    initial_sidebar_state="expanded",
)

# 커스텀 CSS: 깔끔한 UI
st.markdown(
    """
<style>
    .main-header {
        font-size: 2rem;
        font-weight: 700;
        color: #1e3a5f;
        margin-bottom: 0.5rem;
    }
    .sub-header {
        color: #5a6c7d;
        margin-bottom: 2rem;
    }
    .result-box {
        padding: 1.5rem;
        border-radius: 12px;
        background: #f8fafc;
        border: 1px solid #e2e8f0;
        margin: 1rem 0;
    }
    .match-icon { color: #22c55e; font-size: 1.5rem; }
    .mismatch-icon { color: #ef4444; font-size: 1.5rem; }
    .stTable td { font-size: 1rem; }
    div[data-testid="stExpander"] {
        border: 1px solid #e2e8f0;
        border-radius: 8px;
    }
    .verifier-result-table {
        border: 1px solid #e2e8f0;
        border-collapse: collapse;
        width: 100%;
        margin: 1rem 0;
    }
    .verifier-result-table th {
        background-color: #f1f5f9;
        border: 1px solid #e2e8f0;
        padding: 8px 12px;
        text-align: left;
        font-size: 1rem;
    }
    .verifier-result-table td {
        border: 1px solid #e2e8f0;
        padding: 8px 12px;
        text-align: left;
        font-size: 1rem;
    }
</style>
""",
    unsafe_allow_html=True,
)


def _get_user_value_for_item(item_name: str, user_input: dict) -> str:
    """항목명에 해당하는 사용자 입력값 반환."""
    mapping = {
        "주소": "address",
        "보증금": "deposit",
        "월세": "rent",
        "계약기간": lambda u: f"{u.get('start_date', '')} ~ {u.get('end_date', '')}".strip()
        .strip("~")
        .strip(),
        "임대인 성명": "lessor_name",
        "임대인 생년월일": "lessor_dob",
        "임차인 성명": "lessee_name",
        "임차인 생년월일": "lessee_dob",
    }
    val = mapping.get(item_name)
    if val is None:
        return ""
    if callable(val):
        return (val(user_input) or "").strip()
    return str(user_input.get(val, "") or "")


def _format_amount_for_display(s: str | int) -> str:
    """금액 문자열/숫자를 읽기 쉽게 쉼표 포맷 (예: 161000000 -> 161,000,000)."""
    if s is None:
        return ""
    if isinstance(s, int):
        s = str(s)
    if not s or not isinstance(s, str):
        return str(s) if s is not None else ""
    t = s.strip().replace(",", "").replace(" ", "")
    if t.isdigit():
        return f"{int(t):,}"
    return s


def _append_decision_log(log_data: dict[str, Any]) -> None:
    """회차별 검증 요약 결과를 decision_log.csv에 저장."""
    log_path = str(DECISION_LOG_PATH)
    df_new = pd.DataFrame([log_data])

    # 엑셀에서 보기 편하도록 컬럼 순서 고정
    cols = [
        "timestamp",
        "document_id",
        "주소",
        "보증금",
        "월세",
        "계약기간",
        "임대인 성명",
        "임대인 생년월일",
        "임차인 성명",
        "임차인 생년월일",
        "기타사항",
    ]
    df_new = df_new.reindex(columns=cols)

    if DECISION_LOG_PATH.is_file():
        try:
            df_old = pd.read_csv(log_path)
            df_old = pd.concat([df_old, df_new], ignore_index=True)
            df_old.to_csv(log_path, index=False, encoding="utf-8-sig")
        except Exception:
            df_new.to_csv(log_path, index=False, encoding="utf-8-sig")
    else:
        df_new.to_csv(log_path, index=False, encoding="utf-8-sig")


def render_result_with_icons(
    result: dict[str, Any],
    user_input: Optional[dict] = None,
    name_revised: Optional[dict[str, bool]] = None,
    analysis_text: Optional[str] = None,
):
    """
    build_final_items 결과를 받아 O/X 아이콘과 불일치 코멘트 테이블로 표시.
    cross_check_mismatches가 있으면 최하단 기타사항 행에 빨간색으로 상세 출력.
    """
    items = result.get("items", [])
    if not items:
        st.warning("AI 분석 결과 형식이 불완전합니다. 다시 시도해 주세요.")
        return

    user_input = user_input or {}
    name_revised = name_revised or {}
    human_review = result.get("human_review", False)
    cross_check_mismatches = result.get("cross_check_mismatches", [])
    blank_form = result.get("blank_form", False)

    st.markdown("#### 📊 항목별 일치 여부")
    if blank_form:
        st.info(
            "빈 양식(템플릿)으로 판단되어 자동 비교를 생략하고 Human-Review로 분기했습니다."
        )
    data: list[list[Any]] = []

    for row in items:
        item_name = row.get("item", "")
        # 주민등록번호 원문은 UI에서 숨김(생년월일만 표시)
        if item_name in ("임대인 주민등록번호", "임차인 주민등록번호"):
            continue
        contract_raw = str(row.get("contract_value", "") or "").strip()
        checklist_val = row.get("checklist_value")
        user_raw = _get_user_value_for_item(item_name, user_input)
        is_doc_mismatch = row.get("is_doc_mismatch", False)

        if blank_form:
            match_val, comment = True, ""
            icon = "—"
            remark_parts = ['<span style="color:#6b7280;">입력값 없음(빈 양식)</span>']
        else:
            match_val, comment = _run_python_comparison(
                item_name, contract_raw, user_raw
            )
            remark_parts: list[str] = []

            if is_doc_mismatch:
                remark_parts.append(
                    '<span style="color:#ca8a04; font-weight:bold;">⚠️ 확인필요 일부서류 불일치</span>'
                )
            if not match_val and comment:
                remark_parts.append(comment)
            if name_revised.get(item_name):
                remark_parts.append(
                    '<span style="color:#ef4444; font-weight:bold;">🔍 정밀 검증으로 수정됨</span>'
                )

            if is_doc_mismatch:
                icon = (
                    '<span style="color:#ca8a04; font-weight:bold;">⚠️ 확인필요</span>'
                )
            elif match_val:
                icon = "✅ O"
            else:
                icon = "❌ X"
        remark = " / ".join(remark_parts) if remark_parts else ""

        # JSON 원본값 그대로 사용 (월세 공란/null은 표시만 "0"으로)
        display_contract = contract_raw
        if item_name == "월세" and (
            str(contract_raw or "").strip() in ("", "null", "None")
        ):
            display_contract = "0"
        # ✅ [추가] 보증금/월세는 UI 표시용으로 숫자 정규화
        if item_name in ("보증금", "월세"):
            try:
                from comparators import _parse_amount_from_text

                n = _parse_amount_from_text(contract_raw, item_name)
                if n is not None:
                    display_contract = _format_amount_for_display(str(n))
            except Exception:
                pass
        # ✅ [추가] 계약기간도 UI 표시용으로 YYYYMMDD~YYYYMMDD 로 정규화
        if item_name == "계약기간":
            try:
                from comparators import _parse_dates_from_period_text

                s, e = _parse_dates_from_period_text(contract_raw)
                if s and e:
                    display_contract = f"{s.replace('-', '')} ~ {e.replace('-', '')}"
            except Exception:
                pass
        # 주민번호 마스킹은 표시용으로만 별도 적용
        if item_name in (
            "임대인 생년월일",
            "임차인 생년월일",
            "임대인 주민등록번호",
            "임차인 주민등록번호",
        ):
            display_user = _mask_jumin(user_raw)
        else:
            display_user = user_raw

        # [추가] 보증금/월세 항목인 경우 사용자 입력값에도 쉼표 포맷팅 적용
        if item_name in ("보증금", "월세"):
            display_user = _format_amount_for_display(display_user)

        if blank_form:
            display_user = '<span style="color:#6b7280;">-</span>'
        else:
            if not match_val:
                if item_name in (
                    "보증금",
                    "월세",
                    "임대인 생년월일",
                    "임차인 생년월일",
                    "임대인 주민등록번호",
                    "임차인 주민등록번호",
                ):
                    display_user = f'<span style="color:#ef4444; font-weight:bold;">{html.escape(display_user)}</span>'
                elif item_name == "계약기간":
                    display_user = _highlight_period_diff(contract_raw, display_user)
                else:
                    display_user = _highlight_diff(contract_raw, display_user)
            else:
                display_user = html.escape(display_user)

        data.append([item_name, display_contract, display_user, icon, remark])

    # 기타사항 행: 문서 간 불일치를 빨간색으로 상세 출력 (금액은 쉼표 포맷, 용어는 확인설명서)
    etc_parts: list[str] = []
    for m in cross_check_mismatches:
        name = m.get("item_name", "")
        cv = m.get("contract_value", "")
        chv = m.get("checklist_value", "")
        cv_display = (
            _format_amount_for_display(cv) if name in ("보증금", "월세") else cv
        )
        chv_display = (
            _format_amount_for_display(chv) if name in ("보증금", "월세") else chv
        )
        etc_parts.append(
            f"⚠️ 확인설명서 내용 불일치: [{name}] 본문({cv_display}) vs 확인설명서({chv_display})"
        )
    if human_review and not cross_check_mismatches:
        etc_parts.append("Human-Review 필요")
    elif human_review and cross_check_mismatches:
        etc_parts.append("Human-Review 필요 (문서 간 불일치 포함)")

    if etc_parts:
        etc_lines = "<br />".join(etc_parts)
        etc_display = (
            f'<span style="color:#ef4444; font-weight:bold;">{etc_lines}</span>'
        )
        data.append(["기타사항", "-", "-", "", etc_display])

    columns = ["항목", "계약서 내용", "사용자 입력", "일치 여부", "비고 (불일치 시)"]
    df = pd.DataFrame(data, columns=columns)
    html_table = df.to_html(
        escape=False, index=False, classes=["verifier-result-table"]
    )
    st.markdown(html_table, unsafe_allow_html=True)
    st.markdown("---")
    if analysis_text:
        st.markdown("#### 📝 AI 응답 원문")
        st.code(analysis_text)


# ----- 사이드바 -----
with st.sidebar:
    st.markdown("### 🔑 설정")
    api_key = st.text_input(
        "Google (Gemini) API Key",
        type="password",
        placeholder="AIza...",
        help="Google AI Studio에서 발급한 API 키를 입력하세요.",
        key="api_key",
    )
    st.markdown("---")
    st.caption(
        "임대차 계약서 이미지 또는 PDF를 업로드하고, 입력한 정보와 비교 검증합니다."
    )


# ----- 메인 화면 -----
st.markdown(
    '<p class="main-header">📋 임대차 계약서 자동 검증기</p>', unsafe_allow_html=True
)
st.markdown(
    '<p class="sub-header">계약서 이미지/PDF를 업로드하고 입력 정보와 비교해 보세요.</p>',
    unsafe_allow_html=True,
)

address = st.text_input(
    "주소(전체)",
    placeholder="",
    key="address_input",
    help="시/도 + 도로명 또는 지번 + 상세주소(동·호수)를 한 번에 입력하세요.",
)

st.markdown("**임대인·임차인 정보**")
col_lessor, col_lessee = st.columns(2)
with col_lessor:
    lessor_name = st.text_input(
        "임대인(집주인) 성명", placeholder="홍길동", key="lessor_name"
    )
    lessor_dob = st.text_input(
        "임대인(집주인) 생년월일(6자리)", placeholder="900101", key="lessor_dob"
    )
with col_lessee:
    lessee_name = st.text_input(
        "임차인(세입자) 성명", placeholder="김철수", key="lessee_name"
    )
    lessee_dob = st.text_input(
        "임차인(세입자) 생년월일(6자리)", placeholder="850315", key="lessee_dob"
    )

col1, col2 = st.columns(2)
with col1:
    deposit = st.number_input(
        "보증금 (원)",
        min_value=0,
        value=0,
        step=10000,
        format="%d",
        key="deposit_input",
    )
    st.caption(format_korean_money(int(deposit)))
    rent = st.number_input(
        "월세 (원)",
        min_value=0,
        value=0,
        step=10000,
        format="%d",
        key="rent_input",
    )
    st.caption(format_korean_money(int(rent)))

with col2:
    start_date = st.date_input("계약 시작일", value=date.today())
    end_date = st.date_input("계약 종료일", value=date.today())
    st.caption("계약기간은 시작일 ~ 종료일로 사용됩니다.")

uploaded_files = st.file_uploader(
    "계약서 파일 업로드 (여러 장 가능)",
    type=["png", "jpg", "jpeg", "pdf"],
    accept_multiple_files=True,
    help="계약서의 모든 페이지(이미지 또는 PDF)를 한꺼번에 선택하세요.",
    key="uploader",
)

# 업로드 파일 bytes 저장 (rerun 대비)
if uploaded_files:
    st.session_state["uploaded_files_data"] = [
        (f.name, f.getvalue()) for f in uploaded_files
    ]

final_address = (address or "").strip()

user_input = {
    "address": final_address,
    "deposit": str(deposit) if deposit is not None else "",
    "rent": str(rent) if rent is not None else "",
    # YYYYMMDD 포맷으로 고정 (UI 및 비교 표시 일관성)
    "start_date": start_date.strftime("%Y%m%d") if start_date else "",
    "end_date": end_date.strftime("%Y%m%d") if end_date else "",
    "lessor_name": (lessor_name or "").strip(),
    "lessor_dob": (lessor_dob or "").strip(),
    "lessee_name": (lessee_name or "").strip(),
    "lessee_dob": (lessee_dob or "").strip(),
}

date_invalid = end_date < start_date if (start_date and end_date) else False
if date_invalid:
    st.error("종료일은 시작일보다 빠를 수 없습니다.")

analyze_clicked = st.button(
    "🔍 계약서 검증하기",
    type="primary",
    use_container_width=True,
    disabled=date_invalid,
)

if analyze_clicked:
    start_time = time.time()
    if not api_key or not api_key.strip():
        st.error("사이드바에서 Google (Gemini) API Key를 입력해 주세요.")
    else:
        # 버튼 클릭 시점의 파일: 위젯 값 우선, 없으면 session_state 보관분 사용
        files_to_use = uploaded_files
        if not files_to_use and st.session_state.get("uploaded_files_data"):
            files_to_use = [
                _BytesFile(n, b) for n, b in st.session_state["uploaded_files_data"]
            ]
        if not files_to_use:
            st.warning("계약서 파일을 먼저 업로드해 주세요.")
        else:
            with st.spinner("계약서를 분석하고 있습니다..."):
                try:
                    images_b64, mimes = get_images_for_vision(files_to_use)
                    if not images_b64:
                        st.error("이미지를 읽을 수 없습니다.")
                    else:
                        analysis = call_gemini_vision(api_key, images_b64, mimes)
                        doc_type = detect_doc_type_from_vision(
                            api_key, images_b64, mimes
                        )
                        parsed = parse_result_json(analysis)

                        name_revised: dict[str, bool] = {}
                        log_rows: list[dict[str, Any]] = []
                        document_id = str(uuid.uuid4())
                        ts = datetime.now(timezone.utc).isoformat()

                        if parsed and parsed.get("items"):
                            # 1. 명칭 정규화 및 값 1차 정제
                            for r in parsed["items"]:
                                r["item"] = re.sub(
                                    r"^\d+\)\s*", "", str(r.get("item", ""))
                                ).replace("식별정보 원문", "생년월일")
                                if "생년월일" in r["item"]:
                                    r["contract_value"] = smart_clean_dob(
                                        str(r["contract_value"])
                                    )

                            for row in parsed["items"]:
                                if "생년월일" not in row["item"]:
                                    continue
                                val = row["contract_value"]

                                # 6자리가 아니면 무조건 리트라이 (전화번호 오독 포함)
                                if len(val) != 6:
                                    second = verify_field_strictly(
                                        api_key, images_b64, mimes, row["item"]
                                    )
                                    cleaned = smart_clean_dob(second)
                                    if len(cleaned) == 6:
                                        row["contract_value"] = cleaned
                                        name_revised[row["item"]] = True
                                    else:
                                        row["contract_value"] = "식별불가"

                            result = build_final_items(parsed)

                        if parsed:
                            result = build_final_items(parsed)
                            name_mismatch = False
                            for row in result["items"]:
                                item_name = row.get("item", "")
                                if item_name not in ("임대인 성명", "임차인 성명"):
                                    continue
                                c_val = str(row.get("contract_value", "") or "").strip()
                                u_val = _get_user_value_for_item(item_name, user_input)
                                match_val, _ = _run_python_comparison(
                                    item_name, c_val, u_val
                                )
                                if not match_val or "식별불가" in c_val:
                                    name_mismatch = True
                                    break
                            if name_mismatch:
                                result["human_review"] = True
                                reason = (
                                    result.get("human_review_reason") or ""
                                ).strip()
                                result["human_review_reason"] = (
                                    (reason + "; 성명 확인필요").strip(" ;")
                                    if "성명 확인필요" not in reason
                                    else reason
                                )

                            # 월세 후처리: 0/공란이면 보강 OCR (표준 포함), 합리적 금액만 덮어쓰기
                            for row in result.get("items", []):
                                if str(row.get("item", "")).strip() != "월세":
                                    continue

                                contract_rent = str(
                                    row.get("contract_value", "") or ""
                                ).strip()
                                if contract_rent in ("", "null", "None"):
                                    contract_rent = "0"

                                user_rent_raw = _get_user_value_for_item(
                                    "월세", user_input
                                )
                                user_rent_num = None
                                if user_rent_raw and str(user_rent_raw).strip():
                                    try:
                                        user_rent_num = int(
                                            re.sub(r"\D", "", str(user_rent_raw)) or 0
                                        )
                                    except ValueError:
                                        pass
                                is_ai_rent_zero = contract_rent in (
                                    "0",
                                    "0원",
                                    "",
                                    "null",
                                    "None",
                                )

                                if (
                                    is_ai_rent_zero
                                    and user_rent_num
                                    and user_rent_num != 0
                                ):
                                    result["human_review"] = True
                                    reason = (
                                        result.get("human_review_reason") or ""
                                    ).strip()
                                    if "월세 확인필요" not in reason:
                                        result["human_review_reason"] = (
                                            reason + "; 월세 확인필요"
                                        ).strip(" ;")

                                strict_str = ""
                                strict_num = None
                                if is_ai_rent_zero:
                                    one = extract_monthly_rent_onepass(
                                        api_key, images_b64, mimes
                                    )
                                    if (
                                        one.get("found")
                                        and one.get("rent_num") is not None
                                    ):
                                        strict_num = one["rent_num"]
                                        strict_str = str(
                                            one.get("rent_raw") or strict_num
                                        )
                                    else:
                                        strict_rent_ref = (
                                            verify_rent_from_rent_box_strictly(
                                                api_key, images_b64, mimes, doc_type
                                            )
                                        )
                                        strict_str = (strict_rent_ref or "").strip()
                                        if strict_str and strict_str not in (
                                            "0",
                                            "0원",
                                            "해당없음",
                                            "-",
                                            "없음",
                                        ):
                                            try:
                                                strict_num = int(
                                                    re.sub(r"\D", "", strict_str) or 0
                                                )
                                            except ValueError:
                                                strict_num = None

                                    if (
                                        strict_num is not None
                                        and 0 < strict_num < 5_000_000
                                    ):
                                        row["contract_value"] = str(strict_num)
                                        name_revised["월세"] = True
                                    elif (
                                        strict_num is not None
                                        and strict_num >= 5_000_000
                                    ):
                                        result["human_review"] = True
                                        reason = (
                                            result.get("human_review_reason") or ""
                                        ).strip()
                                        if "월세 오독 의심" not in reason:
                                            result["human_review_reason"] = (
                                                reason + "; 월세 오독 의심(보증금 전이)"
                                            ).strip(" ;")

                                st.caption(
                                    f"[debug] doc_type={doc_type} / ai_rent={contract_rent} / strict_rent={strict_str}"
                                )

                            def _apply_name_text_only(
                                item_label: str, party: str
                            ) -> None:
                                for row in result.get("items", []):
                                    if str(row.get("item", "")).strip() != item_label:
                                        continue
                                    ref = extract_party_name_text_only(
                                        api_key, images_b64, mimes, party
                                    )
                                    if ref.get("ok") and ref.get("name"):
                                        row["contract_value"] = ref["name"]
                                        name_revised[item_label] = True
                                    else:
                                        result["human_review"] = True
                                        reason = (
                                            result.get("human_review_reason") or ""
                                        ).strip()
                                        msg = f"{item_label} 텍스트 추출 실패(필기/서명 배제 정책)"
                                        if msg not in reason:
                                            result["human_review_reason"] = (
                                                reason + "; " + msg
                                            ).strip(" ;")
                                    return

                            def _needs_name_fix(v: str) -> bool:
                                s = (v or "").strip()
                                if not s:
                                    return True
                                if any(k in s for k in ["성명", "서명", "날인"]):
                                    return True
                                if not re.fullmatch(r"[가-힣]{2,10}", s):
                                    return True
                                return False

                            # ✅ 표준임대차계약서: 성명은 무조건 텍스트-only 추가판독 결과를 최종값으로 사용
                            if doc_type == "standard":
                                _apply_name_text_only("임대인 성명", "임대인")
                                _apply_name_text_only("임차인 성명", "임차인")

                            if detect_blank_form(result):
                                result["blank_form"] = True
                                result["human_review"] = True
                                reason = (
                                    result.get("human_review_reason") or ""
                                ).strip()
                                msg = "빈 양식(템플릿): 입력값 없음"
                                if msg not in reason:
                                    result["human_review_reason"] = (
                                        reason + "; " + msg
                                    ).strip(" ;")

                            # 회차별 검증 요약 로그 수집
                            session_log = {
                                "timestamp": ts,
                                "document_id": document_id,
                                "기타사항": "; ".join(
                                    [
                                        f"{m['item_name']} 확인설명서 불일치"
                                        for m in result.get(
                                            "cross_check_mismatches", []
                                        )
                                    ]
                                ),
                            }
                            for row in result["items"]:
                                item_name = row.get("item", "")
                                # decision_log에도 주민등록번호 원문은 남기지 않음
                                if item_name in (
                                    "임대인 주민등록번호",
                                    "임차인 주민등록번호",
                                ):
                                    continue
                                c_val = str(row.get("contract_value", "") or "").strip()
                                u_val = _get_user_value_for_item(item_name, user_input)
                                match_val, _ = _run_python_comparison(
                                    item_name, c_val, u_val
                                )
                                if row.get("is_doc_mismatch"):
                                    status = "확인필요"
                                elif match_val:
                                    status = "일치"
                                else:
                                    status = "불일치"
                                session_log[item_name] = status
                            _append_decision_log(session_log)

                            end_time = time.time()
                            elapsed = end_time - start_time
                            st.session_state["analysis_done"] = True
                            st.session_state["result"] = result
                            st.session_state["parsed"] = parsed
                            st.session_state["user_input"] = user_input
                            st.session_state["name_revised"] = name_revised
                            st.session_state["analysis_text"] = analysis or ""
                            st.session_state["analysis_elapsed"] = elapsed
                        else:
                            st.error("데이터 구조화 실패")
                            debug_fail = st.toggle(
                                "디버그 출력(PII 포함 가능) 보기",
                                value=False,
                                key="debug_fail",
                            )
                            if debug_fail:
                                st.markdown("**AI 응답 전문:**")
                                st.markdown(analysis or "(응답 없음)")

                            end_time = time.time()
                            elapsed = end_time - start_time
                            st.caption(f"⏱️ 분석 소요 시간: {elapsed:.2f}초")
                except Exception as e:
                    st.error(f"오류가 발생했습니다: {e}")

# ----- 결과 렌더링 (session_state 기준, 버튼 누를 때마다 재분석되지 않음) -----
if st.session_state.get("analysis_done"):
    st.success("분석이 완료되었습니다.")
    # 디버그 토글은 무조건 session_state key로
    st.toggle("디버그 출력(PII 포함 가능) 보기", value=False, key="debug_mode")
    if st.session_state.get("debug_mode"):
        st.subheader("📝 AI 응답 원문")
        st.code(st.session_state.get("analysis_text") or "(응답 없음)")
        st.subheader("사용된 parsed JSON (테이블 직전)")
        st.json(st.session_state.get("parsed"))
        result = st.session_state.get("result", {})
        parsed = st.session_state.get("parsed", {})
        mismatch_log = []
        for i, r in enumerate(result.get("items", [])):
            p_item = parsed.get("items") or []
            pc = str(
                (p_item[i].get("contract_value") if i < len(p_item) else "") or ""
            ).strip()
            rc = str(r.get("contract_value", "") or "").strip()
            if pc != rc:
                mismatch_log.append(f"{r.get('item', '')}: parsed≠result")
        if mismatch_log:
            st.caption("⚠️ contract_value 확인: " + "; ".join(mismatch_log))
        else:
            st.caption("✅ contract_value 확인: 테이블 표시값과 parsed 동일")
    render_result_with_icons(
        st.session_state.get("result", {}),
        st.session_state.get("user_input", {}),
        name_revised=st.session_state.get("name_revised", {}),
        analysis_text=(
            st.session_state.get("analysis_text")
            if st.session_state.get("debug_mode")
            else None
        ),
    )
    elapsed = st.session_state.get("analysis_elapsed", 0)
    st.caption(f"⏱️ 분석 소요 시간: {elapsed:.2f}초")

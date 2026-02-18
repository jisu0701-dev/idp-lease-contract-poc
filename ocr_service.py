# -*- coding: utf-8 -*-
import base64
import json
import re
import google.generativeai as genai
from typing import Any, Optional

try:
    import fitz

    HAS_PYMUPDF = True
except ImportError:
    HAS_PYMUPDF = False

ENABLE_HIGHRES_NAME_OCR = True


def pdf_to_images_bytes(
    pdf_bytes: bytes, max_pages: int = 3, dpi: int = 150
) -> list[bytes]:
    if not HAS_PYMUPDF:
        raise ValueError("PDF 처리를 위해 pymupdf를 설치해 주세요: pip install pymupdf")
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    result: list[bytes] = []
    for i in range(min(len(doc), max_pages)):
        page = doc[i]
        pix = page.get_pixmap(dpi=dpi)
        result.append(pix.tobytes("png"))
    doc.close()
    return result


def extract_pdf_text(pdf_bytes: bytes, max_pages: int = 3) -> str:
    if not HAS_PYMUPDF:
        return ""
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    texts = []
    for i in range(min(len(doc), max_pages)):
        t = (doc[i].get_text("text") or "").strip()
        if t:
            texts.append(t)
    doc.close()
    return "\n".join(texts).strip()


def has_text_layer(pdf_text: str, min_chars: int = 200) -> bool:
    """텍스트 레이어 존재 판단 (너무 짧으면 스캔본으로 간주)."""
    return len((pdf_text or "").strip()) >= min_chars


def extract_pdf_text_if_available(pdf_bytes: bytes, min_chars: int = 200) -> str:
    """
    전자계약 PDF처럼 텍스트 레이어가 있는 경우, PyMuPDF로 텍스트를 직접 추출.
    min_chars 이상이면 '텍스트가 있다'고 판단.
    """
    text = extract_pdf_text(pdf_bytes, max_pages=3)
    return text if has_text_layer(text, min_chars) else ""


def get_images_for_vision(files):
    files = sorted(files, key=lambda f: (f.name or ""))
    b64s, mimes = [], []
    for f in files:
        raw = f.read()
        f.seek(0)
        name = (f.name or "").lower()
        if name.endswith(".pdf"):
            for b in pdf_to_images_bytes(raw, 12):
                b64s.append(base64.b64encode(b).decode("utf-8"))
                mimes.append("png")
        else:
            b64s.append(base64.b64encode(raw).decode("utf-8"))
            mimes.append("jpeg" if name.endswith((".jpg", ".jpeg")) else "png")
    return b64s, mimes


def _pick_pages(b64s, mimes, idxs):
    return [b64s[i] for i in idxs], [mimes[i] for i in idxs]


def detect_rent_page_index(
    api_key: str, b64s: list[str], mimes: list[str]
) -> int | None:
    """
    월임대료/월차임 표가 있을 확률이 높은 페이지 index를 반환.
    비용 절감을 위해 페이지별로 짧은 판별만 수행.
    """
    genai.configure(api_key=api_key.strip())
    model = genai.GenerativeModel("gemini-2.0-flash")

    judge_prompt = (
        "이 페이지에 '임대보증금'과 '월임대료(월차임)'가 같은 표(계약조건 표) 안에 함께 기재되어 있으면 1, 아니면 0. "
        "반드시 0 또는 1만 출력."
    )

    best_idx = None
    for i in range(len(b64s)):
        parts = [
            judge_prompt,
            {"inline_data": {"mime_type": f"image/{mimes[i]}", "data": b64s[i]}},
        ]
        try:
            res = model.generate_content(parts, generation_config={"temperature": 0})
            out = (res.text or "").strip()
        except Exception:
            out = ""

        if out == "1":
            best_idx = i
            break

    return best_idx


def extract_monthly_rent_onepass(
    api_key: str, b64s: list[str], mimes: list[str]
) -> dict:
    """
    1회 호출로:
    - 월임대료 표가 있는 페이지인지 판별
    - 있으면 월임대료 금액(숫자)만 추출
    반환 예:
      {"found": True, "page_index": 1, "rent_raw": "₩1,050,000", "rent_num": 1050000}
      {"found": False, "page_index": None, "rent_raw": "", "rent_num": None}
    """
    genai.configure(api_key=api_key.strip())
    model = genai.GenerativeModel("gemini-2.0-flash")

    prompt = (
        "너는 임대차계약서 페이지에서 '월임대료(월차임)'를 추출하는 엔진이다.\n"
        "규칙:\n"
        "1) 이 페이지에 '임대보증금'과 '월임대료(월차임)'가 같은 표(계약조건 표) 안에 함께 있으면 found=true, 아니면 found=false.\n"
        "2) found=true인 경우에만 월임대료 금액을 rent_raw에 그대로 적고, rent_num에는 숫자만(원 단위 정수) 적어라.\n"
        "3) 월임대료가 '없음/0/해당없음'이면 rent_num은 0.\n"
        "4) 절대로 임대보증금 금액을 월임대료로 쓰지 마라.\n"
        "5) 출력은 반드시 JSON 1줄만. 키는 found,page_index,rent_raw,rent_num.\n"
        '예시: {"found":true,"page_index":2,"rent_raw":"₩1,050,000","rent_num":1050000}\n'
        '예시: {"found":false,"page_index":null,"rent_raw":"","rent_num":null}'
    )

    for i in range(len(b64s)):
        parts = [
            prompt,
            {"inline_data": {"mime_type": f"image/{mimes[i]}", "data": b64s[i]}},
        ]
        try:
            res = model.generate_content(parts, generation_config={"temperature": 0})
            out = (res.text or "").strip()
        except Exception:
            out = ""

        m = re.search(r"\{.*\}", out, flags=re.DOTALL)
        if not m:
            continue
        js = m.group(0)

        found = bool(re.search(r"\"found\"\s*:\s*true", js, re.IGNORECASE))
        if not found:
            continue

        page_index = i
        rent_num = None
        m_num = re.search(r"\"rent_num\"\s*:\s*(null|\d+)", js, re.IGNORECASE)
        if m_num:
            v = m_num.group(1)
            rent_num = None if v.lower() == "null" else int(v)

        rent_raw = ""
        m_raw = re.search(r"\"rent_raw\"\s*:\s*\"(.*?)\"", js, re.DOTALL)
        if m_raw:
            rent_raw = m_raw.group(1)

        if rent_num is None and rent_raw:
            digits = re.sub(r"\D", "", rent_raw)
            if digits:
                rent_num = int(digits)

        return {
            "found": True,
            "page_index": page_index,
            "rent_raw": rent_raw,
            "rent_num": rent_num,
        }

    return {"found": False, "page_index": None, "rent_raw": "", "rent_num": None}


def extract_party_name_text_only(
    api_key: str,
    b64s: list[str],
    mimes: list[str],
    party: str,  # "임대인" or "임차인"
) -> dict:
    """
    성명은 인쇄/타이핑 텍스트만 채택. 서명/필기/인감 배제.
    텍스트가 없거나 불확실하면 ok=false로 반환(=HR 유도).
    """
    assert party in ("임대인", "임차인")

    genai.configure(api_key=api_key.strip())
    model = genai.GenerativeModel("gemini-2.0-flash")

    prompt = (
        f"너는 임대차계약서에서 '{party} 성명(법인명)'을 추출한다.\n"
        "규칙:\n"
        "1) 반드시 '성명(법인명)' 입력칸 안의 인쇄/타이핑된 텍스트만 읽어라.\n"
        "2) 서명/필기/인감 글자는 절대 참고하지 마라.\n"
        "3) 인쇄/타이핑 텍스트가 없거나 값이 불확실하면 ok=false로 반환해라.\n"
        '4) 출력은 JSON 한 줄만: {"ok":true|false,"name":"..."}\n'
        '예: {"ok":true,"name":"홍길동"}\n'
        '예: {"ok":false,"name":""}'
    )

    for i in range(len(b64s)):
        parts = [
            prompt,
            {"inline_data": {"mime_type": f"image/{mimes[i]}", "data": b64s[i]}},
        ]
        try:
            res = model.generate_content(parts, generation_config={"temperature": 0})
            out = (res.text or "").strip()
        except Exception:
            out = ""

        m = re.search(r"\{.*\}", out, flags=re.DOTALL)
        if not m:
            continue
        js = m.group(0)

        ok = bool(re.search(r"\"ok\"\s*:\s*true", js, re.IGNORECASE))
        if not ok:
            continue

        m_name = re.search(r"\"name\"\s*:\s*\"(.*?)\"", js, re.DOTALL)
        name = (m_name.group(1).strip() if m_name else "").strip()

        # 라벨/공백 제거
        name = re.sub(r"(성명|법인명|서명|날인|\s)", "", name)

        # 최소 검증(한글 이름 기준; 법인명까지 필요하면 규칙 확장)
        if re.fullmatch(r"[가-힣]{2,10}", name):
            return {"ok": True, "name": name}

    return {"ok": False, "name": ""}


GEMINI_VISION_PROMPT = """당신은 임대차 계약서의 데이터를 픽셀 단위로 전사하는 정밀 OCR 엔진입니다.

**[데이터 판독 절대 원칙]**
1. **주소(지번 사수)**:
   - '석촌동 8-13' 처럼 동 이름 바로 뒤에 나오는 **지번 숫자**를 절대로 누락하지 마십시오.
   - 건물명(아파트명)을 추측하거나 익숙한 이름으로 자동 완성하지 마십시오. 이미지에 적힌 글자 그대로 한 자 한 자 똑같이 전사하십시오.
2. **보증금 및 월세 (자릿수 엄수)**:
   - 보증금과 월세는 서로 다른 칸에 있습니다. 위 칸의 숫자를 아래 칸으로 가져오는 '전이 오류'를 범하지 마십시오.
   - 월세 칸에 숫자가 없거나 '해당없음', '-' 표시가 있다면 반드시 **"0"**으로 출력하십시오. 임의로 숫자를 만들어내지 마십시오.
3. **서류 교차 검증 (중요: 오검출 금지)**:
   - 첨부된 이미지 중 **페이지 상단 제목에 정확히 '중개대상물 확인·설명서'** 라고 적힌 페이지만 확인설명서로 인정하십시오.
     (본문에 '확인·설명서' 문구가 있어도 제목이 아니면 절대 확인설명서로 보지 마십시오.)
   - 확인설명서 페이지가 **없으면**, 모든 항목의 `checklist_value`는 반드시 **null** 입니다.
   - 확인설명서가 **있을 때만**, 그 문서의 소재지(주소)·거래예정금액(보증금)을 `checklist_value`에 넣으십시오.
   - 확인설명서가 없는데 `checklist_value`를 채우면 오답입니다.

4. **'주소'의 정의(가장 중요)**:
   - "주소"는 **임차목적물(주택 소재지)** 주소입니다.
   - **표준임대차계약서 1페이지**의 "임대사업자/임차인 주소(현주소)"는 절대로 쓰지 마십시오.
   - 아래 중 하나의 위치에서만 주소를 뽑으십시오:
     - "민간임대주택의 표시" 섹션의 **"주택 소재지"**
     - "임차목적물의 소재지", "주택 소재지" 같은 명시적 헤딩
   - 만약 위 위치에서 찾지 못하면 `contract_value`를 null로 두십시오(추측 금지).

5. **월세 추출 규칙(오독 방지)**:
   - 표준임대차계약서의 월세는 2페이지 "계약조건" 표의 **"월임대료"** 칸에 있습니다.
   - "월임대료" 칸에 금액이 있으면 반드시 그 값을 그대로 전사하십시오(예: 금오만원정(₩50,000)).
   - 월임대료 칸이 비어있거나 '해당없음/-'일 때만 "0"으로 출력하십시오.

**[출력 항목]**
주소, 보증금, 월세, 계약기간, 임대인 성명, 임대인 주민등록번호, 임차인 성명, 임차인 주민등록번호

{"items": [{"item": "항목명", "contract_value": "값", "checklist_value": "확인설명서값"}]} JSON 구조로만 출력하십시오."""


# 텍스트(OCR 결과) 기반 추출용 프롬프트 (이미지 대신 [PAGE N] 텍스트 입력 시 사용)
TEXT_EXTRACT_PROMPT = """
You are a precise document extraction engine.

You will be given OCR text of multiple pages from a rental contract package.

Your job is to extract ONLY the following fields and return JSON.

Return JSON only in this exact shape:
{{
  "items": [
    {{"item": "주소", "contract_value": "...", "checklist_value": "..."}},
    {{"item": "보증금", "contract_value": "...", "checklist_value": "..."}},
    {{"item": "월세", "contract_value": "...", "checklist_value": "..."}},
    {{"item": "계약기간", "contract_value": "...", "checklist_value": "..."}},
    {{"item": "임대인 성명", "contract_value": "...", "checklist_value": "..."}},
    {{"item": "임대인 주민등록번호", "contract_value": "...", "checklist_value": "..."}},
    {{"item": "임차인 성명", "contract_value": "...", "checklist_value": "..."}},
    {{"item": "임차인 주민등록번호", "contract_value": "...", "checklist_value": "..."}}
  ]
}}

CRITICAL RULES:
1) contract_value MUST come from the rental contract itself ("임대차계약서", "표준임대차계약서", "전자계약서" etc).
2) checklist_value MUST come ONLY from a page that is CLEARLY the "중개대상물 확인·설명서".
   - Treat it as present ONLY if a page title/header contains the exact phrase "중개대상물 확인·설명서"
     (or an unmistakable equivalent like "중개대상물 확인·설명서(…)" at the top).
   - If such a page is NOT present, checklist_value for ALL items MUST be null.
   - NEVER reuse values from the rental contract pages as checklist_value.
3) If a value does not exist or is not readable, set it to null. Do not guess.

ADDRESS EXTRACTION (VERY IMPORTANT):
4) The item "주소" means the RENTED PROPERTY address (임차목적물/주택 소재지), NOT the landlord/tenant's current address.
   - On "표준임대차계약서", page 1 often contains the parties' addresses (임대사업자/임차인 '주소').
     DO NOT use those for "주소".
   - Prefer the address under headings like:
     * "주택 소재지"
     * "임차목적물의 소재지"
     * "민간임대주택의 표시" section → "주택 소재지"
     * Any table/row explicitly describing the dwelling being leased
   - If multiple candidate addresses exist, choose the one explicitly tied to the dwelling (주택/임차목적물),
     and ignore addresses tied to persons (임대인/임차인 주소).

INPUT FORMAT:
You will receive text grouped by page, like:
[PAGE 1]
...
[PAGE 2]
...

Now extract the fields.
"""


def call_gemini_vision(api_key, b64s, mimes):
    genai.configure(api_key=api_key.strip())
    model = genai.GenerativeModel("gemini-2.0-flash")
    parts = [GEMINI_VISION_PROMPT]
    for i, b in enumerate(b64s):
        parts.append({"inline_data": {"mime_type": f"image/{mimes[i]}", "data": b}})
    res = model.generate_content(parts, generation_config={"temperature": 0})
    return res.text if res.text else ""


def verify_field_strictly(api_key, b64s, mimes, item_name):
    role = "임대인" if "임대인" in item_name else "임차인"
    prompt = (
        f"[{role}]의 '주민등록번호' 칸만 보고 "
        "하이픈 포함 모든 숫자를 그대로 전사하라. "
        "전화번호(010-xxxx-xxxx), 계좌번호, 다른 숫자는 절대 쓰지 마라. "
        "출력은 반드시 한 줄로 '######-#######' 형식만."
    )

    genai.configure(api_key=api_key.strip())
    model = genai.GenerativeModel("gemini-2.0-flash")
    parts = [prompt]
    for i, b in enumerate(b64s):
        parts.append({"inline_data": {"mime_type": f"image/{mimes[i]}", "data": b}})
    res = model.generate_content(parts, generation_config={"temperature": 0})

    out = (res.text or "").strip().split("\n")[0].strip()
    if not out:
        return "식별불가"

    # 공백 제거
    out = re.sub(r"\s+", "", out)
    # 숫자/하이픈 외 제거
    out = re.sub(r"[^0-9\-]", "", out)

    m = re.search(r"(\d{6}-\d{7})", out)
    if m:
        return m.group(1)

    return "식별불가"


def verify_monthly_rent_strictly(api_key, b64s, mimes):
    prompt = """
표준임대차계약서 2페이지 '계약조건' 표에서
'월임대료' 칸의 금액만 정확히 읽어라.
숫자와 괄호 안 금액을 그대로 전사하라.
값이 있으면 절대 0으로 쓰지 마라.
없을 때만 0을 출력하라.
JSON 없이 값만 출력.
"""
    genai.configure(api_key=api_key.strip())
    model = genai.GenerativeModel("gemini-2.0-flash")
    parts = [prompt]
    for i, b in enumerate(b64s):
        parts.append({"inline_data": {"mime_type": f"image/{mimes[i]}", "data": b}})
    res = model.generate_content(parts, generation_config={"temperature": 0})
    return res.text.strip() if res.text else "0"


def detect_doc_type_from_vision(api_key: str, b64s: list[str], mimes: list[str]) -> str:
    """
    문서 타입만 판별: "standard"=표준임대차계약서, "econtract"=부동산전자계약서, "unknown"
    - 다중 페이지 중 1~2페이지만 사용(비용 절감)
    """
    genai.configure(api_key=api_key.strip())
    model = genai.GenerativeModel("gemini-2.0-flash")

    prompt = """
다음 이미지들은 임대차 계약서 패키지 일부다.
문서 타입을 아래 셋 중 하나로만 답하라.

- standard : '표준임대차계약서' / '민간임대주택' / '민간임대주택의 표시' 같은 문구가 있는 표준 양식
- econtract : '부동산전자계약서' / '전자계약서' / '부동산(주거용) 임대차전자계약서' 같은 문구가 있는 전자계약 양식
- unknown : 위 둘로 확정 불가

정답은 오직 한 단어로만 출력.
"""

    parts = [prompt]
    for i, b in enumerate(b64s[:2]):
        parts.append({"inline_data": {"mime_type": f"image/{mimes[i]}", "data": b}})
    res = model.generate_content(parts, generation_config={"temperature": 0})
    out = (res.text or "").strip().lower()
    if "standard" in out:
        return "standard"
    if "econtract" in out:
        return "econtract"
    return "unknown"


def verify_rent_from_rent_box_strictly(api_key: str, b64s, mimes, doc_type: str) -> str:
    """
    참고용(의심 판단): 월세/차임 칸만 읽어 반환. 최종 월세 확정에는 사용하지 않음.
    - econtract: '차임'/'월차임' 라벨 옆 칸만
    - standard/unknown: '월임대료' 칸만
    같은 줄/같은 박스에 보증금·계약금·잔금이 있어도 월세로 가져오지 않는다.
    """
    genai.configure(api_key=api_key.strip())
    model = genai.GenerativeModel("gemini-2.0-flash")

    if doc_type == "econtract":
        target_rule = """
전자계약서 양식이다.
반드시 '월세' / '차임' / '월 임대료' 라벨이 붙은 칸 바로 옆의 숫자만 읽어라.
같은 줄·같은 박스에 보증금/계약금/잔금/중도금이 있으면 절대 월세로 가져오지 마라.
월세·차임 칸이 공란이거나 0원 의미면 반드시 "0"만 출력해라.
출력은 반드시 한 줄로 "0" 또는 숫자(쉼표 가능)만. 다른 텍스트 금지.
"""
    else:
        target_rule = """
표준임대차계약서 양식이다.
2페이지 계약조건 표에서 '월임대료' 라벨이 붙은 칸만 찾아 그 칸의 값만 읽어라.
같은 표에 보증금/계약금/잔금/관리비가 있어도 월세로 가져오지 마라.
해당 칸이 공란이거나 0/해당없음이면 반드시 "0"만 출력해라.
출력은 반드시 한 줄로 "0" 또는 숫자(쉼표 가능)만. 다른 텍스트 금지.
"""

    prompt = f"""
너는 임대차 계약서에서 월세(차임)만 정밀 판독하는 OCR 엔진이다.
{target_rule}
"""

    parts = [prompt]
    for i, b in enumerate(b64s):
        parts.append({"inline_data": {"mime_type": f"image/{mimes[i]}", "data": b}})
    res = model.generate_content(parts, generation_config={"temperature": 0})
    out = (res.text or "").strip().split("\n")[0].strip()
    return out if out else "0"


def verify_contract_period_strictly(
    api_key: str, b64s: list, mimes: list, doc_type: str
) -> dict:
    """
    계약기간(임대차기간)을 정밀 재추출. 시작일·종료일 2개를 YYYY-MM-DD로 반환.
    반환: {"ok": True, "start": "YYYY-MM-DD", "end": "YYYY-MM-DD"} 또는 {"ok": False, "start": "", "end": ""}
    """
    genai.configure(api_key=api_key.strip())
    model = genai.GenerativeModel("gemini-2.0-flash")
    prompt = """
너는 임대차계약서에서 '계약기간(임대차기간)'을 정밀 판독하는 OCR 엔진이다.
규칙:
1) '임대차 기간/임대차기간/계약기간/인도일로부터' 문장에서 시작일과 종료일(만기일) 두 날짜를 모두 찾아라.
2) 예: '2025년 5월 16일부터 2027년 5월 15일까지' → start=2025-05-16, end=2027-05-15
3) 날짜는 YYYY-MM-DD로 정규화. 두 날짜를 못 찾으면 ok=false.
4) JSON 한 줄만: {"ok":true,"start":"YYYY-MM-DD","end":"YYYY-MM-DD"} 또는 {"ok":false,"start":"","end":""}
"""
    parts = [prompt]
    for i, b in enumerate(b64s):
        parts.append({"inline_data": {"mime_type": f"image/{mimes[i]}", "data": b}})
    try:
        res = model.generate_content(parts, generation_config={"temperature": 0})
        out = (res.text or "").strip()
    except Exception:
        out = ""
    m = re.search(r"\{[^{}]*\}", out)
    if not m:
        return {"ok": False, "start": "", "end": ""}
    try:
        data = json.loads(m.group(0))
        ok = bool(data.get("ok"))
        s = (data.get("start") or "").strip()
        e = (data.get("end") or "").strip()
        if ok and re.fullmatch(r"20\d{2}-\d{2}-\d{2}", s) and re.fullmatch(r"20\d{2}-\d{2}-\d{2}", e):
            return {"ok": True, "start": s, "end": e}
    except Exception:
        pass
    return {"ok": False, "start": "", "end": ""}


# ============================================================
# v1.1 추가: 특약(ConSpecial) 페이지 탐지 + 값 추출
# ============================================================

import json as _json

_SPECIAL_TERMS_TEXT_PAT = re.compile(r"(특약\s*사항|특약\s*\d+\s*:)", re.IGNORECASE)

CONSPECIAL_EXTRACT_PROMPT = r"""
너는 임대차계약서의 '특약사항' 페이지에서 본문(제1조~제N조)과 다를 수 있는 값을 추출하는 엔진이다.

**추출 대상**: 보증금, 월세, 계약기간 — 이 3개만.

**핵심 규칙**:
1) 특약 텍스트에 보증금/월세/계약기간 관련 금액이나 날짜가 **명시적으로 적혀 있을 때만** 추출해라.
   - 예: "보증금을 1억 3천만원으로 변경", "월세 40만원으로 조정", "계약기간을 2025.05.16~2026.05.15로 한다"
   - 예: "임대차보증금 금일억삼천만원", "차임(월세) 금사십만원"
2) 명시적으로 안 적혀 있으면 반드시 null. 추측 금지. 본문 값 재사용 금지.
3) 보증금/월세 출력 형식: 숫자만 (예: "130000000", "400000"). 한글 금액이면 숫자로 환산.
4) 월세가 "없음/전세/0원" 의미면 "0".
5) 계약기간: "YYYY-MM-DD ~ YYYY-MM-DD" 형식. 날짜 2개가 명시 안 돼있으면 null.
6) JSON만 출력. 코드펜스/설명글/마크다운 절대 금지.

출력:
{"items":[{"item":"보증금","ConSpecial_value":null},{"item":"월세","ConSpecial_value":null},{"item":"계약기간","ConSpecial_value":null}]}
"""


def detect_special_terms_page_indices(
    images_b64: list[str], mimes: list[str],
    pdf_bytes: Optional[bytes] = None,
) -> list[int]:
    """
    특약사항 페이지 인덱스를 반환.
    PDF 텍스트 레이어가 있으면 텍스트로 판별(API 호출 0).
    """
    if pdf_bytes is not None and HAS_PYMUPDF:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        idxs = []
        for i in range(len(doc)):
            text = (doc[i].get_text("text") or "").strip()
            if text and _SPECIAL_TERMS_TEXT_PAT.search(text):
                idxs.append(i)
        doc.close()
        if idxs:
            return idxs
    # 텍스트 레이어 없으면: 이미지 개수 기준 추정 (API 절약)
    n = len(images_b64)
    if n == 10:
        return [7]
    if n > 6:
        return [n - 3]
    return []


def extract_conspecial_values(
    api_key: str, images_b64: list[str], mimes: list[str],
    special_idxs: list[int],
) -> list[dict]:
    """
    특약 페이지만 Gemini에 넣어서 보증금/월세/계약기간의 ConSpecial_value를 추출.
    반환: [{"item": "보증금", "ConSpecial_value": "150000000"}, ...] (없으면 null)
    """
    if not special_idxs:
        return []
    sub_b64 = [images_b64[i] for i in special_idxs if 0 <= i < len(images_b64)]
    sub_mime = [mimes[i] for i in special_idxs if 0 <= i < len(mimes)]
    if not sub_b64:
        return []

    genai.configure(api_key=api_key.strip())
    model = genai.GenerativeModel("gemini-2.0-flash")
    parts: list[Any] = [CONSPECIAL_EXTRACT_PROMPT]
    for j, b in enumerate(sub_b64):
        parts.append({
            "inline_data": {
                "mime_type": f"image/{sub_mime[j]}",
                "data": b,
            }
        })
    try:
        res = model.generate_content(parts, generation_config={"temperature": 0})
        raw = (res.text or "").strip()
    except Exception:
        return []

    m = re.search(r"\{", raw)
    if not m:
        return []
    depth = 0
    start = m.start()
    for i in range(start, len(raw)):
        if raw[i] == "{":
            depth += 1
        elif raw[i] == "}":
            depth -= 1
            if depth == 0:
                try:
                    data = _json.loads(raw[start:i+1])
                    items = data.get("items")
                    return items if isinstance(items, list) else []
                except Exception:
                    return []
    return []

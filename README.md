# 임대차 계약서 자동 검증기 (Rental Contract Auto Verifier)

This is a **Proof-of-Concept (POC)** Streamlit web app that extracts key fields from Korean lease contracts (임대차 계약서) and validates them against user-provided checklist inputs.  
It uses **Google Gemini Vision** to parse document content and highlights mismatches (e.g., deposit, address, contract period) in a human-review-friendly table.

---

## What it does
- Extracts: address, deposit, monthly rent, contract period, landlord/tenant name, resident registration number (**handled carefully / masked where applicable**)
- Compares document values vs checklist values and shows match/mismatch results
- Optionally provides debug output (**may include PII if enabled**)

---

## How to run
```bash
pip install -r requirements.txt
streamlit run app.py
```

---

## 무엇을 하는 프로젝트인가요?
이 프로젝트는 **임대차 계약서(한국)**에서 주요 항목을 추출하고, 사용자가 입력한 체크리스트 값과 **일치/불일치 여부를 검증**하는 **개념증명(POC)** Streamlit 웹 앱입니다.  
**Google Gemini Vision**을 사용해 문서 내용을 파싱하고, 보증금·주소·계약기간 등 불일치 항목을 **휴먼 리뷰가 쉬운 표 형태로 강조 표시**합니다.

---

## 주요 기능 (개요)
- 추출 항목: 주소, 보증금, 월세, 계약기간, 임대인/임차인 성명, 주민등록번호(**필요 시 마스킹/주의 처리**)
- 계약서 값 vs 체크리스트 값 비교 후 일치/불일치 결과 표시
- 디버그 출력 옵션 제공(**활성화 시 PII 포함 가능**)

---

## 실행 방법
```bash
pip install -r requirements.txt
streamlit run app.py
```

브라우저에서 `http://localhost:8501` 로 접속하세요.

---

## ⚠️ Important (PII / Privacy)
- This repository is a **POC** for document extraction & validation workflows.
- **Do NOT upload or commit real contracts** containing names, addresses, resident registration numbers, or any personal data.
- Use **synthetic / fully anonymized** samples only.
- Debug outputs may contain sensitive fields; keep debug mode **OFF** unless you are using anonymized data.
- Logs (e.g., decision_log.csv) must remain **local only** and should never be committed.

## ⚠️ 중요 안내 (개인정보/보안)
- 이 저장소는 문서 추출 및 검증 워크플로우를 위한 **POC**입니다.
- 성명, 주소, 주민등록번호 등 개인정보가 포함된 **실제 계약서를 업로드/커밋하지 마세요.**
- **가상 데이터 또는 완전 비식별화된 샘플**만 사용하세요.
- 디버그 출력에는 민감 정보가 포함될 수 있으니, 비식별 데이터가 아닌 경우 **디버그 모드는 OFF**로 유지하세요.
- 로그(예: decision_log.csv)는 **로컬 전용**이며 절대 커밋하지 마세요.

---

## 주요 기능

- **사이드바**: Google (Gemini) API Key 입력
- **메인 입력**: 주소, 보증금, 월세, 계약기간(시작일~종료일), 임대인/임차인 성명·생년월일, 계약서 파일(PNG/JPG/PDF) 업로드
- **OCR**: Gemini 2.0 Flash로 이미지/PDF에서 텍스트 추출 (전체 페이지 통합·Cross-page reasoning, 수사관 모드로 확인설명서 보증금 정밀 추출)
- **사용자 입력과 비교**: 8개 항목(주소, 보증금, 월세, 계약기간, 임대인/임차인 성명·식별정보)에 대해 ✅ O / ❌ X로 일치 여부 표시
- **문서 간 교차 검증**: 본문(contract_value) vs **확인설명서**(checklist_value)를 비교해, 불일치 시 해당 행에 **⚠️ 확인필요** 노란색 경고 및 비고란에 **「⚠️ 확인필요 일부서류 불일치」** 표시
- **기타사항 행**: 하단에 확인설명서 내용 불일치 상세(본문 vs 확인설명서, 금액은 쉼표 포맷) 및 Human-Review 필요 여부 표시
- **성명 정밀 검증**: 성명 불일치 시 2차 Vision 호출로 획·모양만 집중 재판독 (결과는 `decision_log.csv`에 기록)

---

## 프로젝트 구조

| 파일 | 역할 |
|------|------|
| **app.py** | Streamlit UI 전용: 폼, 버튼, 결과 테이블 렌더링(`render_result_with_icons`) |
| **ocr_service.py** | PDF→이미지 변환, Vision API 호출(`call_gemini_vision`), 성명 정밀 검증(`verify_name_strictly`) |
| **document_logic.py** | JSON 파싱(`parse_result_json`), 본문 vs 확인설명서 교차 검증·`is_doc_mismatch` 설정(`build_final_items`) |
| **comparators.py** | 주소/금액/날짜/성명/식별정보 비교, `format_korean_money`, 하이라이트 유틸 |

---

## 설치 및 실행

```bash
cd rental_contract_verifier
pip install -r requirements.txt
streamlit run app.py
```

브라우저에서 `http://localhost:8501` 로 접속하세요.

---

## 요구사항

- Python 3.8+
- **Google (Gemini) API Key** (Gemini 2.0 Flash 사용)
- 의존성: `streamlit`, `google-generativeai`, `pymupdf`, `pandas` 등 (`requirements.txt` 참고)

---

## Validation
- Verified: reproducibility (repeat runs), safety routing (Human-Review on uncertain cases), and decision logging.


## 검증(Validation)
- 반복 실행 시 결과가 일관되게 재현되는지 확인했습니다.
- 불확실/위험 케이스는 자동 확정하지 않고 Human-Review로 라우팅되도록 동작을 확인했습니다.


### Known Limitations
- Gemini Vision 2.0 한글 모음(ㅗ/ㅜ) 오인식 가능성 존재
- 계약서 해상도/폰트 품질에 따라 변동성 있음
- 멀티콜(2차 검증) 사용 시 평균 30~40초 소요

본 프로젝트는 Production 시스템이 아닌 **Proof-of-Concept** 입니다.

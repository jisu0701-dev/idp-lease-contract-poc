# Rental Contract Auto Verifier (IDP Lease Contract POC)

A **Proof-of-Concept (POC)** Streamlit web app that extracts key fields from Korean lease contracts and validates them against user-provided checklist inputs.  
It uses **Google Gemini Vision** to parse document content and highlights mismatches (e.g., deposit, address, contract period) in a human-review-friendly table.

---

## What it does
- Extracts key fields: address, deposit, monthly rent, contract period, landlord/tenant name, resident registration number (**handled carefully / masked where applicable**)
- Compares **document values vs. checklist values** and shows match/mismatch results
- Optional debug output (**may include PII if enabled**)

---

## How to run
```bash
pip install -r requirements.txt
streamlit run app.py
```
Open: http://localhost:8501

---

## Notes (PII / Privacy)
- This repository is a POC for document extraction & validation workflows.
- **Do NOT** upload or commit real contracts containing names, addresses, resident registration numbers, or any personal data.
- Use **synthetic / fully anonymized** samples only.
- Debug outputs may contain sensitive fields; keep debug mode **OFF** unless you are using anonymized data.
- Logs (e.g., decision_log.csv) must remain **local only** and should never be committed.

---

## Key features (overview)
- Checklist input + contract upload (PNG/JPG/PDF)
- Document parsing strategy: text-layer first (when available), otherwise image rendering + Vision
- Field-level ✅/❌ match indicators with brief notes/reasons
- (Optional) conditional strict re-checks for high-risk fields; on uncertainty, route to Human Review
- (Local only) decision log can be written to decision_log.csv (never commit)

---

## Project structure
| File | Role |
|------|------|
| **app.py** | Streamlit UI: inputs, upload, results table rendering |
| **ocr_service.py** | PDF handling (text-layer first / image fallback), Vision calls, conditional strict checks |
| **document_logic.py** | JSON parsing/normalization, final item building, cross-validation logic |
| **comparators.py** | Comparators for address/money/date/name/ID + formatting helpers |
| **pii_mask.py** | PII masking/normalization helpers |
| **check_models.py** | Environment/model sanity checks & small helpers |

---

## Requirements
- Python 3.8+
- **Google (Gemini) API Key**
- Dependencies: see `requirements.txt`

---

## Validation
- Verified reproducibility (repeat runs), safety routing (Human Review on uncertain cases), and decision logging.

---

## Known limitations
- OCR/vision results may vary depending on scan quality, DPI, fonts, and document layouts.
- Sensitive fields (e.g., RRNs) are highly dependent on rendering quality; prefer text-layer extraction when available.
- Enabling multi-pass / strict re-checks can increase latency.

This project is a **Proof-of-Concept**, not a production system.

---

# 임대차 계약서 자동 검증기 (IDP Lease Contract POC)

이 프로젝트는 **임대차 계약서**에서 주요 항목을 추출하고, 사용자가 입력한 체크리스트 값과 **일치/불일치 여부를 검증**하는 **개념증명(POC)** Streamlit 웹 앱입니다.  
**Google Gemini Vision**을 사용해 문서 내용을 파싱하고, 보증금·주소·계약기간 등 불일치 항목을 **휴먼 리뷰가 쉬운 표 형태로 강조 표시**합니다.

---

## 무엇을 하나요?
- 주요 항목 추출: 주소, 보증금, 월세, 계약기간, 임대인/임차인 성명, 주민등록번호(**필요 시 마스킹/주의 처리**)
- **계약서 값 vs 체크리스트 값** 비교 후 일치/불일치 결과 표시(✅/❌)
- 디버그 출력 옵션 제공(**활성화 시 PII 포함 가능**)

---

## 실행 방법
```bash
pip install -r requirements.txt
streamlit run app.py
```
브라우저에서 http://localhost:8501 로 접속하세요.

---

## ⚠️ 중요 안내 (개인정보/보안)
- 이 저장소는 문서 추출 및 검증 워크플로우를 위한 POC입니다.
- 성명, 주소, 주민등록번호 등 개인정보가 포함된 **실제 계약서를 업로드/커밋하지 마세요.**
- **가상 데이터 또는 완전 비식별화된 샘플**만 사용하세요.
- 디버그 출력에는 민감 정보가 포함될 수 있으니, 비식별 데이터가 아닌 경우 **디버그 모드는 OFF**로 유지하세요.
- 로그(예: decision_log.csv)는 **로컬 전용**이며 절대 커밋하지 마세요.

---

## 주요 기능(요약)
- 체크리스트 입력 + 계약서(PNG/JPG/PDF) 업로드
- 문서 파싱 전략: PDF 텍스트 레이어 우선 추출, 불가 시 이미지 렌더링 후 Vision 호출
- 항목별 ✅/❌ 표시 및 간단한 불일치 사유/비고 표기
- (옵션) 오독 위험 항목은 조건부 정밀 재판독, 불확실 시 Human Review로 라우팅
- (로컬 전용) 의사결정 로그를 decision_log.csv로 남길 수 있음(커밋 금지)

---

## 프로젝트 구조
| 파일 | 역할 |
|------|------|
| **app.py** | Streamlit UI: 입력 폼, 업로드, 결과 테이블 렌더링 |
| **ocr_service.py** | PDF 처리(텍스트/이미지 분기), Vision 호출, 조건부 정밀 검증 유틸 |
| **document_logic.py** | JSON 파싱/정규화, 최종 아이템 구성 및 교차검증 로직 |
| **comparators.py** | 주소/금액/날짜/성명/식별정보 비교 유틸 및 포맷터 |
| **pii_mask.py** | 주민번호 등 민감정보 마스킹/정규화 유틸 |
| **check_models.py** | 환경/모델 체크 및 헬퍼 |

---

## 요구사항
- Python 3.8+
- **Google (Gemini) API Key**
- 의존성: `requirements.txt` 참고

---

## 검증(Validation)
- 반복 실행 시 결과가 일관되게 재현되는지 확인했습니다.
- 불확실/위험 케이스는 자동 확정하지 않고 Human Review로 라우팅되도록 동작을 확인했습니다.
- 판단 근거가 로컬 로그로 남도록 구성했습니다(커밋 금지).

---

## 한계(Known Limitations)
- 계약서 해상도/DPI/폰트/레이아웃 품질에 따라 OCR/비전 결과가 변동될 수 있습니다.
- 주민등록번호 등 민감 필드는 렌더링 품질에 민감하므로, 가능하면 텍스트 레이어 우선 추출이 유리합니다.
- 멀티콜/정밀 재판독을 활성화하면 지연 시간이 증가할 수 있습니다.

본 프로젝트는 Production 시스템이 아닌 **Proof-of-Concept** 입니다.

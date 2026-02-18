# Lease Contract Auto-Verification PoC

Upload a jeonse/monthly-rent residential lease contract (PDF/images), and the AI extracts key fields and automatically compares them against the checklist values entered by a reviewer.

This project is a **Proof-of-Concept (PoC)** to validate whether we can automate the **document cross-checking work** that happens every day in financial guarantee underwriting (rent deposit return guarantee).

---

## Background

In guarantee underwriting, reviewers manually read unstructured documents such as lease contracts and brokerage "Explanation/Confirmation" forms, then retype the values into internal checklist systems. This manual work accounts for roughly **40%** of review time, and reviewers must cross-check inconsistencies across documents (deposit amount, address, contract period, etc.) by hand.

This PoC tests whether that workflow can shift to: **"AI drafts first, human verifies and corrects."**

---

## What It Does

1. **Extraction**: Automatically extracts address, deposit, monthly rent, contract period, landlord/tenant names and dates of birth from the contract PDF/images.
2. **Cross-Document Validation**: If an "Explanation/Confirmation" document is attached, it automatically compares planned transaction amount and address against the main contract.
3. **Special Terms Mismatch Detection (v1.1)**: Detects and flags cases where the special terms section states a different deposit/monthly rent/contract period than the main body.
4. **User Input Comparison**: Compares each extracted field with the reviewer-entered checklist values and marks ✅/❌.
5. **Human Review Routing**: If the model is uncertain or there is any cross-document mismatch, it routes the case to a human instead of auto-confirming.

---

## How to Run

```bash
pip install -r requirements.txt
streamlit run app.py
```

Open: http://localhost:8501

You need a Gemini API Key issued from Google AI Studio.

---

## Project Structure

| File | Role |
|------|------|
| **app.py** | Streamlit UI: input form, file upload, result table rendering |
| **ocr_service.py** | PDF text-layer extraction / image rendering + Gemini Vision calls, special-terms page detection & extraction |
| **document_logic.py** | JSON parsing, final item construction, cross-check logic for Explanation/Confirmation + special terms |
| **comparators.py** | Deterministic rule engine for comparing address/amount/dates/names/identity fields |
| **pii_mask.py** | Utility for masking resident registration numbers (RRN) |
| **check_models.py** | Helper to verify Gemini API connectivity |

---

## Design Principles

**Separation of Reading vs Decision-Making**: Gemini Vision is used only for "reading" (unstructured documents → structured JSON). "Decision-making" (match/mismatch, numeric comparison, address normalization) is handled by a deterministic Python rule engine. This keeps the comparison logic reusable even if the OCR engine is replaced.

**Preventing Special-Terms Contamination (v1.1)**: During contract-period re-extraction, special-terms pages are excluded and only the main body pages are used, preventing special-terms end dates from contaminating the main contract values.

---

## v1.1 Changes

- Automatic detection of special-terms pages (text-layer first; if unavailable, position-based estimation)
- Separate extraction of deposit/monthly rent/contract period from special terms and comparison against the main body
- If main body vs special terms mismatch is found: show it under "Other Notes" + route to Human Review
- Exclude special-terms pages when retrying contract-period extraction (prevents contamination)

---

## Known Limitations

- **Korean Name OCR**: Gemini Vision does not reliably recognize Korean names (e.g., "안지수" → "인수지"). Prompt tuning is not sufficient; a dedicated OCR model is required.
- **Numeric Misreads**: Confusions occur in dates of birth and the first digits of RRNs (e.g., 9↔0, 6↔0). The result is sensitive to image resolution.
- **Non-Deterministic Outputs**: Even with identical images and identical settings, Gemini Vision may produce different results. While temperature=0 enforces greedy decoding for text generation, variation in the image encoding stage cannot be fully controlled.
- **Template Dependency**: Tested on e-contract and standard residential lease templates. Handwritten and non-standard formats are not supported.

These limitations support the conclusion that a general-purpose LLM + prompts alone cannot reach finance-grade accuracy, and that a dedicated OCR model plus a self-learning pipeline is required.

---

## Personal Data Notice

- Do not upload or commit real contracts containing personal data (names, addresses, RRNs).
- Use synthetic data or fully de-identified samples only.
- decision_log.csv and feedback_log.csv are local-only and must not be committed.

---

This project is a Proof-of-Concept, not a production product.

---

# 임대차 계약서 자동 검증 PoC

전세·월세 임대차계약서를 업로드하면, AI가 주요 항목을 추출하고 심사자가 입력한 체크리스트 값과 자동 비교합니다.

이 프로젝트는 금융권 전세대출 서류심사 및 임대차 반환보증 심사 실무에서 매일 반복되는 **서류 대조 업무**를 자동화할 수 있는지 검증하기 위해 만든 **개념증명(PoC)**입니다.

---

## 배경

전세대출 서류심사 및 임대차 반환보증 심사에서 심사자는 계약서·확인설명서 등 비정형 서류를 육안으로 확인한 뒤, 전산 체크리스트에 수기로 입력합니다. 이 과정이 심사 시간의 약 40%를 차지하며, 서류 간 불일치(보증금·주소·계약기간 등)를 사람이 일일이 대조해야 합니다.

이 PoC는 그 대조 과정을 "AI가 초안을 쓰고, 사람이 확인·교정"하는 구조로 바꿀 수 있는지 실험합니다.

---

## 무엇을 하는가

1. **추출**: 계약서 PDF/이미지에서 주소, 보증금, 월세, 계약기간, 임대인/임차인 성명·생년월일을 자동 추출
2. **교차검증**: 확인설명서가 첨부되어 있으면 본문과 거래예정금액·주소를 자동 비교
3. **특약 불일치 감지** (v1.1): 특약사항에 본문과 다른 보증금·월세·계약기간이 있으면 자동 탐지하여 표시
4. **사용자 입력 대조**: 심사자가 입력한 체크리스트 값과 항목별 ✅/❌ 비교
5. **Human Review 라우팅**: 불확실하거나 서류 간 불일치가 있으면 자동 확정하지 않고 사람에게 넘김

---

## 실행 방법

```bash
pip install -r requirements.txt
streamlit run app.py
```

접속: http://localhost:8501

Google AI Studio에서 발급한 Gemini API Key가 필요합니다.

---

## 프로젝트 구조

| 파일 | 역할 |
|------|------|
| **app.py** | Streamlit UI: 입력 폼, 파일 업로드, 결과 테이블 렌더링 |
| **ocr_service.py** | PDF 텍스트 레이어 추출 / 이미지 렌더링 + Gemini Vision 호출, 특약 페이지 탐지·추출 |
| **document_logic.py** | JSON 파싱, 최종 항목 구성, 확인설명서·특약 교차검증 |
| **comparators.py** | 주소·금액·날짜·성명·식별정보 비교 로직 (결정론적 Python 룰 엔진) |
| **pii_mask.py** | 주민등록번호 마스킹 유틸 |
| **check_models.py** | Gemini API 연결 확인용 헬퍼 |

---

## 설계 원칙

**읽기와 판단의 분리**: Gemini Vision은 "읽기"만 담당하고(비정형 서류 → 구조화 JSON), "판단"(일치/불일치, 금액 비교, 주소 분해)은 Python 룰 엔진이 수행합니다. OCR 엔진을 교체해도 비교 로직은 그대로 재활용할 수 있는 구조입니다.

**특약 오염 방지** (v1.1): 계약기간 재추출 시 특약 페이지를 제외한 본문 페이지만 사용하여, 특약 만기일이 본문값으로 오염되는 문제를 방지합니다.

---

## v1.1 변경사항

- 특약사항 페이지 자동 탐지 (텍스트 레이어 우선, 없으면 위치 추정)
- 특약 내 보증금·월세·계약기간을 별도 추출하여 본문과 비교
- 본문 vs 특약 불일치 시 기타사항에 표시 + Human Review 라우팅
- 계약기간 리트라이 시 특약 페이지 제외 (본문값 오염 방지)

---

## 확인된 한계

- **한글 성명 OCR**: Gemini Vision은 한글 성명을 안정적으로 인식하지 못합니다 (예: "안지수" → "인수지"). 프롬프트 강화로 해결되지 않으며, 전용 OCR 모델이 필요합니다.
- **숫자 오독**: 생년월일·주민번호 앞자리에서 유사 숫자 혼동이 발생합니다 (예: 9↔0, 6↔0). 이미지 해상도에 민감합니다.
- **비결정적 결과**: 동일 이미지·동일 설정에서도 Gemini Vision 결과가 달라질 수 있습니다. temperature=0이 텍스트 생성의 greedy decoding은 보장하지만, 이미지 인코딩 단계의 변동은 통제하지 못합니다.
- **문서 양식 의존**: 전자계약서·표준임대차계약서 양식에서 테스트했으며, 손글씨 계약서·비표준 양식은 미지원입니다.

이 한계들은 "범용 LLM + 프롬프트만으로는 금융 실무 수준의 정확도를 달성할 수 없고, 전용 OCR 모델과 자가학습 파이프라인이 필요하다"는 결론의 근거입니다.

---

## 개인정보 안내

- 실제 계약서(성명, 주소, 주민등록번호 포함)를 업로드하거나 커밋하지 마세요.
- 가상 데이터 또는 완전 비식별화된 샘플만 사용하세요.
- decision_log.csv, feedback_log.csv는 로컬 전용이며 커밋 금지입니다.

---

이 프로젝트는 Proof-of-Concept이며, 실제 프로덕트가 아닙니다.

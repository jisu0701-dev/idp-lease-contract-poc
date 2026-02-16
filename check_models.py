import google.generativeai as genai
import os

# 👇 여기에 지수님의 실제 Google API Key를 따옴표 안에 넣으세요!
MY_API_KEY = os.environ.get("GOOGLE_API_KEY", "") 

# API 설정
genai.configure(api_key=MY_API_KEY)

print("----- 내 API 키로 사용 가능한 모델 목록 -----")
try:
    for m in genai.list_models():
        if 'generateContent' in m.supported_generation_methods:
            print(f"- {m.name}")
except Exception as e:
    print(f"오류가 발생했습니다: {e}")
    print("팁: pip install -U google-generativeai 명령어로 라이브러리를 업데이트 해보세요.")
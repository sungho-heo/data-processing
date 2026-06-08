import json
import glob
import os
import re
from collections import Counter

# ================================================
# 설정: 데이터 폴더 경로만 바꾸면 됩니다
# ================================================
INPUT_DIRS = [
    "./민사법/법령",
    "./민사법/법령_질의응답",
]
OUTPUT_PATH = "./민사법_법령.json"

# ================================================
# 필터 설정
# ================================================
SKIP_KEYWORDS = ["북한", "미사일", "외교", "국방", "군사", "선거"]

TABLE_REF = re.compile(r"\[(?:표|그림)\s*[\w\dⅠ-Ⅻ가-힣A-Za-z0-9\-\.]+\]")

# 문장 끝에 붙는 메타 표기 제거 패턴 (단위/자료/출처/주 등)
TRAILING_META = re.compile(r'\s*\((?:단위|자료|출처|주|참고)\s*[:：][^)]*\)\s*$')

# '음/임'으로 끝나지만 서술형 어미가 아닌 명사 예외 목록
NOUN_ENDINGS_EUM = {'다음', '처음', '이음', '노음', '고음', '저음', '중음', '화음', '불음'}
NOUN_ENDINGS_IM  = {'이임', '전임', '후임', '겸임', '현임', '신임', '사임'}

# 단독으로 남으면 의미 없는 잔해 패턴 (표 캡션, 출처 등)
JUNK_PATTERNS = [
    re.compile(r'^\s*\(단위\s*:'),    # (단위: 명, %)
    re.compile(r'^\s*단위\s*:'),       # 단위: 억원
    re.compile(r'^\s*\(자료\s*:'),     # (자료: 통계청)
    re.compile(r'^\s*\(출처\s*:'),     # (출처: 법제처)
    re.compile(r'^\s*\(주\s*[\)::]'), # (주) / (주:
]


def is_junk(text: str) -> bool:
    """표 캡션, 출처 등 단독으로 남으면 의미 없는 잔해 텍스트 판별"""
    return any(p.match(text) for p in JUNK_PATTERNS)


def insert_period_after_verbal_ending(text: str) -> str:
    """서술형 어미 음/임/함/됨 뒤에 마침표 삽입"""
    def replacer(m):
        start = m.start()
        ch = m.group(1)
        prefix_2 = text[max(0, start - 1):start + 1]
        if ch == '음' and prefix_2 in NOUN_ENDINGS_EUM:
            return m.group(0)
        if ch == '임' and prefix_2 in NOUN_ENDINGS_IM:
            return m.group(0)
        return ch + '. '

    return re.sub(
        r'(음|임|함|됨)(?!\.)(\s+)(?=[가-힣A-Z])',
        replacer,
        text
    )


def split_sentences(text: str) -> list[str]:
    """마침표/느낌표/물음표 뒤 공백 기준으로 문장 분리"""
    parts = re.split(r'(?<![0-9])(?<=[.!?])\s+', text)
    return [p.strip() for p in parts if p.strip()]


def clean_text(text: str) -> str:
    # 1. 줄바꿈 정리
    text = text.replace("\\n", " ")
    text = text.replace("\n", " ")

    # 2. HTML 태그 제거
    text = re.sub(r"<[^>]+>", " ", text)

    # 3. 특수 bullet 기호 제거
    text = re.sub(r"[◦□■●▶▷△▲◆◇☞※○]", " ", text)

    # 4. 서술형 어미 뒤 마침표 삽입
    text = insert_period_after_verbal_ending(text)

    # 5. 연속 공백 정리
    text = re.sub(r" {2,}", " ", text)

    # 6. 표/그림 참조 포함 문장 제거
    sentences = split_sentences(text)
    filtered = [s for s in sentences if not TABLE_REF.search(s)]
    text = " ".join(filtered)

    # 7. 문장 끝 메타 표기 제거
    text = TRAILING_META.sub('', text)

    # 8. 연속 공백 최종 정리
    text = re.sub(r" {2,}", " ", text)

    return text.strip()


def should_include(category_name: str) -> bool:
    """카테고리에 필터링 키워드가 포함되어 있는지 확인"""
    if any(kw in category_name for kw in SKIP_KEYWORDS):
        return False
    return True


def load_and_preprocess_files(input_dirs: list) -> list:
    all_vectors = []
    seen_doc_ids = set()

    base_dir = os.path.dirname(os.path.abspath(__file__)) if '__file__' in globals() else os.getcwd()
    print(f"🔍 [디버깅] 스크립트 기준 절대 경로: {base_dir}")

    for input_dir in input_dirs:
        abs_input_dir = os.path.normpath(os.path.join(base_dir, input_dir))
        
        if not os.path.exists(abs_input_dir):
            print(f"  ❌ [경고] 폴더가 존재하지 않습니다: {abs_input_dir}")
            continue

        search_pattern = os.path.join(abs_input_dir, "**/*.json")
        json_files = glob.glob(search_pattern, recursive=True)
        
        total_files = len(json_files)
        print(f"\n📂 탐색 중인 폴더: {abs_input_dir}")
        print(f"  📊 발견된 JSON 파일 수: {total_files:,}개 (전처리를 시작합니다...)")

        processed_count = 0

        for filepath in json_files:
            processed_count += 1
            
            if processed_count % 1000 == 0 or processed_count == total_files:
                print(f"  ⏳ 진행 중... [{processed_count:,} / {total_files:,}] ({processed_count/total_files*100:.1f}%) | 누적 유효 벡터: {len(all_vectors):,}건")

            try:
                with open(filepath, "r", encoding="utf-8-sig") as f:
                    data = json.load(f)
                
                file_title = os.path.splitext(os.path.basename(filepath))[0]
                docs = data if isinstance(data, list) else [data]

                for doc in docs:
                    # ------------------------------------------------
                    # 동적 스키마 판별 (판결문 vs 법령)
                    # ------------------------------------------------
                    # 1. 판결문인 경우 (casenames 존재)
                    if "casenames" in doc:
                        category = doc.get("casenames", "미분류")
                        doc_id = doc.get("doc_id", file_title)
                    # 2. 법령인 경우 (statute_category 존재)
                    elif "statute_category" in doc:
                        category = doc.get("statute_category", "법령_미분류")
                        # 법령에 고유 ID 필드가 없으면 statute_name이나 파일명을 고유 식별자로 활용
                        doc_id = doc.get("statute_name", file_title)
                    else:
                        # 예외 스키마인 경우 기본 처리
                        category = "미분류"
                        doc_id = file_title
                    
                    # 중복 문서 스킵
                    if doc_id in seen_doc_ids:
                        continue
                    seen_doc_ids.add(doc_id)

                    # 카테고리 필터링 키워드 체크
                    if not should_include(category):
                        continue

                    # 내부 문장 필터링 및 정제
                    sentences_list = doc.get("sentences", [])
                    cleaned_sentences = []
                    for sentence in sentences_list:
                        if len(sentence) < 10:
                            continue
                        if is_junk(sentence):
                            continue
                        
                        cleaned_s = clean_text(sentence)
                        if len(cleaned_s) >= 5:
                            cleaned_sentences.append(cleaned_s)
                    
                    # 문장 결합
                    final_text = " ".join(cleaned_sentences).strip()
                    
                    # 최소 유효 길이 검증
                    if len(final_text) < 30:
                        continue

                    # 최종 통합 매핑 규격 저장
                    all_vectors.append({
                        "title": file_title,    # 파일명 기반 타이틀
                        "category": category,   # 판결문(casenames) 또는 법령(statute_type)
                        "text": final_text,     # sentences 정제 후 결합 내용
                    })

            except Exception as e:
                pass
                
    return all_vectors


# ================================================
# 메인 실행
# ================================================
print("=== 통합 단계: 판결문 및 법령 데이터 로드 및 전처리 시작 ===")
all_vectors = load_and_preprocess_files(INPUT_DIRS)
print(f"\n✅ 전처리 최종 변환 완료 벡터 수: {len(all_vectors):,}건\n")

# 최종 결과 저장
with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
    json.dump(all_vectors, f, ensure_ascii=False, indent=2)

print("=" * 40)
print(f"🎉 저장 완료되었습니다 -> {OUTPUT_PATH}")
print("=" * 40)

# 최종 카테고리 통합 분포 요약 정보 출력
cats = Counter(v["category"] for v in all_vectors)
print("\n📊 통합 카테고리(category) 분포 TOP 20:")
for k, v in cats.most_common(20):
    print(f"  {k}: {v:,}건")
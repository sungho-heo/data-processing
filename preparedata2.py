import json
import glob
import os
import re
from collections import Counter

# ================================================
# 설정: 데이터 폴더 경로만 바꾸면 됩니다
# ================================================
INPUT_DIRS = [
    "./민사법/판결문",
    "./민사법/판결문_요약",
    "./민사법/판결문_질의응답",
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
    re.compile(r'^\s*\(단위\s*:'),    # (단위: 명, %) / (단위: 천명, %, %p)
    re.compile(r'^\s*단위\s*:'),       # 단위: 억원
    re.compile(r'^\s*\(자료\s*:'),     # (자료: 통계청)
    re.compile(r'^\s*\(출처\s*:'),     # (출처: 법제처)
    re.compile(r'^\s*\(주\s*[\)::]'), # (주) / (주:
]


def is_junk(text: str) -> bool:
    """표 캡션, 출처 등 단독으로 남으면 의미 없는 잔해 텍스트 판별"""
    return any(p.match(text) for p in JUNK_PATTERNS)


def insert_period_after_verbal_ending(text: str) -> str:
    """
    서술형 어미 음/임/함/됨 뒤에 마침표 삽입.
    - 이미 마침표가 있으면 삽입 안 함
    - 뒤에 공백 + 한글/영대문자가 오는 경우에만 삽입
    - 명사 예외 목록에 있는 단어는 건너뜀 (다음, 처음 등)
    """
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
    """마침표/느낌표/물음표 뒤 공백 기준으로 문장 분리 (소수점 제외)"""
    parts = re.split(r'(?<![0-9])(?<=[.!?])\s+', text)
    return [p.strip() for p in parts if p.strip()]


def clean_text(text: str) -> str:
    # 1. 줄바꿈 정리
    text = text.replace("\\n", " ")
    text = text.replace("\n", " ")

    # 2. HTML 태그 제거 (<br>, <br/>, <p>, <b>, <span> 등)
    text = re.sub(r"<[^>]+>", " ", text)

    # 3. 특수 bullet 기호 제거 (○ 포함)
    text = re.sub(r"[◦□■●▶▷△▲◆◇☞※○]", " ", text)

    # 4. 서술형 어미(음/임/함/됨) 뒤 마침표 삽입
    text = insert_period_after_verbal_ending(text)

    # 5. 연속 공백 정리
    text = re.sub(r" {2,}", " ", text)

    # 6. 표/그림 참조([표 Ⅱ-1], [그림 A-2] 등) 포함 문장 통째로 제거
    sentences = split_sentences(text)
    filtered = [s for s in sentences if not TABLE_REF.search(s)]
    text = " ".join(filtered)

    # 7. 문장 끝 메타 표기 제거 (단위: ...), (자료: ...) 등
    text = TRAILING_META.sub('', text)

    # 8. 연속 공백 최종 정리
    text = re.sub(r" {2,}", " ", text)

    return text.strip()


def should_include(casename: str) -> bool:
    """사건명(casename)에 필터링 키워드가 포함되어 있는지 확인"""
    if any(kw in casename for kw in SKIP_KEYWORDS):
        return False
    return True


def load_and_preprocess_files(input_dirs: list) -> list:
    """모든 폴더에서 판결문 JSON 파일을 읽어 요청된 형식으로 전처리 수행"""
    all_vectors = []
    seen_doc_ids = set()

    # 스크립트 파일의 실제 절대 경로 기준점 계산
    base_dir = os.path.dirname(os.path.abspath(__file__)) if '__file__' in globals() else os.getcwd()
    print(f"🔍 [디버깅] 스크립트 기준 절대 경로: {base_dir}")

    for input_dir in input_dirs:
        # 상대 경로(./data/...)를 절대 경로로 안전하게 변환
        abs_input_dir = os.path.normpath(os.path.join(base_dir, input_dir))
        print(f"\n📂 탐색 중인 폴더 (절대경로): {abs_input_dir}")
        
        # 1차 검증: 폴더 자체가 실제로 존재하는지 확인
        if not os.path.exists(abs_input_dir):
            print(f"  ❌ [경고] 폴더가 존재하지 않습니다: {abs_input_dir}")
            print(f"  💡 팁: 현재 폴더 안의 실제 목록을 확인하세요 -> {os.listdir(os.path.dirname(abs_input_dir) if os.path.exists(os.path.dirname(abs_input_dir)) else base_dir)}")
            continue

        # 2차 검증: glob 패턴 생성 및 검색
        search_pattern = os.path.join(abs_input_dir, "**/*.json")
        json_files = glob.glob(search_pattern, recursive=True)
        
        print(f"  🔎 검색 패턴: {search_pattern}")
        print(f"  📊 발견된 JSON 파일 수: {len(json_files)}개")

        for filepath in json_files:
            try:
                with open(filepath, "r", encoding="utf-8-sig") as f:
                    data = json.load(f)
                
                file_title = os.path.splitext(os.path.basename(filepath))[0]
                docs = data if isinstance(data, list) else [data]

                for doc in docs:
                    doc_id = doc.get("doc_id", file_title)
                    casename = doc.get("casenames", "미분류")
                    sentences_list = doc.get("sentences", [])
                    
                    if doc_id in seen_doc_ids:
                        continue
                    seen_doc_ids.add(doc_id)

                    if not should_include(casename):
                        continue

                    cleaned_sentences = []
                    for sentence in sentences_list:
                        if len(sentence) < 10:
                            continue
                        if is_junk(sentence):
                            continue
                        
                        cleaned_s = clean_text(sentence)
                        if len(cleaned_s) >= 5:
                            cleaned_sentences.append(cleaned_s)
                    
                    final_text = " ".join(cleaned_sentences).strip()
                    
                    if len(final_text) < 30:
                        continue

                    all_vectors.append({
                        "title": file_title,
                        "category": casename,
                        "text": final_text,
                    })

            except Exception as e:
                print(f"  ⚠️ 오류 발생 ({filepath}): {e}")
                
    return all_vectors


# ================================================
# 메인 실행
# ================================================
print("=== 1~4단계 통합: 판결문 데이터 로드 및 파일명/사건명 기반 정제 ===")
all_vectors = load_and_preprocess_files(INPUT_DIRS)
print(f"\n최종 변환 완료 벡터 수: {len(all_vectors):,}건\n")

# 최종 결과 저장
with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
    json.dump(all_vectors, f, ensure_ascii=False, indent=2)

print("=" * 40)
print(f"저장 완료: {OUTPUT_PATH}")
print("=" * 40)

# 카테고리(사건명) 분포 확인
cats = Counter(v["category"] for v in all_vectors)
print("\n사건명(category) 분포:")
for k, v in cats.most_common(20): # 상위 20개 출력
    print(f"  {k}: {v:,}건")
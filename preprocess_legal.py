import json
import glob
import os
import re
from collections import defaultdict

# ================================================
# 설정: 데이터 폴더 경로만 바꾸면 됩니다
# ================================================
INPUT_DIRS = [
    "./data/training",
    "./data/training2",
    "./data/training3",
    "./data/training4",
]
OUTPUT_PATH = "./legal_vector_data2.json"

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


def should_include(doc: dict) -> bool:
    cls = doc["doc_class"]["class"]
    title = doc["doc_title"]
    if not cls.startswith("법률/"):
        return False
    if any(kw in title for kw in SKIP_KEYWORDS):
        return False
    return True


def load_all_docs(input_dirs: list) -> list:
    """모든 폴더에서 문서 로드"""
    all_docs = []
    for input_dir in input_dirs:
        json_files = glob.glob(os.path.join(input_dir, "**/*.json"), recursive=True)
        for filepath in json_files:
            print(f"로드 중: {filepath}")
            try:
                with open(filepath, "r", encoding="utf-8-sig") as f:
                    data = json.load(f)
                all_docs.extend(data["data"])
            except Exception as e:
                print(f"  ⚠️ 오류 ({filepath}): {e}")
    return all_docs


def deduplicate_by_latest(docs: list) -> list:
    """같은 제목이면 최신 발행일 버전만 유지"""
    title_latest = {}
    for doc in docs:
        title = doc["doc_title"]
        pub = doc["doc_published"]
        if title not in title_latest or pub > title_latest[title]:
            title_latest[title] = pub

    seen_titles_dates = set()
    result = []
    for doc in docs:
        title = doc["doc_title"]
        pub = doc["doc_published"]
        key = (title, pub)
        if pub < title_latest[title]:
            continue
        if key in seen_titles_dates:
            continue
        seen_titles_dates.add(key)
        result.append(doc)

    return result


# ================================================
# 메인 실행
# ================================================
print("=== 1단계: 전체 문서 로드 ===")
all_docs = load_all_docs(INPUT_DIRS)
print(f"총 로드: {len(all_docs):,}건\n")

print("=== 2단계: 법률 필터링 ===")
filtered_docs = [doc for doc in all_docs if should_include(doc)]
print(f"필터링 후: {len(filtered_docs):,}건 (제거: {len(all_docs)-len(filtered_docs):,}건)\n")

print("=== 3단계: 최신 버전 중복 제거 ===")
deduped_docs = deduplicate_by_latest(filtered_docs)
print(f"중복 제거 후: {len(deduped_docs):,}건 (제거: {len(filtered_docs)-len(deduped_docs):,}건)\n")

print("=== 4단계: context 추출 및 정제 ===")
all_vectors = []
seen_context_ids = set()

for doc in deduped_docs:
    for para in doc["paragraphs"]:
        if len(para["context"]) < 50:
            continue
        if is_junk(para["context"]):
            continue
        if para["context_id"] in seen_context_ids:
            continue
        seen_context_ids.add(para["context_id"])

        cleaned = clean_text(para["context"])
        if len(cleaned) < 20:  # clean_text 후 너무 짧아진 경우도 제거
            continue

        all_vectors.append({
            "title": clean_text(doc["doc_title"]),
            "category": doc["doc_class"]["class"],
            "text": cleaned,
        })

print(f"최종 벡터 수: {len(all_vectors):,}건\n")

with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
    json.dump(all_vectors, f, ensure_ascii=False, indent=2)

print("=" * 40)
print(f"저장 완료: {OUTPUT_PATH}")
print("=" * 40)

from collections import Counter
cats = Counter(v["category"] for v in all_vectors)
print("\ncategory 분포:")
for k, v in cats.most_common():
    print(f"  {k}: {v:,}건")

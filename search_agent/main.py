import sys
sys.stdout.reconfigure(encoding='utf-8')

from naver_news_api import fetch_naver_news
from rss_collector import fetch_rss_news, fetch_google_news_rss
from dart_api import fetch_corp_code, fetch_disclosures
from database import save_news_to_db, save_disclosures_to_db, init_db
from crawler import update_empty_contents

def main():
    print("--- Search Agent 파이프라인 시작 ---")

    # 1. DB 셋업
    init_db()

    news_queries = [
        "반도체", "삼성전자", "SK하이닉스", "HBM", "파운드리",
        "엔비디아", "TSMC", "인텔", "AI반도체", "메모리반도체"
    ]

    all_news = []

    # 2. 네이버 뉴스 API 수집
    print("\n[1] 네이버 API 수집 중...")
    for query in news_queries:
        print(f"  - '{query}' 수집 중...")
        all_news += fetch_naver_news(query, display=100)

    # 3. RSS 수집 (키워드 없이 전체 + 반도체 필터)
    print("\n[2] RSS 수집 중...")
    for query in ["반도체", "삼성전자", "SK하이닉스", "HBM"]:
        all_news += fetch_rss_news(query=query, display=20)

    # 4. 구글 뉴스 RSS 수집
    print("\n[3] 구글 뉴스 RSS 수집 중...")
    all_news += fetch_google_news_rss(display=20)

    # 4. 합쳐서 DB 저장
    print(f"\n[3] 총 {len(all_news)}건 DB 저장 중...")
    if all_news:
        save_news_to_db(all_news)
    else:
        print("저장할 뉴스가 없습니다.")

    # 5. DART 공시 수집
    dart_targets = [
        "삼성전자", "SK하이닉스",
        "DB하이텍", "한미반도체", "HPSP",
        "리노공업", "피에스케이", "ISC",
        "원익IPS", "테크윙",
    ]
    from datetime import datetime, timedelta
    bgn_de = (datetime.today() - timedelta(days=30)).strftime("%Y%m%d")
    end_de = datetime.today().strftime("%Y%m%d")

    for corp_name in dart_targets:
        print(f"\n[5] DART: '{corp_name}' 공시 수집 중...")
        corp = fetch_corp_code(corp_name)
        if corp:
            disclosures = fetch_disclosures(corp_code=corp["corp_code"], bgn_de=bgn_de, end_de=end_de, display=20)
            for d in disclosures:
                d["stock_code"] = corp["stock_code"]
            save_disclosures_to_db(disclosures)

    # 6. 빈 본문 크롤링
    print("\n[6] 본문이 비어있는 기사 크롤링 시작...")
    update_empty_contents()

    print("\n전체 파이프라인 실행이 완료되었습니다!")

if __name__ == "__main__":
    main()

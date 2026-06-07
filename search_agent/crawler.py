import time
import re
import requests
from bs4 import BeautifulSoup
from database import SessionLocal
from models import News, Reporter

# 네이버 서버의 봇(Bot) 차단을 방지하기 위한 User-Agent 헤더
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
}

def clean_extracted_text(text):
    """본문 내 불필요한 공백, 잡음(저작권 문구 등)을 단순히 정제합니다."""
    if not text:
        return ""
    lines = [line.strip() for line in text.split('\n') if line.strip()]
    
    clean_lines = []
    for line in lines:
        if any(keyword in line for keyword in ["무단 전재", "무단복제", "Copyright ⓒ", "무단전재"]):
            break
        clean_lines.append(line)
        
    return " ".join(clean_lines)

def extract_email(text):
    """정규표현식을 사용해 텍스트 내에서 이메일 패턴 추출"""
    if not text: return None
    match = re.search(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', text)
    return match.group(0) if match else None

def extract_summary(text):
    """본문의 앞 3문장만 반환하는 간이 요약 기능"""
    if not text: return ""
    sentences = [s.strip() for s in text.replace("\n", " ").split('. ') if s.strip()]
    if len(sentences) > 3:
        sentences = sentences[:3]
        
    result = '. '.join(sentences)
    if result and not result.endswith('.'):
        result += '.'
    return result

def extract_reporter_from_soup(soup):
    """한국 뉴스 사이트 공통 기자 이름 추출"""
    reporter_name = None

    # 1. 클래스명 기반 탐색
    byline_tag = soup.find(class_=re.compile(r"journalist|byline|reporter|writer|author", re.I))
    if byline_tag:
        rep_text = byline_tag.get_text(strip=True)
        name_match = re.search(r'([가-힣]{2,4})\s*기자', rep_text)
        if name_match:
            return name_match.group(1)

    # 2. 전체 텍스트에서 "홍길동 기자" 패턴 탐색
    full_text = soup.get_text()
    name_match = re.search(r'([가-힣]{2,4})\s*기자', full_text)
    if name_match:
        reporter_name = name_match.group(1)

    return reporter_name


def crawl_article(url):
    """네이버 및 외부 뉴스 사이트에서 기사 본문, 이메일, 기자 이름을 추출합니다."""
    try:
        response = requests.get(url, headers=HEADERS, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")

        reporter_name = extract_reporter_from_soup(soup)

        # 네이버 뉴스
        article_body = soup.find("article", id="dic_area")

        # 외부 뉴스: 일반적인 본문 후보 셀렉터 순서대로 시도
        if not article_body:
            for selector in [
                {"id": re.compile(r"article|article-body|news-body|view_content|articeBody", re.I)},
                {"class_": re.compile(r"article[-_]?(body|content|text|view)|news[-_]?(body|content|text)|view[-_]?content|read[-_]?body", re.I)},
            ]:
                article_body = soup.find(attrs=selector) if "id" not in selector else soup.find(id=selector.get("id"))
                # handle both
                if not article_body:
                    article_body = soup.find(class_=selector.get("class_")) if "class_" in selector else None
                if article_body:
                    break

        if article_body:
            raw_text = article_body.get_text(separator="\n")
            email = extract_email(raw_text)
            for tag in article_body(["script", "style", "iframe", "em"]):
                tag.decompose()
            clean_text = clean_extracted_text(article_body.get_text(separator="\n"))
            return clean_text, email, reporter_name

    except Exception as e:
        print(f"[{url}] 본문 추출 실패: {e}")

    return None, None, None


def crawl_naver_news_content(url):
    """하위 호환용 - crawl_article로 위임"""
    return crawl_article(url)

def update_empty_contents():
    """DB에서 content가 비어있는 레코드를 찾아 본문, 요약, 이메일을 UPDATE 합니다."""
    db = SessionLocal()
    try:
        empty_news_list = db.query(News).filter(
            (News.content == None) | (News.content == "")
        ).all()
        
        if not empty_news_list:
            print("[OK] 모든 뉴스의 본문이 이미 꽉 차 있습니다! (업데이트할 항목 없음)")
            return

        print(f"▶ 총 {len(empty_news_list)}개의 빈 데이터를 찾아 업데이트를 시작합니다...")
        updated_count = 0
        skipped_count = 0
        
        for news in empty_news_list:
            url = news.url

            # 2. 크롤링 진행
            content, email, reporter_name = crawl_article(url)
            
            if content:
                # 3. 크롤링한 데이터 반영 (본문, 요약 3문장, 기자 이메일)
                news.content = content
                news.summary = extract_summary(content)
                
                # 기자 이름 추출 시 DB에 없으면 생성, reporter_id 연결
                if reporter_name:
                    if not news.reporter or news.reporter.name in ["Unknown", "알 수 없음", "김철수"]:
                        existing_rep = db.query(Reporter).filter_by(name=reporter_name).first()
                        if not existing_rep:
                            existing_rep = Reporter(name=reporter_name, press_id=news.press_id)
                            db.add(existing_rep)
                            db.flush()
                        news.reporter_id = existing_rep.id
                
                # 외래키로 연결된 최신 Reporter 객체에 이메일 채우기
                if email and news.reporter and not news.reporter.email:
                    news.reporter.email = email
                    
                updated_count += 1
                pr_name = reporter_name if reporter_name else '알수없음'
                print(f"[OK] 추출 성공 (기자: {pr_name}, 메일: {email if email else '없음'}): {news.title[:15]}...")
            else:
                print(f"[FAIL] 추출 실패: {news.title[:15]}...")
                
            time.sleep(1)
            
        db.commit() # 전체 UPDATE를 커밋
        print(f"\n[완료] 지능형 크롤링 완료: {updated_count}개 추가 완료! (스킵 {skipped_count}개)")

    except Exception as e:
        db.rollback()
        print(f"[ERROR] DB 본문 업데이트 중 에러 발생: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    update_empty_contents()

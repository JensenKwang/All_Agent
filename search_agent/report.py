import sys
sys.stdout.reconfigure(encoding='utf-8')

from database import SessionLocal
from models import Press, News, Reporter
from sqlalchemy import func

def print_report():
    db = SessionLocal()
    try:
        print("="*50)
        print(" [검색 AI 데이터 통계 리포트] ")
        print("="*50)
        
        # 1. 언론사별 기사 개수
        print("\n[언론사별 기사 개수]")
        # Press를 기준으로 조인한 뒤, 묶어서 (그룹바이) 세어줌
        press_stats = db.query(Press.name, func.count(News.id)).outerjoin(News).group_by(Press.id).all()
        for p_name, count in press_stats:
            print(f" - {p_name}: {count}건")
            
        # 2. 본문 수집(크롤링) 성공 통계
        total_news = db.query(News).count()
        success_news = db.query(News).filter(News.content != None, News.content != "").count()
        
        print("\n[본문 수집 성공률]")
        if total_news == 0:
            print(" 현재 저장된 데이터가 없습니다.")
        else:
            rate = (success_news / total_news) * 100
            print(f" - 전체 수집된 URL: {total_news}건")
            print(f" - 본문 크롤링 성공: {success_news}건")
            print(f" - 수집 성공률: {rate:.1f}%")
            
        print("="*50)
            
    except Exception as e:
        print(f"[ERROR] 통계 산출 중 에러 발생: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    print_report()

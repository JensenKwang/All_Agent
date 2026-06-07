"""
threads_collector.py
Threads Graph API를 이용한 인플루언서 계정 및 포스트 메트릭 수집 모듈.

사용법:
    from threads_collector import run_threads_collection
    run_threads_collection(access_token="...")
"""

import os
import math
import time
from datetime import datetime
from dotenv import load_dotenv
import requests
from database import SessionLocal, save_threads_accounts_to_db, save_threads_posts_to_db

load_dotenv()

THREADS_API_BASE = "https://graph.threads.net/v1.0"

SEMICONDUCTOR_KEYWORDS = [
    "반도체", "HBM", "TSMC", "삼성전자", "SK하이닉스",
    "파운드리", "엔비디아", "메모리", "NAND", "DRAM",
    "AI반도체", "CoWoS", "패키징", "웨이퍼", "fab",
    "semiconductor", "chipmaker", "chip", "CXL",
]

# 수집할 인플루언서 Threads 계정 user_id 목록
# 실제 반도체 관련 인플루언서 계정 ID를 여기에 추가
DEFAULT_INFLUENCER_IDS: list[str] = []


class ThreadsCollector:
    def __init__(self, access_token: str):
        self.access_token = access_token
        self.session = requests.Session()
        self.session.params = {"access_token": access_token}

    def _api_get(self, endpoint: str, params: dict = None) -> dict | None:
        """Threads Graph API GET 요청 공통 래퍼."""
        url = f"{THREADS_API_BASE}{endpoint}"
        extra_params = params or {}
        for attempt in range(2):
            try:
                resp = self.session.get(url, params=extra_params, timeout=10)
                if resp.status_code == 200:
                    return resp.json()
                if resp.status_code == 429:
                    print("[Threads API] Rate Limit → 60초 대기 후 재시도...")
                    time.sleep(60)
                    continue
                if resp.status_code == 401:
                    print("[Threads API] 토큰 만료 또는 권한 없음. 재인증이 필요합니다.")
                    return None
                print(f"[Threads API] 오류 {resp.status_code}: {resp.text[:200]}")
                return None
            except Exception as e:
                print(f"[Threads API] 요청 실패: {e}")
                return None
        return None

    def fetch_my_profile(self) -> dict | None:
        """본인 계정 프로필 조회 (/me)."""
        data = self._api_get("/me", {
            "fields": "id,username,followers_count,is_verified"
        })
        if not data:
            return None
        return {
            "account_id": str(data.get("id", "")),
            "username": data.get("username", ""),
            "followers": data.get("followers_count") or 0,
            "is_verified": 1 if data.get("is_verified") else 0,
        }

    def fetch_account_profile(self, user_id: str) -> dict | None:
        """특정 계정 프로필 조회."""
        data = self._api_get(f"/{user_id}", {
            "fields": "id,username,followers_count,is_verified"
        })
        if not data:
            return None
        return {
            "account_id": str(data.get("id", "")),
            "username": data.get("username", ""),
            "followers": data.get("followers_count") or 0,
            "is_verified": 1 if data.get("is_verified") else 0,
        }

    def fetch_user_posts(self, user_id: str, limit: int = 25) -> list[dict]:
        """특정 계정의 최근 포스트 메트릭 조회."""
        data = self._api_get(f"/{user_id}/threads", {
            "fields": "id,text,timestamp,like_count,reply_count,repost_count",
            "limit": min(limit, 100),
        })
        if not data or "data" not in data:
            return []

        posts = []
        for item in data["data"]:
            posts.append({
                "post_id": str(item.get("id", "")),
                "content": item.get("text", "") or "",
                "like_count": item.get("like_count") or 0,
                "reply_count": item.get("reply_count") or 0,
                "repost_count": item.get("repost_count") or 0,
                "posted_at": item.get("timestamp", ""),
                "account_id": str(user_id),
            })
        return posts

    def filter_semiconductor_posts(self, posts: list[dict]) -> list[dict]:
        """반도체 관련 키워드가 포함된 포스트만 필터링."""
        result = []
        for post in posts:
            content = post.get("content", "") or ""
            if not content:
                continue
            if any(kw.lower() in content.lower() for kw in SEMICONDUCTOR_KEYWORDS):
                result.append(post)
        return result

    def calculate_reliability_score(self, account: dict, posts: list[dict]) -> int:
        """
        계정 신뢰도 점수 계산 (0~100).

        - 계정 점수 40%: 인증여부(20) + 팔로워 규모(20)
        - 반도체 포스팅 비중 30%: 키워드 포함 포스트 비율
        - 커뮤니티 10%: 인게이지먼트 상위권 여부
        - 과거 적중률 20%: 초기값 10점 (추후 주가 데이터 연동)
        """
        score = 0

        # 계정 점수 (40점)
        if account.get("is_verified"):
            score += 20
        followers = account.get("followers", 0) or 0
        if followers > 0:
            # log10(1000)=3, log10(100000)=5 → 최대 20점 정규화
            follower_score = min(20, int(math.log10(followers + 1) / 5 * 20))
            score += follower_score

        # 반도체 포스팅 비중 (30점)
        if posts:
            semi_posts = self.filter_semiconductor_posts(posts)
            semi_ratio = len(semi_posts) / len(posts)
            score += int(semi_ratio * 30)

        # 커뮤니티 인게이지먼트 (10점)
        if posts:
            total_engage = sum(
                p.get("like_count", 0) + p.get("reply_count", 0) + p.get("repost_count", 0)
                for p in posts
            )
            avg_engage = total_engage / len(posts)
            # 평균 인게이지먼트 100 이상이면 만점
            engage_score = min(10, int(avg_engage / 100 * 10))
            score += engage_score

        # 과거 적중률 초기값 (20점 중 10점)
        score += 10

        return min(100, score)

    def collect_influencers(self, user_ids: list[str] = None) -> int:
        """인플루언서 계정 프로필 수집 + DB 저장."""
        targets = user_ids or DEFAULT_INFLUENCER_IDS

        # 본인 계정은 항상 포함
        me = self.fetch_my_profile()
        accounts = [me] if me else []

        for uid in targets:
            profile = self.fetch_account_profile(uid)
            if profile:
                posts = self.fetch_user_posts(uid, limit=50)
                profile["reliability_score"] = self.calculate_reliability_score(profile, posts)
                accounts.append(profile)
                print(f"[Threads] 계정 수집: @{profile['username']} (팔로워: {profile['followers']:,})")

        if accounts:
            save_threads_accounts_to_db(accounts)
        return len(accounts)

    def collect_posts(self, user_ids: list[str] = None, limit: int = 25) -> int:
        """각 계정의 포스트 수집 → 반도체 키워드 필터링 → DB 저장."""
        # DB에 등록된 계정 ID 목록 사용
        db = SessionLocal()
        try:
            from models import ThreadsAccount
            registered = db.query(ThreadsAccount).all()
            db_account_ids = [a.account_id for a in registered]
        finally:
            db.close()

        targets = user_ids or db_account_ids
        if not targets:
            print("[Threads] 등록된 계정이 없습니다. collect_influencers()를 먼저 실행하세요.")
            return 0

        all_posts = []
        for uid in targets:
            posts = self.fetch_user_posts(uid, limit=limit)
            filtered = self.filter_semiconductor_posts(posts)
            all_posts.extend(filtered)
            print(f"[Threads] @{uid}: {len(posts)}건 중 반도체 관련 {len(filtered)}건")

        if all_posts:
            save_threads_posts_to_db(all_posts)
        return len(all_posts)


def run_threads_collection(access_token: str = None) -> None:
    """main.py에서 호출하는 진입점 함수."""
    if not access_token:
        from threads_auth import get_access_token
        access_token = get_access_token()
    if not access_token:
        print("[Threads] 액세스 토큰 없음 → 수집 스킵")
        return

    collector = ThreadsCollector(access_token)

    print("[Threads] 인플루언서 계정 수집 중...")
    account_count = collector.collect_influencers()
    print(f"[Threads] 계정 수집 완료: {account_count}개")

    print("[Threads] 포스트 수집 중...")
    post_count = collector.collect_posts(limit=50)
    print(f"[Threads] 포스트 수집 완료: {post_count}개")


if __name__ == "__main__":
    token = os.getenv("THREADS_ACCESS_TOKEN", "")
    if not token:
        from threads_auth import get_access_token
        token = get_access_token()
    if token:
        run_threads_collection(token)
    else:
        print("토큰을 먼저 발급하세요: python threads_auth.py")

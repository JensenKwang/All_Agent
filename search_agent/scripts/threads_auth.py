"""
threads_auth.py
Meta Threads OAuth 2.0 인증 및 액세스 토큰 관리 모듈.

사용법:
    python threads_auth.py   # 최초 토큰 발급
    from threads_auth import get_access_token  # 다른 모듈에서 호출
"""

import os
import json
import ssl
import time
import webbrowser
import threading
from datetime import datetime, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs, urlencode, quote

import requests
from dotenv import load_dotenv, set_key

load_dotenv()

TOKEN_FILE = "token.json"
DOTENV_FILE = ".env"
REDIRECT_URI = "https://localhost:3000/"
SCOPES = "threads_basic,threads_manage_insights"
AUTH_URL_BASE = "https://threads.net/oauth/authorize"
TOKEN_ENDPOINT = "https://graph.threads.net/oauth/access_token"
LONG_LIVED_ENDPOINT = "https://graph.threads.net/access_token"
REFRESH_ENDPOINT = "https://graph.threads.net/refresh_access_token"
API_BASE = "https://graph.threads.net/v1.0"

# 토큰 만료 7일 전부터 갱신 시도
REFRESH_BUFFER_DAYS = 7


# ── 토큰 파일 I/O ─────────────────────────────────────────────

def _load_token() -> dict | None:
    """token.json에서 토큰 정보를 로드. 없거나 파싱 실패 시 None 반환."""
    if not os.path.exists(TOKEN_FILE):
        return None
    try:
        with open(TOKEN_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _save_token(token_data: dict) -> None:
    """token.json 저장 + .env의 THREADS_ACCESS_TOKEN 업데이트."""
    with open(TOKEN_FILE, "w", encoding="utf-8") as f:
        json.dump(token_data, f, ensure_ascii=False, indent=2)
    try:
        set_key(DOTENV_FILE, "THREADS_ACCESS_TOKEN", token_data.get("access_token", ""))
    except Exception as e:
        print(f"[Threads Auth] .env 업데이트 실패 (무시): {e}")
    print(f"[Threads Auth] 토큰 저장 완료 → {TOKEN_FILE}")


def _is_token_valid(token_data: dict) -> bool:
    """만료 7일 전까지는 유효로 판단."""
    issued_at_str = token_data.get("issued_at")
    expires_in = token_data.get("expires_in", 0)
    if not issued_at_str or not expires_in:
        return False
    try:
        issued_at = datetime.fromisoformat(issued_at_str)
        expires_at = issued_at + timedelta(seconds=expires_in)
        return datetime.now() < (expires_at - timedelta(days=REFRESH_BUFFER_DAYS))
    except Exception:
        return False


def _is_near_expiry(token_data: dict) -> bool:
    """만료 7일 이내 여부 (갱신 필요)."""
    issued_at_str = token_data.get("issued_at")
    expires_in = token_data.get("expires_in", 0)
    if not issued_at_str or not expires_in:
        return True
    try:
        issued_at = datetime.fromisoformat(issued_at_str)
        expires_at = issued_at + timedelta(seconds=expires_in)
        return datetime.now() >= (expires_at - timedelta(days=REFRESH_BUFFER_DAYS))
    except Exception:
        return True


# ── 토큰 교환 ─────────────────────────────────────────────────

def _exchange_code_for_token(code: str, app_id: str, app_secret: str) -> dict | None:
    """Authorization Code → 단기 Access Token (1시간) 교환."""
    try:
        resp = requests.post(TOKEN_ENDPOINT, data={
            "client_id": app_id,
            "client_secret": app_secret,
            "grant_type": "authorization_code",
            "redirect_uri": REDIRECT_URI,
            "code": code,
        }, timeout=10)
        if resp.status_code == 200:
            return resp.json()
        print(f"[Threads Auth] 단기 토큰 교환 실패: {resp.status_code} {resp.text}")
    except Exception as e:
        print(f"[Threads Auth] 단기 토큰 요청 오류: {e}")
    return None


def _exchange_short_to_long(short_token: str, app_secret: str) -> dict | None:
    """단기 토큰(1시간) → 장기 토큰(60일) 교환."""
    try:
        resp = requests.get(LONG_LIVED_ENDPOINT, params={
            "grant_type": "th_exchange_token",
            "client_secret": app_secret,
            "access_token": short_token,
        }, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            data["issued_at"] = datetime.now().isoformat()
            data["is_long_lived"] = True
            return data
        print(f"[Threads Auth] 장기 토큰 교환 실패: {resp.status_code} {resp.text}")
    except Exception as e:
        print(f"[Threads Auth] 장기 토큰 요청 오류: {e}")
    return None


def _refresh_long_lived_token(access_token: str) -> dict | None:
    """장기 토큰 갱신 (60일 만료 전 재발급)."""
    try:
        resp = requests.get(REFRESH_ENDPOINT, params={
            "grant_type": "th_refresh_token",
            "access_token": access_token,
        }, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            data["issued_at"] = datetime.now().isoformat()
            data["is_long_lived"] = True
            return data
        print(f"[Threads Auth] 토큰 갱신 실패: {resp.status_code} {resp.text}")
    except Exception as e:
        print(f"[Threads Auth] 토큰 갱신 요청 오류: {e}")
    return None


# ── OAuth 콜백 서버 ───────────────────────────────────────────

class _CallbackHandler(BaseHTTPRequestHandler):
    """localhost:3000에서 OAuth 리다이렉트를 수신하는 임시 핸들러."""

    def do_GET(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)

        if "code" in params:
            self.server.auth_code = params["code"][0]
            self.server.auth_error = None
            body = "<html><body><h2>Threads 인증 완료!</h2><p>이 창을 닫아도 됩니다.</p></body></html>".encode("utf-8")
        elif "error" in params:
            self.server.auth_code = None
            self.server.auth_error = params.get("error_description", ["알 수 없는 오류"])[0]
            body = f"<html><body><h2>인증 실패</h2><p>{self.server.auth_error}</p></body></html>".encode("utf-8")
        else:
            self.server.auth_code = None
            self.server.auth_error = "code 파라미터 없음"
            body = "<html><body><h2>잘못된 요청</h2></body></html>".encode("utf-8")

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass  # 불필요한 서버 로그 억제


def _make_self_signed_cert():
    """자체서명 SSL 인증서 생성 (cryptography 라이브러리 사용)."""
    from cryptography import x509
    from cryptography.x509.oid import NameOID
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    import ipaddress

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, "localhost"),
    ])
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.utcnow())
        .not_valid_after(datetime.utcnow() + timedelta(days=1))
        .add_extension(
            x509.SubjectAlternativeName([
                x509.DNSName("localhost"),
                x509.IPAddress(ipaddress.IPv4Address("127.0.0.1")),
            ]),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )

    cert_pem = cert.public_bytes(serialization.Encoding.PEM)
    key_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    )
    return cert_pem, key_pem


def _get_auth_code_via_browser(app_id: str) -> str | None:
    """
    브라우저 열기 → 콜백 서버로 code 수신.
    HTTPS 실패 시 URL 수동 입력 모드로 fallback.
    """
    auth_params = {
        "client_id": app_id,
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPES,
        "response_type": "code",
    }
    auth_url = AUTH_URL_BASE + "?" + urlencode(auth_params)

    # HTTPS 서버 기동 시도
    server = None
    try:
        import tempfile

        cert_pem, key_pem = _make_self_signed_cert()

        with tempfile.NamedTemporaryFile(delete=False, suffix=".pem") as cf:
            cf.write(cert_pem)
            cert_path = cf.name
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pem") as kf:
            kf.write(key_pem)
            key_path = kf.name

        server = HTTPServer(("localhost", 3000), _CallbackHandler)
        server.auth_code = None
        server.auth_error = None

        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(cert_path, key_path)
        server.socket = ctx.wrap_socket(server.socket, server_side=True)

        print(f"\n[Threads Auth] 브라우저에서 인증을 진행해 주세요.")
        print(f"  (브라우저가 '연결이 안전하지 않음'을 표시하면 '고급 → 계속 진행' 클릭)")
        webbrowser.open(auth_url)

        # 최대 120초 대기
        deadline = time.time() + 120
        while time.time() < deadline:
            server.handle_request()
            if server.auth_code or server.auth_error:
                break

        if server.auth_error:
            print(f"[Threads Auth] 인증 오류: {server.auth_error}")
            return None
        return server.auth_code

    except ImportError:
        print("[Threads Auth] cryptography 미설치 → 수동 입력 모드로 전환")
    except OSError as e:
        print(f"[Threads Auth] 서버 기동 실패: {e} → 수동 입력 모드로 전환")
    except Exception as e:
        print(f"[Threads Auth] HTTPS 서버 오류: {e} → 수동 입력 모드로 전환")
    finally:
        if server:
            try:
                server.server_close()
            except Exception:
                pass
        # 임시 파일 정리
        for path in [locals().get("cert_path"), locals().get("key_path")]:
            if path and os.path.exists(path):
                try:
                    os.unlink(path)
                except Exception:
                    pass

    # ── 수동 입력 fallback ──
    print(f"\n[Threads Auth] 아래 URL을 브라우저에서 열고 인증 후,")
    print(f"  리다이렉트된 전체 URL을 복사해서 붙여넣으세요.\n")
    print(f"  {auth_url}\n")
    webbrowser.open(auth_url)
    redirected_url = input("리다이렉트된 URL 붙여넣기: ").strip()
    try:
        parsed = urlparse(redirected_url)
        params = parse_qs(parsed.query)
        return params.get("code", [None])[0]
    except Exception:
        return None


# ── 메인 진입점 ───────────────────────────────────────────────

def get_access_token() -> str | None:
    """
    유효한 Threads 액세스 토큰을 반환하는 메인 진입점.

    1. token.json 로드 → 유효하면 즉시 반환
    2. 만료 7일 이내 → 갱신 시도
    3. 토큰 없음/갱신 실패 → 전체 OAuth flow 실행

    Returns:
        access_token 문자열 또는 None (실패 시)
    """
    app_id = os.getenv("THREADS_APP_ID", "")
    app_secret = os.getenv("THREADS_APP_SECRET", "")

    if not app_id or not app_secret:
        print("[Threads Auth] THREADS_APP_ID 또는 THREADS_APP_SECRET가 .env에 없습니다.")
        return None

    # 1. 기존 토큰 확인
    token_data = _load_token()
    if token_data:
        if _is_token_valid(token_data):
            print("[Threads Auth] 유효한 토큰 사용 중.")
            return token_data["access_token"]

        if _is_near_expiry(token_data) and token_data.get("is_long_lived"):
            print("[Threads Auth] 토큰 만료 임박 → 갱신 시도...")
            refreshed = _refresh_long_lived_token(token_data["access_token"])
            if refreshed:
                _save_token(refreshed)
                return refreshed["access_token"]
            print("[Threads Auth] 갱신 실패 → 재인증 진행")

    # 2. 전체 OAuth flow
    print("[Threads Auth] 새 토큰 발급을 시작합니다...")
    code = _get_auth_code_via_browser(app_id)
    if not code:
        print("[Threads Auth] Authorization code 획득 실패.")
        return None

    short = _exchange_code_for_token(code, app_id, app_secret)
    if not short:
        return None

    long_token = _exchange_short_to_long(short["access_token"], app_secret)
    if not long_token:
        # 장기 토큰 교환 실패 시 단기 토큰이라도 저장
        short["issued_at"] = datetime.now().isoformat()
        short["is_long_lived"] = False
        _save_token(short)
        return short["access_token"]

    _save_token(long_token)
    return long_token["access_token"]


if __name__ == "__main__":
    token = get_access_token()
    if token:
        print(f"\n토큰 발급 성공: {token[:20]}...")
    else:
        print("\n토큰 발급 실패.")

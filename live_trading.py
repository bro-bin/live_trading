import websocket
import requests
import json
import time
import threading
import yaml
import pandas as pd
from datetime import datetime, timedelta
import os
# _________________________ PART 1: 클래스 및 함수 정의  __________________________
# ==============================================================================
# ========== [수정] 디스코드 웹훅 설정 (초기값 None) ==========
# ==============================================================================
# main 함수에서 config.yaml을 읽어와 이 변수에 할당할 것입니다.
DISCORD_WEBHOOK_URL = None 

def send_discord_alert(message):
    """디스코드 웹훅으로 메시지 전송"""
    global DISCORD_WEBHOOK_URL  # 전역 변수 사용 선언
    
    # URL이 설정되지 않았으면 전송하지 않음
    if not DISCORD_WEBHOOK_URL:
        return

    try:
        now = datetime.now().strftime("[%Y-%m-%d %H:%M:%S]")
        payload = {
            "content": f"`{now}` {message}"
        }
        requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=2)
    except Exception as e:
        print(f"❌ 디스코드 전송 실패: {e}")

# ==============================================================================
# ========== Class 1: 기본 설정 및 토큰 관리 ==========
# ==============================================================================
class KISConfig:
    """한국투자증권 API 설정 및 토큰 관리 클래스"""
    
    def __init__(self, config_path='config.yaml'):
        """config.yaml 불러오기"""
        print("\n📋 설정 파일 로드 중...")
        
        with open(config_path, encoding='UTF-8') as f:
            cfg = yaml.safe_load(f)
        
        # API 인증 정보
        self.app_key = cfg['APP_KEY']
        self.app_secret = cfg['APP_SECRET']
        self.account_no = cfg['ACCOUNT_NO']
        self.base_url = cfg['URL_BASE']
        
        # 계좌 정보 분리
        self.cano = cfg['CANO']
        self.acnt_prdt_cd = cfg['ACNT_PRDT_CD']

        # [추가] 디스코드 웹훅 URL 로드
        # config.yaml에 키가 없으면 None 반환
        self.discord_webhook_url = cfg.get('DISCORD_WEBHOOK_URL', None)
        
        # 실전/모의 판단
        self.is_real = "vts" not in self.base_url.lower()
        
        # 웹소켓 URL
        self.ws_url = "ws://ops.koreainvestment.com:21000" if self.is_real else "ws://ops.koreainvestment.com:31000"
        
        # 접근 토큰
        self.access_token = None
        self.ws_approval_key = None  # ⬅️ [추가] 웹소켓 접속키 저장 변수
        
        print(f"✅ 설정 로드 완료")
        print(f"   - 환경: {'실전투자' if self.is_real else '모의투자'}")
        print(f"   - 계좌: {self.account_no}")
        print(f"   - URL: {self.base_url}")
    
    def issue_token(self):
        """REST API용 접근 토큰 발급 (유효기간 24시간)"""
        try:
            print("\n🔑 접근 토큰 발급 중...")
            
            url = f"{self.base_url}/oauth2/tokenP"
            headers = {"content-type": "application/json"}
            data = {
                "grant_type": "client_credentials",
                "appkey": self.app_key,
                "appsecret": self.app_secret
            }
            
            response = requests.post(url, headers=headers, data=json.dumps(data))
            
            if response.status_code == 200:
                result = response.json()
                self.access_token = result['access_token']
                expires_in = result.get('expires_in', 'N/A')
                
                print(f"✅ 접근 토큰 발급 성공")
                if expires_in != 'N/A':
                    print(f"   만료시간: {expires_in}초 ({int(expires_in)/3600:.1f}시간)")
                return True
            else:
                print(f"❌ 접근 토큰 발급 실패: {response.status_code}")
                print(f"   응답: {response.text}")
                return False
                
        except Exception as e:
            print(f"❌ 접근 토큰 발급 중 오류: {e}")
            return False
    
    def revoke_token(self):
        """접근 토큰 반납"""
        try:
            print("\n🔓 접근 토큰 반납 중...")
            
            if not self.access_token:
                print("⚠️  반납할 토큰이 없습니다.")
                return True
            
            url = f"{self.base_url}/oauth2/revokeP"
            headers = {"content-type": "application/json"}
            body = {
                "appkey": self.app_key,
                "appsecret": self.app_secret,
                "token": self.access_token
            }
            
            response = requests.post(url, headers=headers, data=json.dumps(body))
            
            if response.status_code == 200:
                print("✅ 접근 토큰 반납 완료")
                self.access_token = None
                return True
            else:
                print(f"⚠️  토큰 반납 실패: {response.status_code}")
                return False
                
        except Exception as e:
            print(f"❌ 토큰 반납 중 오류: {e}")
            return False
    
    def issue_websocket_key(self):
        """[공통] 웹소켓 접속키 발급 (1회성)"""
        try:
            print("🔑 [공통] 웹소켓 접속키 발급 중...")
            
            url = f"{self.base_url}/oauth2/Approval"
            headers = {"content-type": "application/json"}
            body = {
                "grant_type": "client_credentials",
                "appkey": self.app_key,
                "secretkey": self.app_secret
            }
            
            response = requests.post(url, headers=headers, data=json.dumps(body))
            
            if response.status_code == 200:
                result = response.json()
                self.ws_approval_key = result.get('approval_key') # ⬅️ 공통 변수에 저장
                if self.ws_approval_key:
                    print(f"✅ [공통] 웹소켓 접속키 발급 성공")
                    return True
                else:
                    print("❌ 응답에 approval_key가 없습니다.")
                    return False
            else:
                print(f"❌ [공통] 웹소켓 접속키 발급 실패: {response.status_code}")
                return False
                
        except Exception as e:
            print(f"❌ [공통] 웹소켓 접속키 발급 중 오류: {e}")
            return False


# ==============================================================================
# ========== Class 2: 바스켓 계산용 웹소켓 ==========
# ==============================================================================
class BasketWebSocket:
    """바스켓 구성을 위한 개별 종목 실시간 가격 수신 웹소켓"""
    
    def __init__(self, config: KISConfig):
        """초기화"""
        self.config = config
        self.ws = None
        self.is_connected = False
        
        # 실시간 가격 저장
        self.current_prices = {}  # {종목명: 가격}
        self.price_lock = threading.Lock()
        
        # 구독할 삼성그룹 종목
        self.stock_list = {
            "삼성E&A": "028050",
            "삼성SDI": "006400",
            "삼성물산": "028260",
            "삼성생명": "032830",
            "삼성에스디에스": "018260",
            "삼성전기": "009150",
            "삼성전자": "005930",
            "삼성중공업": "010140",
            "삼성증권": "016360",
            "삼성카드": "029780",
            "삼성화재": "000810",
            "에스원": "012750",
            "제일기획": "030000",
            "호텔신라": "008770"
        }
        
        print(f"\n📦 바스켓 웹소켓 초기화 ({len(self.stock_list)}개 종목)")
    
    
    def connect(self):
        """웹소켓 연결"""
        try:
            print("\n🌐 바스켓 웹소켓 연결 시작...")
            
            # 1. [수정] 공통 접속키가 있는지 확인
            if not self.config.ws_approval_key:
                print("❌ 바스켓 WS: 공통 접속키가 없습니다.")
                return False
            
            # 2. 웹소켓 연결
            self.ws = websocket.WebSocketApp(
                self.config.ws_url,
                on_message=self._on_message,
                on_error=self._on_error,
                on_close=self._on_close,
                on_open=self._on_open
            )
            
            # 별도 스레드에서 실행
            ws_thread = threading.Thread(
                target=self.ws.run_forever,
                kwargs={'ping_interval': 20, 'ping_timeout': 5}
            )
            ws_thread.daemon = True
            ws_thread.start()
            
            # 연결 대기
            for i in range(10):
                if self.is_connected:
                    print("✅ 바스켓 웹소켓 연결 성공!")
                    return True
                time.sleep(0.5)
            
            print("⚠️  바스켓 웹소켓 연결 타임아웃")
            return False
            
        except Exception as e:
            print(f"❌ 바스켓 웹소켓 연결 실패: {e}")
            return False
    
    def reconnect(self):
        """웹소켓 재연결 및 재구독"""
        msg = "🔄 [Basket WS] 재연결 시도 중..."
        print(f"\n{msg}")
        send_discord_alert(msg)
        
        # 1. 기존 연결 정리
        self.close()
        time.sleep(1)  # 소켓 정리 대기
        
        # 2. 재연결 시도
        if self.connect():
            success_msg = "✅ [Basket WS] 재연결 성공! 재구독을 진행합니다."
            print(success_msg)
            send_discord_alert(success_msg)
            
            # 3. 재구독
            self.subscribe()
            return True
        else:
            fail_msg = "❌ [Basket WS] 재연결 실패."
            print(fail_msg)
            send_discord_alert(fail_msg)
            return False
    
    def subscribe(self):
        """개별 종목 현재가 구독"""
        if not self.is_connected or not self.ws:
            print("❌ 웹소켓이 연결되지 않았습니다.")
            return False
        
        print("\n📡 종목 구독 시작...")
        
        try:
            for stock_name, stock_code in self.stock_list.items():
                subscribe_data = {
                    "header": {
                        "approval_key": self.config.ws_approval_key,
                        "custtype": "P",
                        "tr_type": "1",
                        "content-type": "utf-8"
                    },
                    "body": {
                        "input": {
                            "tr_id": "H0STCNT0",  # 주식 체결가
                            "tr_key": stock_code
                        }
                    }
                }
                
                self.ws.send(json.dumps(subscribe_data))
                print(f"  ✓ {stock_name} ({stock_code})")
                time.sleep(0.1)
            
            print(f"✅ 총 {len(self.stock_list)}개 종목 구독 완료!")
            return True
            
        except Exception as e:
            print(f"❌ 구독 중 오류: {e}")
            return False
        
    def unsubscribe(self):
        """개별 종목 구독 해제"""
        if not self.is_connected or not self.ws:
            print("⚠️  웹소켓이 연결되지 않아 구독 해제를 건너뜁니다.")
            return False
        
        print("\n📡 바스켓 종목 구독 해제 중...")
        
        try:
            for stock_name, stock_code in self.stock_list.items():
                unsubscribe_data = {
                    "header": {
                        "approval_key": self.config.ws_approval_key,
                        "custtype": "P",
                        "tr_type": "2",  # ✅ "1"(구독) → "2"(해제)
                        "content-type": "utf-8"
                    },
                    "body": {
                        "input": {
                            "tr_id": "H0STCNT0",
                            "tr_key": stock_code
                        }
                    }
                }
                
                self.ws.send(json.dumps(unsubscribe_data))
                time.sleep(0.2)  # 빠르게 해제
            
            print(f"✅ 바스켓 {len(self.stock_list)}개 종목 구독 해제 완료!")
            return True
        
        except Exception as e:
            print(f"⚠️  구독 해제 중 오류 (무시): {e}")
            return False
    
    def _on_open(self, ws):
        """연결 성공"""
        print("✅ 바스켓 웹소켓 연결 완료")
        self.is_connected = True
    

    def _on_message(self, ws, message):
        """메시지 수신"""
        try:
            # PINGPONG 처리
            if message == "PINGPONG":
                ws.pong(message)
                return
            
            # 실시간 데이터 처리
            if message.startswith('0|') or message.startswith('1|'):
                parts = message.split('|')
                if len(parts) < 4:
                    return
                
                tr_id = parts[1]
                data_body = parts[3]
                
                if tr_id == "H0STCNT0":  # 체결가
                    data_parts = data_body.split('^')
                    if len(data_parts) >= 3:
                        stock_code = data_parts[0]
                        current_price = int(data_parts[2])
                        
                        # 종목명 찾기
                        stock_name = None
                        for name, code in self.stock_list.items():
                            if code == stock_code:
                                stock_name = name
                                break
                        
                        if stock_name:
                            with self.price_lock:
                                # ✅ 수정: 가격과 종목코드를 함께 저장
                                self.current_prices[stock_name] = {
                                    "price": current_price,
                                    "code": stock_code
                                }
                            
                            # timestamp = datetime.now().strftime("%H:%M:%S")
                            # print(f"[{timestamp}] 📈 {stock_name}: {current_price:,}원")
            
            # JSON 응답 (구독 확인)
            elif message.startswith('{'):
                try:
                    msg_json = json.loads(message)
                    header = msg_json.get('header', {})
                    body = msg_json.get('body', {})
                    tr_key = header.get('tr_key', 'N/A')

                    if body.get('rt_cd') != '0' and header.get('tr_type') == '1':
                        # 실패 시 에러 로그 출력(상세)
                        print(f"==================================================")
                        print(f" ❌ [WS 구독 실패] 종목코드: {tr_key}")
                        print(f"    - 응답 코드: {body.get('rt_cd')}")
                        print(f"    - 응답 메시지: {body.get('msg1')}")
                        print(f"==================================================")

                except Exception as e:
                    print(f"⚠️ JSON 응답 처리 오류: {e} | 원본: {message}")
            
        
        except Exception as e:
            print(f"⚠️  메시지 처리 오류: {e}")
            
    
    def _on_error(self, ws, error):
        """에러"""
        print(f"❌ 바스켓 웹소켓 에러: {error}")
    
    def _on_close(self, ws, close_status_code, close_msg):
        """연결 종료"""
        print(f"🔌 바스켓 웹소켓 연결 종료")
        self.is_connected = False
    
    def get_current_prices(self):
        """현재 가격 조회"""
        with self.price_lock:
            return dict(self.current_prices)
    
    def close(self):
        """연결 종료"""
        if self.ws:
            
            self.ws.close()
            print("🔌 바스켓 웹소켓 연결 종료됨")


# ==============================================================================
# ========== Class 3: 모니터링 웹소켓 (ETF diff 계산용) ==========
# ==============================================================================
class MonitoringWebSocket:
    """ETF 괴리(diff) 계산을 위한 현재가/NAV 수신 웹소켓"""
    
    def __init__(self, config: KISConfig):
        """초기화"""
        self.config = config
        self.ws = None
        self.is_connected = False

        # 하드코딩 또는 config의 공통 approval_key 사용
        self.approval_key = "a34f9329-c5ef-47b6-8030-30b9adb7f40c"
        
        # ETF 정보
        self.etf_code = "102780"  # KODEX 삼성그룹
        self.etf_name = "KODEX 삼성그룹"
        
        # 실시간 데이터 저장
        self.etf_data = {
            "nav": None,
            "current_price": None,
            "diff": None,
            "nav_time": None,
            "price_time": None
        }
        self.data_lock = threading.Lock()
        
        print(f"\n🔍 모니터링 웹소켓 초기화")
        print(f"   - 종목: {self.etf_name} ({self.etf_code})")
        if self.approval_key:
            print("   - approval_key: (하드코딩 사용)")
        else:
            print("   - approval_key: (공통키 사용)")
    
    def connect(self):
        """웹소켓 연결"""
        try:
            print("\n🌐 모니터링 웹소켓 연결 시작...")
            
            # 1. 허용 키 확인: 하드코드된 approval_key 우선 사용
            if not self.approval_key:
                print("❌ 모니터링 WS: 공통 접속키 또는 하드코딩된 approval_key가 없습니다.")
                return False
            
            # 2. 웹소켓 연결
            self.ws = websocket.WebSocketApp(
                self.config.ws_url,
                on_message=self._on_message,
                on_error=self._on_error,
                on_close=self._on_close,
                on_open=self._on_open
            )
            
            # 별도 스레드에서 실행
            ws_thread = threading.Thread(
                target=self.ws.run_forever,
                kwargs={'ping_interval': 20, 'ping_timeout': 5}
            )
            ws_thread.daemon = True
            ws_thread.start()
            
            # 연결 대기
            for i in range(10):
                if self.is_connected:
                    print("✅ 모니터링 웹소켓 연결 성공!")
                    return True
                time.sleep(0.5)
            
            print("⚠️  모니터링 웹소켓 연결 타임아웃")
            return False
            
        except Exception as e:
            print(f"❌ 모니터링 웹소켓 연결 실패: {e}")
            return False
    
    def reconnect(self):
        """웹소켓 재연결 및 재구독"""
        msg = "🔄 [Monitoring WS] 재연결 시도 중..."
        print(f"\n{msg}")
        send_discord_alert(msg)
        
        # 1. 기존 연결 정리
        self.close()
        time.sleep(1)
        
        # 2. 재연결 시도
        if self.connect():
            success_msg = "✅ [Monitoring WS] 재연결 성공! ETF 정보를 다시 구독합니다."
            print(success_msg)
            send_discord_alert(success_msg)
            
            # 3. 재구독
            self.subscribe()
            return True
        else:
            fail_msg = "❌ [Monitoring WS] 재연결 실패."
            print(fail_msg)
            send_discord_alert(fail_msg)
            return False
    
    def subscribe(self):
        """ETF 현재가 및 NAV 구독"""
        if not self.is_connected or not self.ws:
            print("❌ 웹소켓이 연결되지 않았습니다.")
            return False
        
        print("\n📡 ETF 데이터 구독 시작...")
        
        try:
            # 헤더에 들어갈 approval_key 결정 (하드코딩 우선)
            approval = self.approval_key if self.approval_key else self.config.ws_approval_key

            # 1. NAV 구독
            nav_subscribe = {
                "header": {
                    "approval_key": approval,
                    "custtype": "P",
                    "tr_type": "1",
                    "content-type": "utf-8"
                },
                "body": {
                    "input": {
                        "tr_id": "H0STNAV0",
                        "tr_key": self.etf_code
                    }
                }
            }
            self.ws.send(json.dumps(nav_subscribe))
            print(f"  ✓ NAV 구독 ({self.etf_code})")
            time.sleep(0.5)
            
            # 2. 현재가 구독
            price_subscribe = {
                "header": {
                    "approval_key": self.config.ws_approval_key,
                    "custtype": "P",
                    "tr_type": "1",
                    "content-type": "utf-8"
                },
                "body": {
                    "input": {
                        "tr_id": "H0STCNT0",
                        "tr_key": self.etf_code
                    }
                }
            }
            self.ws.send(json.dumps(price_subscribe))
            print(f"  ✓ 현재가 구독 ({self.etf_code})")
            
            print("✅ ETF 구독 완료!")
            return True
            
        except Exception as e:
            print(f"❌ 구독 중 오류: {e}")
            return False
        
    def unsubscribe(self):
        """ETF 구독 해제"""
        if not self.is_connected or not self.ws:
            print("⚠️  웹소켓이 연결되지 않아 구독 해제를 건너뜁니다.")
            return False
        
        print("\n📡 ETF 데이터 구독 해제 중...")
        
        try:
            approval = self.approval_key if self.approval_key else self.config.ws_approval_key

            # 1. NAV 구독 해제
            nav_unsubscribe = {
                "header": {
                    "approval_key": approval,
                    "custtype": "P",
                    "tr_type": "2",  # ✅ "1"(구독) → "2"(해제)
                    "content-type": "utf-8"
                },
                "body": {
                    "input": {
                        "tr_id": "H0STNAV0",
                        "tr_key": self.etf_code
                    }
                }
            }
            self.ws.send(json.dumps(nav_unsubscribe))
            time.sleep(0.1)
            
            # 2. 현재가 구독 해제
            price_unsubscribe = {
                "header": {
                    "approval_key": self.config.ws_approval_key,
                    "custtype": "P",
                    "tr_type": "2",  # ✅ "1"(구독) → "2"(해제)
                    "content-type": "utf-8"
                },
                "body": {
                    "input": {
                        "tr_id": "H0STCNT0",
                        "tr_key": self.etf_code
                    }
                }
            }
            self.ws.send(json.dumps(price_unsubscribe))
            time.sleep(0.1)
            
            print("✅ ETF 데이터 구독 해제 완료!")
            return True
            
        except Exception as e:
            print(f"⚠️  구독 해제 중 오류 (무시): {e}")
            return False
    
    def _on_open(self, ws):
        """연결 성공"""
        print("✅ 모니터링 웹소켓 연결 완료")
        self.is_connected = True
    
    def _on_message(self, ws, message):
        """메시지 수신"""
        try:
            # PINGPONG 처리
            if message == "PINGPONG":
                ws.pong(message)
                return
            
            # 실시간 데이터 처리
            if message.startswith('0|') or message.startswith('1|'):
                parts = message.split('|')
                if len(parts) < 4:
                    return
                
                tr_id = parts[1]
                data_str = parts[3]
                
                # NAV 데이터
                if tr_id == "H0STNAV0":
                    fields = data_str.split('^')
                    if len(fields) > 1:
                        nav_value = float(fields[1])
                        
                        with self.data_lock:
                            self.etf_data["nav"] = nav_value
                            self.etf_data["nav_time"] = datetime.now().strftime("%H:%M:%S")
                            
                            # diff 계산
                            if self.etf_data["current_price"] is not None:
                                self._calculate_diff()
                
                # 현재가 데이터
                elif tr_id == "H0STCNT0":
                    fields = data_str.split('^')
                    if len(fields) > 2:
                        current_price = int(fields[2])
                        
                        with self.data_lock:
                            self.etf_data["current_price"] = current_price
                            self.etf_data["price_time"] = datetime.now().strftime("%H:%M:%S")
                            
                            # diff 계산
                            if self.etf_data["nav"] is not None:
                                self._calculate_diff()
            
            # JSON 응답 (구독 확인)
            elif message.startswith('{'):
                msg_json = json.loads(message)
                if msg_json.get('body', {}).get('rt_cd') == '0':
                    print(f"  ✓ 구독 성공")
        
        except Exception as e:
            print(f"⚠️  메시지 처리 오류: {e}")
    
    def _calculate_diff(self):
        """
        괴리 계산 (현재가 - NAV)
        ⚠️ data_lock 내부에서 호출
        """
        nav = self.etf_data["nav"]
        price = self.etf_data["current_price"]
        
        if nav is not None and price is not None and nav != 0:
            self.etf_data["diff"] = price - nav
    
    def _on_error(self, ws, error):
        """에러"""
        print(f"❌ 모니터링 웹소켓 에러: {error}")
    
    def _on_close(self, ws, close_status_code, close_msg):
        """연결 종료"""
        print(f"🔌 모니터링 웹소켓 연결 종료")
        self.is_connected = False
    
    def get_diff_info(self):
        """현재 괴리 정보 조회"""
        with self.data_lock:
            return dict(self.etf_data)
    
    def close(self):
        """연결 종료"""
        if self.ws:
            
            self.ws.close()
            print("🔌 모니터링 웹소켓 연결 종료됨")

# =============================== end =======================================
# ===========================================================================

from trading_function import buy_etf, sell_etf, buy_basket_direct, sell_basket, clear_all_stocks, save_df_to_csv, get_current_position
# __________________________  PART 2: 전략구현  _______________________________

#전역 변수 추가 (for. run_trading_logic함수)
basket_optimization_counter = 0
cached_basket_quantities = None

### 조건에 따른 매매 실행 함수
def run_trading_logic(config: KISConfig, basket_ws: BasketWebSocket, 
                     monitoring_ws: MonitoringWebSocket, 
                     current_position_type: str):  
    """
    매매 로직 실행 (1초마다 호출)
    
    Returns:
        str: 업데이트된 포지션 상태 (매매 발생 시 변경됨)
    """
    
    global basket_optimization_counter, cached_basket_quantities
    
    timestamp = datetime.now().strftime("%H:%M:%S")
    
    try:
        # STEP 1: diff 모니터링
        diff_info = monitoring_ws.get_diff_info()
        nav = diff_info.get("nav")
        current_price = diff_info.get("current_price")
        diff = diff_info.get("diff")
        
        if nav is not None and current_price is not None and diff is not None:
            print(f"[{timestamp}]  📊 NAV: {nav:>8,.0f}원\n"
                  f"            💰 현재가: {current_price:>8,}원\n"
                  f"            🔍 diff: {diff:>+6,.0f}원\n"
                  f"            📦 포지션: {current_position_type}")
        else:
            nav_status = f"{nav:,.0f}원" if nav is not None else "수신 대기"
            price_status = f"{current_price:,}원" if current_price is not None else "수신 대기"
            print(f"[{timestamp}] ⏳ 데이터 수신 대기 중... (NAV: {nav_status} | ETF현재가: {price_status} | 📦 포지션: {current_position_type})")
            return current_position_type
        
        # STEP 2: 바스켓 수량 최적화
        basket_optimization_counter += 1
        
        if basket_optimization_counter >= 5:
            live_basket_prices = basket_ws.get_current_prices()
            
            valid_prices = all(
                p.get("price", 0) > 0 
                for p in live_basket_prices.values()
            )
            
            if len(live_basket_prices) >= len(basket_ws.stock_list) and valid_prices:
                try:
                    from utils import get_basket_qty
                    cached_basket_quantities = get_basket_qty(live_basket_prices)
                    print(f"[{timestamp}] 🔄 바스켓 최적화 완료 ({len(cached_basket_quantities)}개 종목)")
                except Exception as e:
                    print(f"[{timestamp}] ⚠️  바스켓 최적화 오류: {e}")
            else:
                print(f"[{timestamp}] ⚠️  바스켓 가격 데이터 부족 또는 무효")
            
            basket_optimization_counter = 0
        
        # STEP 3: 현재 포지션 사용 (매개변수)
        position = current_position_type
        
        # STEP 4: tr_id 설정
        if config.is_real:
            buy_tr_id = "TTTC0802U"
            sell_tr_id = "TTTC0801U"
        else:
            buy_tr_id = "VTTC0802U"
            sell_tr_id = "VTTC0801U"
        
        # STEP 5: 매매 조건 체크 및 실행
        
        # 조건 1: diff >= -5 and position == "none" → 바스켓 매수
        if diff >= -5 and position == "none":
            if cached_basket_quantities is not None:
                print(f"\n{'='*80}")
                print(f"⚡ [{timestamp}] [조건 1 충족] diff >= -5 & 포지션 없음 → 바스켓 매수")
                print(f"{'='*80}")
                
                live_basket_prices = basket_ws.get_current_prices()
                
                result = buy_basket_direct(
                    access_token=config.access_token,
                    base_url=config.base_url,
                    app_key=config.app_key,
                    app_secret=config.app_secret,
                    account_no=config.account_no,
                    tr_id=buy_tr_id,
                    live_prices=live_basket_prices
                )
                
                # ✅ 수정: 성공 종목이 있을 때만 포지션 변경
                if result.get("rt_cd") == "0" and result.get("success"):
                    position = "basket"
                    print(f"\n✅ 포지션 업데이트: none → basket")
                    print(f"   성공: {len(result['success'])}개 종목")
                    print(f"   실패: {len(result.get('failed', []))}개 종목")
                else:
                    print(f"\n⚠️  바스켓 매수 실패 - 포지션 유지")
                
                print(f"{'='*80}\n")
            else:
                print(f"[{timestamp}] ⚠️  조건 충족하나 바스켓 최적화 대기 중...")
        
        # 조건 2: diff <= -9 and position == "basket" → 바스켓 매도
        elif diff <= -9 and position == "basket":
            print(f"\n{'='*80}")
            print(f"⚡ [{timestamp}] [조건 2 충족] diff <= -9 & 바스켓 보유 → 바스켓 매도")
            print(f"{'='*80}")
            
            result = sell_basket(
                access_token=config.access_token,
                base_url=config.base_url,
                app_key=config.app_key,
                app_secret=config.app_secret,
                account_no=config.account_no,
                tr_id=sell_tr_id
            )
            
            # ✅ 수정: 성공 종목이 있을 때만 포지션 변경
            if result.get("rt_cd") == "0" and result.get("success"):
                position = "none"
                print(f"\n✅ 포지션 업데이트: basket → none")
                print(f"   성공: {len(result['success'])}개 종목")
                print(f"   실패: {len(result.get('failed', []))}개 종목")
            else:
                print(f"\n⚠️  바스켓 매도 실패 - 포지션 유지")
            
            print(f"{'='*80}\n")
        
        # 조건 3: diff <= -13 and position == "none" → ETF 매수
        elif diff <= -13 and position == "none":
            print(f"\n{'='*80}")
            print(f"⚡ [{timestamp}] [조건 3 충족] diff <= -13 & 포지션 없음 → ETF 매수")
            print(f"{'='*80}")
            
            result = buy_etf(
                access_token=config.access_token,
                base_url=config.base_url,
                app_key=config.app_key,
                app_secret=config.app_secret,
                account_no=config.account_no,
                tr_id=buy_tr_id
            )
            
            # ✅ 수정: 체결 완료 확인 후 포지션 변경
            if result.get("rt_cd") == "0" and result.get("success"):
                position = "etf"
                print(f"\n✅ 포지션 업데이트: none → etf")
                print(f"   체결가: {result['filled_price']:,}원")
                print(f"   수량: {result['filled_qty']}주")
            else:
                print(f"\n⚠️  ETF 매수 실패 - 포지션 유지")
            
            print(f"{'='*80}\n")
        
        # 조건 4: diff >= -9 and position == "etf" → ETF 매도
        elif diff >= -9 and position == "etf":
            print(f"\n{'='*80}")
            print(f"⚡ [{timestamp}] [조건 4 충족] diff >= -9 & ETF 보유 → ETF 매도")
            print(f"{'='*80}")
            
            result = sell_etf(
                access_token=config.access_token,
                base_url=config.base_url,
                app_key=config.app_key,
                app_secret=config.app_secret,
                account_no=config.account_no,
                tr_id=sell_tr_id
            )
            
            # ✅ 수정: 체결 완료 확인 후 포지션 변경
            if result.get("rt_cd") == "0" and result.get("success"):
                position = "none"
                print(f"\n✅ 포지션 업데이트: etf → none")
                try:
                    # success_data = result["success"][0]
                    # print(f"   체결가: {success_data.get('sell_price', 0):,}원")
                    # print(f"   수량: {success_data.get('quantity', 0)}주")
                    # print(f"   손익: {success_data.get('profit', 0):,}원")
                    print(f"   체결가: {result.get('sell_price', 0):,}원")
                    print(f"   수량: {result.get('sell_qty', 0)}주") 
                    print(f"   손익: {result.get('profit', 0):,}원")
                except IndexError:
                    print(f"   ⚠️  매도 성공 응답(결과)을 처리하는 중 오류: {e}")
            else:
                print(f"\n⚠️  ETF 매도 실패 - 포지션 유지")
                # 실패 사유 출력 (디버깅에 도움)
                if result.get("rt_cd") != "0":
                    print(f"   사유: {result.get('msg1', '알 수 없는 오류')}")
                elif not result.get("success"):
                    print(f"   사유: 3단계 체결가 조회 실패 (price_fetch_failed_orders 확인)")
            
            print(f"{'='*80}\n")
        
        # ✅ 추가: 업데이트된 포지션 반환
        return position
        
    except Exception as e:
        print(f"❌ 매매 로직 실행 중 오류: {e}")
        import traceback
        traceback.print_exc()
        return current_position_type  # 오류 발생 시 기존 포지션 유지


# =============================== end =======================================
# ===========================================================================

# _________________________ PART 3: 메인 프로그램 __________________________
if __name__ == "__main__":
    
    # --- main 블록에서 사용할 추가 모듈 임포트 ---
    import threading
    from datetime import time as dt_time, datetime, timedelta
    import time
    import traceback
    
    # --- (중요) trading_function에서 save_df_to_csv 임포트 ---
    try:
        from trading_function import save_df_to_csv, get_current_position
    except ImportError:
        print("="*80)
        print("⚠️  [임포트 오류] trading_function.py에 save_df_to_csv 함수가 없거나")
        print("   live_trading.py PART 2의 from trading_function... 라인에")
        print("   save_df_to_csv가 누락되었습니다. 임포트 목록을 확인해주세요.")
        print("   (예: from trading_function import ..., clear_all_stocks, save_df_to_csv)")
        print("="*80)
        exit()

    
    # ===================================================================
    # 전역 변수 초기화
    # ===================================================================
    
    # --- 전역 객체 변수 ---
    main_config_obj = None
    main_basket_ws_obj = None
    main_monitoring_ws_obj = None

    try:
        # ==================================================================
        #  1. 설정 및 웹소켓 초기화
        # ==================================================================
        print("🚀 자동매매 프로그램을 시작합니다.")
        send_discord_alert("📢 **자동매매 프로그램이 시작되었습니다.**") # [추가]
        main_config_obj = KISConfig(config_path='config.yaml')

        if main_config_obj.discord_webhook_url:
            DISCORD_WEBHOOK_URL = main_config_obj.discord_webhook_url
            print(f"✅ 디스코드 알림이 활성화되었습니다.")
            send_discord_alert("📢 **자동매매 프로그램이 시작되었습니다.** (Config 로드 완료)")
        else:
            print("⚠️ config.yaml에 'DISCORD_WEBHOOK_URL'이 없어 알림이 전송되지 않습니다.")
        
        main_basket_ws_obj = BasketWebSocket(main_config_obj)
        main_monitoring_ws_obj = MonitoringWebSocket(main_config_obj)
        
        # 1-1. (순서 1) 웹소켓 연결
        print("\n" + "-"*30 + " 1. 웹소켓 연결 " + "-"*30)

        # ⬇️ [추가] 두 connect 호출 전에 공통 키를 1회 발급합니다.
        if not main_config_obj.issue_websocket_key():
            raise Exception("공통 웹소켓 접속키 발급에 실패했습니다.")
        
        if not main_basket_ws_obj.connect():
            send_discord_alert("❌ 바스켓 WS 초기 연결 실패") # [추가]
            raise Exception("바스켓 웹소켓(BasketWebSocket) 연결에 실패했습니다.")
        
        if not main_monitoring_ws_obj.connect():
            send_discord_alert("❌ 모니터링 WS 초기 연결 실패") # [추가]
            raise Exception("모니터링 웹소켓(MonitoringWebSocket) 연결에 실패했습니다.")
        
        send_discord_alert("✅ 모든 웹소켓 연결 완료. 장 시작 대기 중...") # [추가]
        print("\n✅ 모든 웹소켓이 성공적으로 연결되었습니다. 장 시작을 대기합니다.")

        # ==================================================================
        #  거래일 루프 (프로그램이 종료되지 않고 매일 반복)
        # ==================================================================
        while True:
            # ======================================================
            # 2. 장 시작 대기 (09:00:00)
            # ======================================================
            print("\n" + "-"*30 + " 2. 장 시작 대기 " + "-"*30)
            start_time = dt_time(9, 0, 0)
            end_time = dt_time(15, 15, 0)  # 매매 종료 시간
            
            # ✅ 수정: 1초마다 확인
            while datetime.now().time() < start_time:
                now_str = datetime.now().strftime('%H:%M:%S')
                print(f"   ... 장 시작 대기 중 (현재: {now_str}, 목표: 09:00:00)", end="\r")
                time.sleep(1)  # 1초마다 확인
            
            send_discord_alert(f"☀️ **장 시작! 매매 로직을 가동합니다.**\n오늘의 계좌: {main_config_obj.account_no}")
            print(f"\n☀️  장 시작! (09:00:00) - {datetime.now().strftime('%Y-%m-%d')}")

            # ======================================================
            # 2-1. (순서 2) 9시 작업 병렬 실행 (토큰 발급, 구독)
            # ======================================================
            print("\n" + "-"*30 + " 2-1. 토큰 발급 및 구독 (병렬) " + "-"*30)
            
            # 병렬 실행할 작업 정의
            token_thread = threading.Thread(target=main_config_obj.issue_token, name="TokenIssuer")
            basket_sub_thread = threading.Thread(target=main_basket_ws_obj.subscribe, name="BasketSubscriber")
            mon_sub_thread = threading.Thread(target=main_monitoring_ws_obj.subscribe, name="MonitorSubscriber")
            
            # 작업 시작
            token_thread.start()
            basket_sub_thread.start()
            mon_sub_thread.start()
            
            # 모든 작업이 완료될 때까지 대기 (순서 2 -> 3 보장)
            token_thread.join()
            basket_sub_thread.join()
            mon_sub_thread.join()
            
            # 토큰 발급 실패 시, 매매 로직을 실행할 수 없으므로 다음 거래일까지 대기
            if not main_config_obj.access_token:
                print("\n❌ 토큰 발급에 실패했습니다. 오늘은 매매를 실행할 수 없습니다.")
                print("   (순서 8) 다음 거래일까지 대기를 시작합니다.")
                # (순서 8)로 바로 넘어감
            else:
                print("\n✅ 토큰 발급 및 웹소켓 구독이 완료되었습니다.")

                # ======================================================
                # 3. & 4. (순서 3, 4) 매매 로직 실행
                # ======================================================
                print("\n" + "-"*30 + " 3. 매매 로직 실행 " + "-"*30)
                print("   📊 diff 모니터링: 1초마다")
                print("   🔄 바스켓 최적화: 5초마다")
                print("   ⚡ 매매 실행: 조건 충족 시 즉시")
                print("-"*80 + "\n")

                # ✅ 전역 변수 초기화 (매일 장 시작 시)
                basket_optimization_counter = 0
                cached_basket_quantities = None

                # ✅ 추가: 장 시작 시 포지션 확인 (1회만)
                print("\n" + "-"*30 + " 2-2. 초기 포지션 확인 " + "-"*30)

                # [수정] get_current_position 호출 방식 변경
                current_position_type = get_current_position(
                    main_config_obj.access_token, 
                    main_config_obj.base_url, 
                    main_config_obj.app_key, 
                    main_config_obj.app_secret, 
                    main_config_obj.account_no, 
                    main_config_obj.is_real
                )

                print("\n" + "-"*30 + " 3. 매매 로직 실행 " + "-"*30)
                print("   📊 diff 모니터링: 1초마다")
                print("   🔄 바스켓 최적화: 5초마다")
                print("   ⚡ 매매 실행: 조건 충족 시 즉시")
                print("-"*80 + "\n")

                # ✅ 메인 루프: 1초마다 run_trading_logic 호출
                while datetime.now().time() <= end_time:
                    loop_start_time = time.monotonic()

                    # ==================================================
                    # 🚨 [추가] 웹소켓 연결 상태 확인 및 재연결 로직
                    # ==================================================
                    # 1. 바스켓 웹소켓 끊김 확인
                    if not main_basket_ws_obj.is_connected:
                        print(f"\n⚠️ [경고] 바스켓 웹소켓 연결 끊김 감지!")
                        main_basket_ws_obj.reconnect()
                        
                    # 2. 모니터링 웹소켓 끊김 확인
                    if not main_monitoring_ws_obj.is_connected:
                        print(f"\n⚠️ [경고] 모니터링 웹소켓 연결 끊김 감지!")
                        main_monitoring_ws_obj.reconnect()
                    

                    # (순서 3) 매매 로직 함수 호출 (1초마다)
                    # 연결이 끊겨있으면 데이터가 갱신되지 않으므로(None), 
                    # run_trading_logic 내부에서 "데이터 수신 대기 중"으로 처리됨
                    current_position_type = run_trading_logic(
                        main_config_obj, 
                        main_basket_ws_obj, 
                        main_monitoring_ws_obj,
                        current_position_type# ✅ 현재 포지션 전달
                    )
                    
                    # 1초 간격 유지
                    elapsed = time.monotonic() - loop_start_time
                    wait_time = max(0, 1.0 - elapsed)
                    
                    # (순서 4) 종료 시간 체크
                    if datetime.now().time() > end_time:
                        break
                    
                    time.sleep(wait_time)

                # ======================================================
                # 4. 장 마감
                # ======================================================
                send_discord_alert("🌙 **장 마감.** 금일 매매를 종료하고 리소스를 정리합니다.")
                print(f"\n🌙 장 마감 (15:15:00). 매매 로직을 종료합니다.")
                
                # ======================================================
                # 5. (순서 5) 전량 매도
                # ======================================================
                send_discord_alert(f"💾 거래 내역 저장 완료: trade_history_{datetime.now().strftime('%Y%m%d_%H%M')}.csv")
                print("\n" + "-"*30 + " 5. 전량 매도 " + "-"*30)
                
                # 전량 매도용 tr_id 설정 (trading_function.py 참조)
                sell_tr_id = "TTTC0801U" if main_config_obj.is_real else "VTTC0801U"
                
                clear_all_stocks(
                    access_token=main_config_obj.access_token,
                    base_url=main_config_obj.base_url,
                    app_key=main_config_obj.app_key,
                    app_secret=main_config_obj.app_secret,
                    account_no=main_config_obj.account_no,
                    tr_id=sell_tr_id
                )

                # ======================================================
                # 6. (순서 6) CSV 저장
                # ======================================================
                print("\n" + "-"*30 + " 6. CSV 저장 " + "-"*30)
                save_df_to_csv(filename=f"trade_history_{datetime.now().strftime('%Y%m%d_%H%M')}.csv")

                # ======================================================
                # 7. (순서 7) 웹소켓 구독 해제 및 토큰 반납
                # ======================================================
                print("\n" + "-"*30 + "7-1 웹소켓 구독 해제 " + "-"*30)
                
                if main_basket_ws_obj and main_basket_ws_obj.is_connected:
                    print("   ... 바스켓 웹소켓 구독 해제 중 ...")
                    main_basket_ws_obj.unsubscribe()
                
                if main_monitoring_ws_obj and main_monitoring_ws_obj.is_connected:
                    print("   ... 모니터링 웹소켓 구독 해제 중 ...")
                    main_monitoring_ws_obj.unsubscribe()
                
                print("   ... 구독 해제 완료. (연결은 유지)")
                time.sleep(1)  # 해제 메시지 전송 대기

                print("\n" + "-"*30 + " 7-2. 토큰 반납 " + "-"*30)
                main_config_obj.revoke_token()
                
            
            # ======================================================
            # (순서 8) 다음 장 대기
            # ======================================================
            print("\n" + "-"*30 + " 8. 다음 거래일 대기 " + "-"*30)
            print(f"   웹소켓 연결은 유지합니다.")
            
            # 다음 날 9시 계산 (주말/공휴일 미고려, 단순 24시간 후 기준)
            now = datetime.now()
            # 다음 날 9시 0분 0초
            next_market_open = (now + timedelta(days=1)).replace(
                hour=start_time.hour, 
                minute=start_time.minute, 
                second=start_time.second, 
                microsecond=0
            )
            
            print(f"   다음 매매 시작 시간: {next_market_open.strftime('%Y-%m-%d %H:%M:%S')}")
            
            while datetime.now() < next_market_open:
                wait_seconds = (next_market_open - datetime.now()).total_seconds()
                
                # [수정] 시간, 분, '초'까지 계산
                wait_hours = int(wait_seconds // 3600)
                wait_minutes = int((wait_seconds % 3600) // 60)
                wait_sec_display = int(wait_seconds % 60)
                
                # [수정] print 문에 초를 추가하고, 줄이 깨지지 않도록 뒤에 공백 추가
                print(f"   ... 다음 거래 시작까지 약 {wait_hours}시간 {wait_minutes}분 {wait_sec_display}초 남음   ", end="\r")
                
                # [수정] 1분/1초 단위 체크 로직을 제거하고, 항상 1초마다 체크하도록 변경
                time.sleep(1)

            # [추가] 루프가 종료된 후, 다음 print가 줄바꿈되도록
            print()

        # --- `while True` 루프 종료 (실행될 일 없음, 예외 발생 시 finally로) ---

    except KeyboardInterrupt:
        print("\n\n🛑 사용자에 의해 프로그램이 중지되었습니다. (Ctrl+C)")
        print("   잠시만 기다려주세요. 리소스를 정리하고 있습니다...")

        save_df_to_csv(filename=f"trade_history_{datetime.now().strftime('%Y%m%d_%H%M')}.csv")
        print("   csv 저장완료 파일이름 :", f"trade_history_{datetime.now().strftime('%Y%m%d_%H%M')}.csv")
        
        # ✅ 추가: 즉시 구독 해제 (finally 블록 전에)
        if main_basket_ws_obj and main_basket_ws_obj.is_connected:
            main_basket_ws_obj.unsubscribe()
        
        if main_monitoring_ws_obj and main_monitoring_ws_obj.is_connected:
            main_monitoring_ws_obj.unsubscribe()
        
        time.sleep(1)  # 해제 메시지 전송 대기
        
    except Exception as e:
        msg = f"❌ 치명적인 오류 발생 (프로그램 종료): {e}"
        print(f"\n\n{msg}")
        send_discord_alert(msg) # [추가]
        traceback.print_exc()
        
    finally:
        # ==================================================================
        #  프로그램 종료 시 리소스 정리
        # ==================================================================
        print("\n" + "-"*30 + " 프로그램 종료 (리소스 정리) " + "-"*30)
        
        # ✅ 순서 1: 웹소켓 구독 해제 및 연결 종료
        if main_basket_ws_obj:
            print("   ... 바스켓 웹소켓 구독 해제 및 연결 종료")
            main_basket_ws_obj.close()  # unsubscribe + close
        
        if main_monitoring_ws_obj:
            print("   ... 모니터링 웹소켓 구독 해제 및 연결 종료")
            main_monitoring_ws_obj.close()  # unsubscribe + close
        
        # ✅ 순서 2: 토큰 반납 (웹소켓 정리 후)
        if main_config_obj and main_config_obj.access_token:
            print("   ... 미처 반납되지 않은 토큰을 반납합니다.")
            main_config_obj.revoke_token()
        
        print("   모든 리소스를 정리했습니다. 프로그램을 종료합니다.")
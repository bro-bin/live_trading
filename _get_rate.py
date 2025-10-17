import websocket
import json
import time
import threading
from typing import Dict, Optional
import yaml  # PyYAML 라이브러리 import

class KISWebSocketClient:
    def __init__(self, app_key: str, app_secret: str, is_real: bool = True):
        """
        한국투자증권 웹소켓 클라이언트
        
        Args:
            app_key: 앱 키
            app_secret: 앱 시크릿
            is_real: 실전투자(True) or 모의투자(False)
        """
        # 전달받은 인자를 클래스 속성으로 설정하도록 수정
        self.app_key = app_key
        self.app_secret = app_secret
        self.is_real = is_real
        
        # 웹소켓 URL
        if is_real:
            self.ws_url = "ws://ops.koreainvestment.com:21000"
        else:
            self.ws_url = "ws://ops.koreainvestment.com:31000"
        
        self.ws = None
        self.approval_key = None
        self.current_prices = {}
        self.is_connected = False
        
        # Kodex 삼성그룹 ETF 구성종목
        self.stocks = {
            "삼성E&A": "028050",
            "삼성SDI": "006400",
            "삼성물산": "028260",
            "삼성바이오로직스": "207940",
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
        
    def get_approval_key(self) -> str:
        """웹소켓 접속키 발급"""
        import requests
        
        # 접속키 발급 URL은 실전/모의투자 환경에 관계없이 동일
        url = "https://openapi.koreainvestment.com:9443/oauth2/Approval"
        headers = {"content-type": "application/json"}
        body = {
            "grant_type": "client_credentials",
            "appkey": self.app_key,
            "secretkey": self.app_secret
        }
        
        response = requests.post(url, headers=headers, data=json.dumps(body))
        if response.status_code == 200:
            return response.json()["approval_key"]
        else:
            raise Exception(f"접속키 발급 실패: {response.text}")
    
    def on_message(self, ws, message):
        """웹소켓 메시지 수신"""
        if message.startswith("0|"):
            # 실시간 체결 데이터
            parts = message.split("|")
            if len(parts) >= 4:
                data = parts[3]
                fields = data.split("^")
                if len(fields) >= 3:
                    stock_code = fields[0]  # 종목코드
                    current_price = int(fields[2])  # 현재가
                    
                    # 종목명 찾기 및 업데이트
                    for name, code in self.stocks.items():
                        if code == stock_code:
                            self.current_prices[name] = {
                                "price": current_price,
                                "code": stock_code
                            }
                            break
    
    def on_error(self, ws, error):
        """웹소켓 에러"""
        print(f"웹소켓 에러: {error}")
    
    def on_close(self, ws, close_status_code, close_msg):
        """웹소켓 종료"""
        self.is_connected = False
        print("웹소켓 연결이 종료되었습니다.")
    
    def on_open(self, ws):
        """웹소켓 연결"""
        self.is_connected = True
        
        # 각 종목 등록
        for stock_name, stock_code in self.stocks.items():
            subscribe_data = {
                "header": {
                    "approval_key": self.approval_key,
                    "custtype": "P",
                    "tr_type": "1",  # 등록
                    "content-type": "utf-8"
                },
                "body": {
                    "input": {
                        "tr_id": "H0STCNT0",  # 실시간 체결가
                        "tr_key": stock_code
                    }
                }
            }
            
            ws.send(json.dumps(subscribe_data))
            time.sleep(0.05)  # API 호출 간격
    
    def connect(self):
        """웹소켓 연결"""
        if self.is_connected:
            print("이미 웹소켓이 연결되어 있습니다.")
            return
        
        # 접속키 발급
        self.approval_key = self.get_approval_key()
        
        # 웹소켓 연결
        websocket.enableTrace(False)
        self.ws = websocket.WebSocketApp(
            self.ws_url,
            on_message=self.on_message,
            on_error=self.on_error,
            on_close=self.on_close,
            on_open=self.on_open
        )
        
        # 웹소켓 실행 (별도 스레드)
        wst = threading.Thread(target=self.ws.run_forever)
        wst.daemon = True
        wst.start()
        
        # 연결 대기
        timeout = 10
        start_time = time.time()
        while not self.is_connected:
            if time.time() - start_time > timeout:
                raise Exception("웹소켓 연결 타임아웃")
            time.sleep(0.1)
    
    def get_current_prices(self, wait_time: float = 3.0) -> Dict:
        """
        현재가 조회 함수
        
        Args:
            wait_time: 데이터 수신 대기 시간 (초)
            
        Returns:
            sample_price 형식의 딕셔너리
        """
        if not self.is_connected:
            raise Exception("웹소켓이 연결되어 있지 않습니다. connect()를 먼저 호출하세요.")
        
        # 데이터 수신 대기
        time.sleep(wait_time)
        
        # 결과 반환 (sample_price 형식)
        return dict(self.current_prices)
    
    def disconnect(self):
        """웹소켓 연결 종료"""
        if self.ws and self.is_connected:
            self.ws.close()


# 전역 클라이언트 인스턴스
_client: Optional[KISWebSocketClient] = None


def initialize_websocket(app_key: str, app_secret: str, is_real: bool = True):
    """
    웹소켓 초기화 및 연결
    
    Args:
        app_key: 앱 키
        app_secret: 앱 시크릿
        is_real: 실전투자(True) or 모의투자(False)
    """
    global _client
    
    if _client is None or not _client.is_connected:
        _client = KISWebSocketClient(app_key, app_secret, is_real)
        _client.connect()
        print("웹소켓 연결 완료")


def get_samsung_etf_prices(wait_time: float = 3.0) -> Dict:
    """
    Kodex 삼성그룹 ETF 구성종목 현재가 조회
    
    Args:
        wait_time: 데이터 수신 대기 시간 (초, 기본값: 3초)
        
    Returns:
        sample_price 형식의 딕셔너리
        {
            "삼성전자": {"price": 95000, "code": "005930"},
            "삼성바이오로직스": {"price": 1127000, "code": "207940"},
            ...
        }
    """
    global _client
    
    if _client is None or not _client.is_connected:
        raise Exception("웹소켓이 연결되어 있지 않습니다. initialize_websocket()을 먼저 호출하세요.")
    
    return _client.get_current_prices(wait_time)


def close_websocket():
    """웹소켓 연결 종료"""
    global _client
    
    if _client:
        _client.disconnect()
        _client = None


# 사용 예시
if __name__ == "__main__":
    # --- config.yaml 파일에서 설정값 불러오기 ---
    try:
        with open('config.yaml', encoding='UTF-8') as f:
            _cfg = yaml.load(f, Loader=yaml.FullLoader)
    except FileNotFoundError:
        print("config.yaml 파일을 찾을 수 없습니다. 파일을 생성하고 API 키를 입력해주세요.")
        exit()

    APP_KEY = _cfg['APP_KEY']
    APP_SECRET = _cfg['APP_SECRET']
    URL_BASE = _cfg['URL_BASE']
    
    # URL에 'vts'가 포함되어 있으면 모의투자, 아니면 실전투자로 판단
    IS_REAL = "vts" not in URL_BASE.lower()
    
    print(f"실행 환경: {'실전투자' if IS_REAL else '모의투자'}")
    # ---------------------------------------------

    # 1. 웹소켓 연결
    initialize_websocket(APP_KEY, APP_SECRET, IS_REAL)
    
    # 2. 현재가 조회 (여러 번 호출 가능)
    sample_price = get_samsung_etf_prices(wait_time=5.0)
    
    print("\n결과:")
    print("=" * 60)
    print(f"sample_price = {json.dumps(sample_price, ensure_ascii=False)}")
    
    # 3. 다시 조회 가능 (웹소켓은 계속 연결되어 있음)
    print("\n5초 후 다시 조회...")
    time.sleep(5)
    sample_price = get_samsung_etf_prices(wait_time=2.0)
    print(f"sample_price = {json.dumps(sample_price, ensure_ascii=False)}")
    
    # 4. 프로그램 종료 시 웹소켓 연결 종료 (선택사항)
    # close_websocket()
    
    # 웹소켓 연결을 유지하려면 프로그램이 계속 실행되어야 함
    print("\n웹소켓 연결 유지 중... (Ctrl+C로 종료)")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n프로그램 종료")
        close_websocket()
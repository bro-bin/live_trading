import websocket
import json
import time
import threading
from typing import Dict, Optional
import yaml
import pandas as pd
import requests

# ##############################################################################
# KISWebSocketClient 클래스 - 실시간 데이터 수신
# ##############################################################################

class KISWebSocketClient:
    """한국투자증권 웹소켓 클라이언트 - 백그라운드에서 지속적으로 데이터 수신"""
    def __init__(self, app_key: str, app_secret: str, is_real: bool = True):
        self.app_key = app_key
        self.app_secret = app_secret
        self.is_real = is_real
        self.ws_url = "ws://ops.koreainvestment.com:21000" if is_real else "ws://ops.koreainvestment.com:31000"
        
        self.ws = None
        self.approval_key = None
        self.current_prices = {}
        self.is_connected = False
        self.lock = threading.Lock()  # 스레드 안전성을 위한 락
        
        # Kodex 삼성그룹 ETF 구성종목
        self.stocks = {
            "삼성E&A": "028050", "삼성SDI": "006400", "삼성물산": "028260",
            "삼성생명": "032830", "삼성에스디에스": "018260",
            "삼성전기": "009150", "삼성전자": "005930", "삼성중공업": "010140",
            "삼성증권": "016360", "삼성카드": "029780", "삼성화재": "000810",
            "에스원": "012750", "제일기획": "030000", "호텔신라": "008770"
        }
        
    def get_approval_key(self) -> str:
        """웹소켓 접속키 발급"""
        url = "https://openapi.koreainvestment.com:9443/oauth2/Approval"
        headers = {"content-type": "application/json"}
        body = {"grant_type": "client_credentials", "appkey": self.app_key, "secretkey": self.app_secret}
        response = requests.post(url, headers=headers, data=json.dumps(body))
        if response.status_code == 200:
            return response.json()["approval_key"]
        else:
            raise Exception(f"접속키 발급 실패: {response.text}")
    
    def on_message(self, ws, message):
        """웹소켓 메시지 수신 - 실시간으로 가격 업데이트"""
        if message.startswith("0|"):
            parts = message.split("|")
            if len(parts) >= 4:
                data = parts[3]
                fields = data.split("^")
                if len(fields) >= 3:
                    stock_code = fields[0]
                    current_price = int(fields[2])
                    
                    with self.lock:  # 스레드 안전성 보장
                        for name, code in self.stocks.items():
                            if code == stock_code:
                                self.current_prices[name] = {
                                    "price": current_price, 
                                    "code": stock_code,
                                    "timestamp": time.time()
                                }
                                break
    
    def on_error(self, ws, error):
        print(f"웹소켓 에러: {error}")
    
    def on_close(self, ws, close_status_code, close_msg):
        self.is_connected = False
        print("웹소켓 연결이 종료되었습니다.")
    
    def on_open(self, ws):
        self.is_connected = True
        print("✅ 웹소켓 연결 성공 - 실시간 데이터 수신 시작")
        for stock_name, stock_code in self.stocks.items():
            subscribe_data = {
                "header": {"approval_key": self.approval_key, "custtype": "P", "tr_type": "1", "content-type": "utf-8"},
                "body": {"input": {"tr_id": "H0STCNT0", "tr_key": stock_code}}
            }
            ws.send(json.dumps(subscribe_data))
            time.sleep(0.05)
    
    def connect(self):
        """웹소켓 연결 시작 (백그라운드 스레드에서 계속 실행)"""
        if self.is_connected:
            print("이미 웹소켓이 연결되어 있습니다.")
            return
        
        self.approval_key = self.get_approval_key()
        websocket.enableTrace(False)
        self.ws = websocket.WebSocketApp(
            self.ws_url, 
            on_message=self.on_message, 
            on_error=self.on_error, 
            on_close=self.on_close, 
            on_open=self.on_open
        )
        
        # 데몬 스레드로 실행하여 백그라운드에서 계속 수신
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
    
    def get_current_prices(self) -> Dict:
        """현재 수신된 최신 가격 데이터 반환 (즉시 반환)"""
        with self.lock:
            return dict(self.current_prices)
    
    def disconnect(self):
        """웹소켓 연결 종료"""
        if self.ws and self.is_connected:
            self.ws.close()

# ##############################################################################
# 전역 클라이언트 인스턴스
# ##############################################################################

_client: Optional[KISWebSocketClient] = None

def initialize_websocket(app_key: str, app_secret: str, is_real: bool = True):
    """웹소켓 초기화 및 백그라운드 데이터 수신 시작"""
    global _client
    if _client is None or not _client.is_connected:
        _client = KISWebSocketClient(app_key, app_secret, is_real)
        _client.connect()
        
        # 초기 데이터 수신 대기 (모든 종목 가격 수신까지)
        print("⏳ 초기 데이터 수신 중...")
        timeout = 10
        start_time = time.time()
        while len(_client.current_prices) < 14:
            if time.time() - start_time > timeout:
                print(f"⚠️ 일부 종목만 수신됨 ({len(_client.current_prices)}/14)")
                break
            time.sleep(0.5)
        
        print(f"✅ {len(_client.current_prices)}개 종목 실시간 데이터 수신 중")

def close_websocket():
    """웹소켓 연결 종료"""
    global _client
    if _client:
        _client.disconnect()
        _client = None

# ##############################################################################
# 포트폴리오 계산 관련 함수
# ##############################################################################

def calculate_total_market_cap(live_prices: dict):
    """실시간 가격을 바탕으로 각 종목의 시가총액과 비중을 계산하는 함수"""
    ETF_COMPOSITION = {
        "삼성전자": {"quantity": 3845, "code": "005930"}, 
        "삼성물산": {"quantity": 601, "code": "028260"}, 
        "삼성화재": {"quantity": 202, "code": "000810"},
        "삼성중공업": {"quantity": 4341, "code": "010140"}, 
        "삼성생명": {"quantity": 560, "code": "032830"},
        "삼성SDI": {"quantity": 391, "code": "006400"}, 
        "삼성전기": {"quantity": 363, "code": "009150"},
        "삼성에스디에스": {"quantity": 253, "code": "018260"}, 
        "삼성증권": {"quantity": 405, "code": "016360"},
        "삼성E&A": {"quantity": 1006, "code": "028050"}, 
        "에스원": {"quantity": 160, "code": "012750"},
        "호텔신라": {"quantity": 201, "code": "008770"}, 
        "제일기획": {"quantity": 452, "code": "030000"},
        "삼성카드": {"quantity": 154, "code": "029780"}
    }
    
    data = []
    total_market_cap = 0
    
    for stock_name, comp_info in ETF_COMPOSITION.items():
        if stock_name in live_prices:
            price = live_prices[stock_name]["price"]
            quantity = comp_info["quantity"]
            market_cap = price * quantity
            total_market_cap += market_cap
            
            data.append({
                '종목명': stock_name, '종목코드': comp_info["code"],
                '가격': price, '수량': quantity, '시가총액': market_cap
            })
    
    df = pd.DataFrame(data)
    df['비중(%)'] = (df['시가총액'] / total_market_cap * 100).round(2)
    df = df[['종목명', '종목코드', '가격', '수량', '시가총액', '비중(%)']]
    
    return df, total_market_cap

def create_minimum_cost_portfolio(target_df, tolerance=1.0):
    """삼성카드를 기준으로 역산하여 최소 비용 포트폴리오를 생성
       변경: 삼성카드 수량을 반복문으로 찾지 않고 4개로 고정함."""
    # 삼성카드 정보
    samsung_card_row = target_df[target_df['종목명'] == '삼성카드'].iloc[0]
    samsung_card_weight = samsung_card_row['비중(%)']
    samsung_card_price = samsung_card_row['가격']

    # 고정 수량
    samsung_card_quantity = 4
    if samsung_card_weight == 0:
        raise ValueError("삼성카드의 비중이 0입니다. 계산 불가.")

    # 삼성카드 비용으로 전체 포트폴리오 목표 금액 역산
    samsung_card_cost = samsung_card_price * samsung_card_quantity
    total_portfolio_value = samsung_card_cost / (samsung_card_weight / 100)

    portfolio_data = []
    actual_total_cost = 0

    for _, row in target_df.iterrows():
        stock_name = row['종목명']
        target_weight = row['비중(%)']
        stock_price = row['가격']

        if stock_name == '삼성카드':
            quantity = samsung_card_quantity
        else:
            target_investment = total_portfolio_value * (target_weight / 100)
            quantity = max(1, round(target_investment / stock_price))

        cost = stock_price * quantity
        actual_total_cost += cost

        portfolio_data.append({
            '종목명': stock_name, '종목코드': row['종목코드'], '가격': stock_price,
            '수량': quantity, '투자금액': cost, '목표비중(%)': target_weight
        })

    portfolio_df = pd.DataFrame(portfolio_data)
    portfolio_df['실제비중(%)'] = (portfolio_df['투자금액'] / actual_total_cost * 100).round(2)
    portfolio_df['오차(%)'] = (portfolio_df['실제비중(%)'] - portfolio_df['목표비중(%)']).round(2)
    portfolio_df['오차절댓값'] = abs(portfolio_df['오차(%)'])

    max_error = portfolio_df['오차절댓값'].max()

    final_df = portfolio_df[['종목명', '종목코드', '가격', '수량', '투자금액', '목표비중(%)', '실제비중(%)', '오차(%)']]
    return final_df, actual_total_cost, max_error

# ##############################################################################
# 외부에서 호출할 메인 함수
# ##############################################################################

def get_optimal_basket(tolerance=1.0):
    """
    현재 수신 중인 실시간 가격으로 최적 바스켓 구성을 계산
    
    Args:
        tolerance: 허용 오차 (기본값 1.0%)
    
    Returns:
        dict: {종목명: 수량} 형태의 딕셔너리
    """
    global _client
    
    if _client is None or not _client.is_connected:
        raise Exception("웹소켓이 연결되어 있지 않습니다. initialize_websocket()을 먼저 호출하세요.")
    
    # 현재 실시간 가격 조회
    live_prices = _client.get_current_prices()
    
    if not live_prices or len(live_prices) < 14:
        raise Exception(f"일부 종목의 실시간 가격을 받지 못했습니다. ({len(live_prices)}/14)")
    
    # ETF 원본 구성 분석
    target_df, total_cap = calculate_total_market_cap(live_prices)
    
    # 최적 포트폴리오 생성
    optimal_portfolio, optimal_cost, max_error = create_minimum_cost_portfolio(target_df, tolerance)
    
    if optimal_portfolio is None:
        raise Exception("최적 포트폴리오를 찾지 못했습니다.")
    
    # 종목명: 수량 딕셔너리로 변환
    basket_dict = dict(zip(optimal_portfolio['종목명'], optimal_portfolio['수량']))
    
    return basket_dict

# ##############################################################################
# 사용 예시
# ##############################################################################

if __name__ == "__main__":
    try:
        # 1. 설정 파일 불러오기
        with open('config.yaml', encoding='UTF-8') as f:
            _cfg = yaml.load(f, Loader=yaml.FullLoader)
        
        APP_KEY = _cfg['APP_KEY']
        APP_SECRET = _cfg['APP_SECRET']
        URL_BASE = _cfg['URL_BASE']
        IS_REAL = "vts" not in URL_BASE.lower()
        
        print(f"실행 환경: {'실전투자' if IS_REAL else '모의투자'}")
        
        # 2. 웹소켓 연결 (백그라운드에서 계속 데이터 수신)
        initialize_websocket(APP_KEY, APP_SECRET, IS_REAL)
        
        print("\n📡 실시간 데이터 수신 중... (Ctrl+C로 종료)")
        print("=" * 80)
        
        # 3. 예시: 주기적으로 최적 바스켓 계산
        while True:
            try:
                print(f"\n⏰ {time.strftime('%Y-%m-%d %H:%M:%S')} - 최적 바스켓 계산")
                
                # 최적 바스켓 계산 (실시간 가격으로)
                basket = get_optimal_basket(tolerance=1.0)
                
                # 결과 출력
                print("\n🎯 최적 바스켓 구성:")
                for stock_name, quantity in basket.items():
                    print(f"   {stock_name}: {quantity}주")
                
                # 30초 대기 후 다시 계산
                print("\n⏳ 30초 후 다시 계산합니다...")
                time.sleep(30)
                
            except KeyboardInterrupt:
                print("\n\n사용자가 프로그램을 중단했습니다.")
                break
            except Exception as e:
                print(f"\n⚠️ 오류 발생: {e}")
                time.sleep(5)
    
    except Exception as e:
        print(f"오류 발생: {e}")
    finally:
        # 4. 웹소켓 연결 종료
        close_websocket()
        print("\n프로그램을 종료합니다.")
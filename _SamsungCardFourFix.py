import websocket
import json
import time
import threading
from typing import Dict, Optional
import yaml
import pandas as pd
import math
import requests

# ##############################################################################
# KISWebSocketClient 클래스 및 관련 함수 (기존과 동일)
# ##############################################################################

class KISWebSocketClient:
    """한국투자증권 웹소켓 클라이언트"""
    def __init__(self, app_key: str, app_secret: str, is_real: bool = True):
        self.app_key = app_key
        self.app_secret = app_secret
        self.is_real = is_real
        self.ws_url = "ws://ops.koreainvestment.com:21000" if is_real else "ws://ops.koreainvestment.com:31000"
        
        self.ws = None
        self.approval_key = None
        self.current_prices = {}
        self.is_connected = False
        
        # Kodex 삼성그룹 ETF 구성종목
        self.stocks = {
            "삼성E&A": "028050", "삼성SDI": "006400", "삼성물산": "028260",
            "삼성바이오로직스": "207940", "삼성생명": "032830", "삼성에스디에스": "018260",
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
        """웹소켓 메시지 수신"""
        if message.startswith("0|"):
            parts = message.split("|")
            if len(parts) >= 4:
                data = parts[3]
                fields = data.split("^")
                if len(fields) >= 3:
                    stock_code = fields[0]
                    current_price = int(fields[2])
                    for name, code in self.stocks.items():
                        if code == stock_code:
                            self.current_prices[name] = {"price": current_price, "code": stock_code}
                            break
    
    def on_error(self, ws, error):
        print(f"웹소켓 에러: {error}")
    
    def on_close(self, ws, close_status_code, close_msg):
        self.is_connected = False
        print("웹소켓 연결이 종료되었습니다.")
    
    def on_open(self, ws):
        self.is_connected = True
        for stock_name, stock_code in self.stocks.items():
            subscribe_data = {
                "header": {"approval_key": self.approval_key, "custtype": "P", "tr_type": "1", "content-type": "utf-8"},
                "body": {"input": {"tr_id": "H0STCNT0", "tr_key": stock_code}}
            }
            ws.send(json.dumps(subscribe_data))
            time.sleep(0.05)
    
    def connect(self):
        if self.is_connected:
            print("이미 웹소켓이 연결되어 있습니다.")
            return
        self.approval_key = self.get_approval_key()
        websocket.enableTrace(False)
        self.ws = websocket.WebSocketApp(self.ws_url, on_message=self.on_message, on_error=self.on_error, on_close=self.on_close, on_open=self.on_open)
        wst = threading.Thread(target=self.ws.run_forever)
        wst.daemon = True
        wst.start()
        timeout = 10
        start_time = time.time()
        while not self.is_connected:
            if time.time() - start_time > timeout:
                raise Exception("웹소켓 연결 타임아웃")
            time.sleep(0.1)
    
    def get_current_prices(self, wait_time: float = 3.0) -> Dict:
        if not self.is_connected:
            raise Exception("웹소켓이 연결되어 있지 않습니다. connect()를 먼저 호출하세요.")
        print(f"{wait_time}초 동안 실시간 데이터를 수신합니다...")
        time.sleep(wait_time)
        return dict(self.current_prices)
    
    def disconnect(self):
        if self.ws and self.is_connected:
            self.ws.close()

_client: Optional[KISWebSocketClient] = None

def initialize_websocket(app_key: str, app_secret: str, is_real: bool = True):
    global _client
    if _client is None or not _client.is_connected:
        _client = KISWebSocketClient(app_key, app_secret, is_real)
        _client.connect()
        print("✅ 웹소켓 연결 완료")

def get_samsung_etf_prices(wait_time: float = 3.0) -> Dict:
    global _client
    if _client is None or not _client.is_connected:
        raise Exception("웹소켓이 연결되어 있지 않습니다. initialize_websocket()을 먼저 호출하세요.")
    return _client.get_current_prices(wait_time)

def close_websocket():
    global _client
    if _client:
        _client.disconnect()
        _client = None

# ##############################################################################
# 포트폴리오 계산 관련 함수 (기존과 동일)
# ##############################################################################

def calculate_total_market_cap(live_prices: dict):
    """실시간 가격을 바탕으로 각 종목의 시가총액과 비중을 계산하는 함수"""
    import pandas as pd
    
    ETF_COMPOSITION = {
        "삼성전자": {"quantity": 3845, "code": "005930"}, "삼성바이오로직스": {"quantity": 119, "code": "207940"},
        "삼성물산": {"quantity": 601, "code": "028260"}, "삼성화재": {"quantity": 202, "code": "000810"},
        "삼성중공업": {"quantity": 4341, "code": "010140"}, "삼성생명": {"quantity": 560, "code": "032830"},
        "삼성SDI": {"quantity": 391, "code": "006400"}, "삼성전기": {"quantity": 363, "code": "009150"},
        "삼성에스디에스": {"quantity": 253, "code": "018260"}, "삼성증권": {"quantity": 405, "code": "016360"},
        "삼성E&A": {"quantity": 1006, "code": "028050"}, "에스원": {"quantity": 160, "code": "012750"},
        "호텔신라": {"quantity": 201, "code": "008770"}, "제일기획": {"quantity": 452, "code": "030000"},
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

def make_basket(live_prices: dict):
    """실시간 가격으로 ETF 구성 분석 결과를 출력하는 함수"""
    df, total_market_cap = calculate_total_market_cap(live_prices)
    
    print("\n=== ETF 구성 종목별 시가총액 및 비중 (실시간 가격 기준) ===")
    print(df.to_string(index=False))
    print(f"\n총 시가총액: {total_market_cap:,}원")
    
    return df, total_market_cap

# ##############################################################################
# ✨✨✨ START: 수정된 함수 ✨✨✨
# ##############################################################################
def create_minimum_cost_portfolio(target_df, tolerance=1.0):
    """
    삼성카드를 4개 기준으로 하여 최소 비용 포트폴리오를 생성 (수정된 로직)
    """
    print("\n🔍 삼성카드 4개 보유 기준으로 포트폴리오 구성")
    print("="*70)
    
    # 기준 종목인 삼성카드 정보 가져오기
    samsung_card_row = target_df[target_df['종목명'] == '삼성카드'].iloc[0]
    samsung_card_weight = samsung_card_row['비중(%)']
    samsung_card_price = samsung_card_row['가격']
    
    # 삼성카드 수량을 4개로 고정
    samsung_card_quantity = 4
    
    print(f"기준 종목: 삼성카드 (목표 비중: {samsung_card_weight:.2f}%, 현재가: {samsung_card_price:,}원)")
    print(f"고정 수량: {samsung_card_quantity}개")
    
    # 삼성카드 4개의 비용 계산
    samsung_card_cost = samsung_card_price * samsung_card_quantity
    
    # 전체 포트폴리오의 총 가치를 역산
    total_portfolio_value = samsung_card_cost / (samsung_card_weight / 100)
    
    print(f"역산된 전체 포트폴리오 가치: {total_portfolio_value:,.0f}원")
    
    portfolio_data = []
    actual_total_cost = 0
    
    # 각 종목별로 필요한 수량과 비용 계산
    for _, row in target_df.iterrows():
        stock_name = row['종목명']
        target_weight = row['비중(%)']
        stock_price = row['가격']
        
        # 삼성카드는 수량 고정, 다른 종목은 역산된 가치 기준으로 계산
        if stock_name == '삼성카드':
            quantity = samsung_card_quantity
        else:
            target_investment = total_portfolio_value * (target_weight / 100)
            # 최소 1주는 보유하도록 수량 계산
            quantity = max(1, round(target_investment / stock_price))
        
        cost = stock_price * quantity
        actual_total_cost += cost
        
        portfolio_data.append({
            '종목명': stock_name, '종목코드': row['종목코드'], '가격': stock_price,
            '수량': quantity, '투자금액': cost, '목표비중(%)': target_weight
        })
    
    # 최종 데이터프레임 생성 및 실제 비중, 오차 계산
    portfolio_df = pd.DataFrame(portfolio_data)
    portfolio_df['실제비중(%)'] = (portfolio_df['투자금액'] / actual_total_cost * 100).round(2)
    portfolio_df['오차(%)'] = (portfolio_df['실제비중(%)'] - portfolio_df['목표비중(%)']).round(2)
    
    # 허용 오차 만족 여부 확인
    max_error = abs(portfolio_df['오차(%)']).max()
    if max_error <= tolerance:
        print(f"✅ 성공! 모든 종목이 허용 오차 {tolerance:.1f}% 이내입니다. (최대 오차: {max_error:.2f}%)")
    else:
        print(f"⚠️ 경고! 일부 종목이 허용 오차 {tolerance:.1f}%를 초과했습니다. (최대 오차: {max_error:.2f}%)")

    final_df = portfolio_df[['종목명', '종목코드', '가격', '수량', '투자금액', '목표비중(%)', '실제비중(%)', '오차(%)']]
    
    return final_df, actual_total_cost
# ##############################################################################
# ✨✨✨ END: 수정된 함수 ✨✨✨
# ##############################################################################


# ##############################################################################
# 메인 실행 블록 (기존과 동일)
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
        
        # 2. 웹소켓 연결
        initialize_websocket(APP_KEY, APP_SECRET, IS_REAL)
        
        # 3. 실시간 현재가 조회 (5초간 데이터 수신)
        live_prices = get_samsung_etf_prices(wait_time=5.0)
        
        if not live_prices or len(live_prices) < 15:
             print("\n⚠️ 일부 종목의 실시간 가격을 받아오지 못했습니다. 프로그램을 다시 실행해 주세요.")
             exit()
        
        print("\n✅ 모든 종목의 실시간 가격 정보를 성공적으로 수신했습니다.")
        
        # 4. 실시간 가격으로 원본 ETF 구성 분석
        target_df, total_cap = make_basket(live_prices)
        
        # 5. 최소 비용 포트폴리오 생성 (삼성카드 4개 기준)
        optimal_portfolio, optimal_cost = create_minimum_cost_portfolio(target_df, tolerance=1.0)
        
        # 6. 최종 결과 출력
        if optimal_portfolio is not None:
            print("\n" + "="*70)
            print("🎯 포트폴리오 최종 결과 (삼성카드 4개 기준)")
            print("="*70)
            print(optimal_portfolio.to_string(index=False))
            print(f"\n💰 총 투자 필요 금액: {optimal_cost:,}원")
            print(f"📊 원본 ETF 대비 비용 절감: {total_cap - optimal_cost:,}원 ({((total_cap - optimal_cost) / total_cap * 100):.1f}%)")
            
            print(f"\n📈 포트폴리오 분석:")
            print(f"   • 구성 종목 수: {len(optimal_portfolio)}개")
            print(f"   • 최대 오차: {abs(optimal_portfolio['오차(%)']).max():.2f}%")
            print(f"   • 평균 오차: {abs(optimal_portfolio['오차(%)']).mean():.2f}%")
        else:
            print("\n❌ 포트폴리오를 구성하지 못했습니다.")

    except Exception as e:
        print(f"오류 발생: {e}")
    finally:
        # 7. 웹소켓 연결 종료
        close_websocket()
        print("\n프로그램을 종료합니다.")
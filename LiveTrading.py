import websocket
import requests
import json
import time
import threading
import yaml
import pandas as pd
from datetime import datetime
from TradingFunction import buy_etf, sell_etf, buy_basket_direct, sell_basket, all_clear
from GetBasketQty import initialize_websocket, close_websocket, get_optimal_basket
from GetBasketQty import initialize_websocket, close_websocket, get_optimal_basket

# ==============================================================================
# ========== 설정 불러오기 (Configuration) ==========
# ==============================================================================
# config.yaml에서 설정 정보 로드
with open('config.yaml', encoding='UTF-8') as f:
    _cfg = yaml.load(f, Loader=yaml.FullLoader)

APP_KEY = _cfg['APP_KEY']
APP_SECRET = _cfg['APP_SECRET']
ACCOUNT_NO = _cfg['ACCOUNT_NO']
BASE_URL = _cfg['URL_BASE']

# --- KIS Websocket Key (실시간 시세용) ---
# 실시간 시세 이용을 위해서는 별도의 웹소켓 접속키를 발급받아야 합니다.
APPROVAL_KEY = "a34f9329-c5ef-47b6-8030-30b9adb7f40c"  # 👈 본인의 웹소켓 접속키 입력

# 실전/모의 판단
IS_REAL = "vts" not in BASE_URL.lower()
WS_URL = "ws://ops.koreainvestment.com:21000" if IS_REAL else "ws://ops.koreainvestment.com:31000"

# --- 매매 대상 종목 정보 ---
STOCK_CODE = "102780"  # KODEX 삼성그룹
STOCK_NAME = "KODEX 삼성그룹"

# --- 장마감 시간 설정 ---
MARKET_CLOSE_TIME = "15:30:00"  # 장마감 시간

# ==============================================================================
# ========== 전역 변수 (Global Variables) ==========
# ==============================================================================
# 실시간 시세 데이터를 저장할 딕셔너리
realtime_data = {
    "nav": None,
    "current_price": None,
    "nav_time": None,
    "price_time": None
}

# 현재 포지션 상태 
# "none": 미보유
# "holding_etf": ETF 보유
# "holding_basket": 바스켓 보유
position = "none"

# API 접근 토큰
ACCESS_TOKEN = None

# 프로그램 종료 플래그
should_exit = False

# 거래 기록 저장
trade_history = []

# 현재 보유 중인 포지션의 매수 금액 및 상세 정보
current_position_info = {
    "type": None,  # "etf" or "basket"
    "buy_amount": 0,  # 총 매수 금액
    "buy_time": None,  # 매수 시간
    "buy_details": {}  # 매수 상세 (바스켓의 경우 종목별 정보)
}


# 최적 바스켓 구성 (백그라운드에서 계속 업데이트)
optimal_basket = {
    "data": None,  # 최적 바스켓 딕셔너리
    "last_updated": None,  # 마지막 업데이트 시간
    "lock": threading.Lock()  # 스레드 안전성을 위한 락
}

# ==============================================================================
# ========== 백그라운드 바스켓 계산 함수 ==========
# ==============================================================================
def calculate_optimal_basket_background():
    """백그라운드에서 주기적으로 최적 바스켓을 계산하는 함수"""
    global optimal_basket, should_exit
    
    print("\n🔄 백그라운드 바스켓 계산 스레드 시작")
    print("⏱️  5초마다 최적 바스켓 구성을 업데이트합니다.")
    
    while not should_exit:
        try:
            # 최적 바스켓 계산
            basket_dict = get_optimal_basket(tolerance=1.0)
            
            # 스레드 안전하게 업데이트
            with optimal_basket["lock"]:
                optimal_basket["data"] = basket_dict
                optimal_basket["last_updated"] = datetime.now()
            
            # 간단한 로그 출력
            total_qty = sum(basket_dict.values())
            print(f"[{datetime.now().strftime('%H:%M:%S')}] 🎯 바스켓 업데이트 완료 ({len(basket_dict)}개 종목, 총 {total_qty}주)")
            
        except Exception as e:
            print(f"⚠️ 바스켓 계산 오류: {e}")
        
        # 5초 대기
        time.sleep(5)

# ==============================================================================
# ========== 거래 기록 관리 함수 ==========
# ==============================================================================
def save_trade_history():
    """거래 기록을 CSV 파일로 저장"""
    if not trade_history:
        print("\n📝 저장할 거래 기록이 없습니다.")
        return
    
    # DataFrame으로 변환
    df = pd.DataFrame(trade_history)
    
    # 파일명에 날짜 포함
    filename = f"trade_history_{datetime.now().strftime('%Y%m%d')}.csv"
    df.to_csv(filename, index=False, encoding='utf-8-sig')
    
    print(f"\n✅ 거래 기록이 저장되었습니다: {filename}")
    print(f"📊 총 {len(trade_history)}건의 거래 기록")
    
    # 통계 출력
    if len(trade_history) > 0:
        avg_return = df['수익률(%)'].mean()
        total_trades = len(df)
        profitable_trades = len(df[df['수익률(%)'] > 0])
        
        print(f"\n📈 거래 통계:")
        print(f"   - 평균 수익률: {avg_return:.2f}%")
        print(f"   - 총 거래 횟수: {total_trades}회")
        print(f"   - 수익 거래: {profitable_trades}회")
        print(f"   - 손실 거래: {total_trades - profitable_trades}회")
        print(f"   - 승률: {(profitable_trades/total_trades*100):.1f}%")


def record_buy(position_type, buy_amount, details=None):
    """매수 기록"""
    global current_position_info
    
    current_position_info = {
        "type": position_type,
        "buy_amount": buy_amount,
        "buy_time": datetime.now(),
        "buy_details": details if details else {}
    }
    
    print(f"\n📝 매수 기록: {position_type.upper()} / 금액: {buy_amount:,}원")


def record_sell(sell_amount, details=None):
    """매도 기록 및 수익률 계산"""
    global current_position_info, trade_history
    
    if current_position_info["type"] is None:
        print("\n⚠️ 매수 기록이 없어 수익률을 계산할 수 없습니다.")
        return
    
    buy_amount = current_position_info["buy_amount"]
    profit = sell_amount - buy_amount
    return_rate = (profit / buy_amount) * 100
    
    # 거래 기록 추가
    trade_record = {
        "거래일시": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        "포지션": current_position_info["type"].upper(),
        "매수시간": current_position_info["buy_time"].strftime('%Y-%m-%d %H:%M:%S'),
        "매도시간": datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        "매수금액": buy_amount,
        "매도금액": sell_amount,
        "손익": profit,
        "수익률(%)": round(return_rate, 2)
    }
    
    trade_history.append(trade_record)
    
    # 콘솔 출력
    print(f"\n{'='*80}")
    print(f"💰 매도 완료 - 수익률 기록")
    print(f"{'='*80}")
    print(f"   포지션: {current_position_info['type'].upper()}")
    print(f"   매수금액: {buy_amount:,}원")
    print(f"   매도금액: {sell_amount:,}원")
    print(f"   손익: {profit:+,}원")
    print(f"   수익률: {return_rate:+.2f}%")
    print(f"{'='*80}")
    
    # 현재 포지션 정보 초기화
    current_position_info = {
        "type": None,
        "buy_amount": 0,
        "buy_time": None,
        "buy_details": {}
    }


def calculate_basket_amount(result_dict):
    """바스켓 매매 결과에서 총 금액 계산"""
    if not result_dict or "success" not in result_dict:
        return 0
    
    # GetBasketQty에서 실시간 가격 가져오기
    from GetBasketQty import _client
    
    if _client is None:
        print("⚠️ 실시간 가격 정보를 가져올 수 없습니다.")
        return 0
    
    live_prices = _client.get_current_prices()
    total_amount = 0
    
    for item in result_dict["success"]:
        stock_name = item["stock_name"]
        quantity = item["quantity"]
        
        if stock_name in live_prices:
            price = live_prices[stock_name]["price"]
            total_amount += price * quantity
        else:
            print(f"⚠️ {stock_name}의 실시간 가격을 찾을 수 없습니다.")
    
    return total_amount


def calculate_etf_amount(quantity):
    """ETF 매매 금액 계산"""
    price = realtime_data.get("current_price")
    if price is None:
        print("⚠️ ETF 현재가 정보를 가져올 수 없습니다.")
        return 0
    
    return price * quantity


# ==============================================================================
# ========== 1. 한국투자증권 REST API (매매 및 조회) ==========
# ==============================================================================
def get_access_token():
    """OAuth 인증을 통해 접근 토큰을 발급받습니다."""
    global ACCESS_TOKEN
    url = f"{BASE_URL}/oauth2/tokenP"
    headers = {"content-type": "application/json"}
    data = {
        "grant_type": "client_credentials",
        "appkey": APP_KEY,
        "appsecret": APP_SECRET
    }
    response = requests.post(url, headers=headers, data=json.dumps(data))
    if response.status_code == 200:
        ACCESS_TOKEN = response.json()["access_token"]
        print("✅ 접근 토큰 발급 성공")
        return True
    else:
        print(f"❌ 접근 토큰 발급 실패: {response.text}")
        return False


def get_initial_balance():
    """스크립트 시작 시 보유 잔고를 확인하여 포지션 상태를 설정합니다."""
    global position
    print("--- 초기 보유 잔고 확인 중... ---")
    path = "/uapi/domestic-stock/v1/trading/inquire-balance"
    url = f"{BASE_URL}{path}"
    
    cano, acnt_prdt_cd = ACCOUNT_NO.split('-')
    
    # TR_ID 설정 (모의투자/실전투자)
    tr_id = "VTTC8434R" if not IS_REAL else "TTTC8434R"

    headers = {
        "content-type": "application/json",
        "authorization": f"Bearer {ACCESS_TOKEN}",
        "appkey": APP_KEY,
        "appsecret": APP_SECRET,
        "tr_id": tr_id,
    }
    params = {
        "CANO": cano,
        "ACNT_PRDT_CD": acnt_prdt_cd,
        "AFHR_FLPR_YN": "N",
        "OFL_YN": "",
        "INQR_DVSN": "02",
        "UNPR_DVSN": "01",
        "FUND_STTL_ICLD_YN": "N",
        "FNCG_AMT_AUTO_RDPT_YN": "N",
        "PRCS_DVSN": "01",
        "CTX_AREA_FK100": "",
        "CTX_AREA_NK100": ""
    }
    response = requests.get(url, headers=headers, params=params)
    
    if response.status_code == 200:
        data = response.json()
        if data["rt_cd"] == "0":
            stocks = data["output1"]
            has_etf = False
            has_basket = False
            
            # ETF 보유 확인
            for stock in stocks:
                if stock["pdno"] == STOCK_CODE:
                    quantity = int(stock["hldg_qty"])
                    if quantity > 0:
                        has_etf = True
                        print(f"✅ 초기 잔고 확인: {STOCK_NAME} {quantity}주 보유 중.")
                        break
            
            # 바스켓 종목 보유 확인
            SAMSUNG_GROUP_CODES = ["028050", "006400", "028260", "032830", 
                                   "018260", "009150", "005930", "010140", "016360", 
                                   "029780", "000810", "012750", "030000", "008770"]
            
            for stock in stocks:
                if stock["pdno"] in SAMSUNG_GROUP_CODES:
                    quantity = int(stock["hldg_qty"])
                    if quantity > 0:
                        has_basket = True
                        break
            
            # 포지션 상태 설정
            if has_etf:
                position = "holding_etf"
                print("📊 초기 포지션: holding_etf")
            elif has_basket:
                position = "holding_basket"
                print("📊 초기 포지션: holding_basket")
            else:
                position = "none"
                print("📊 초기 포지션: none (미보유)")
        else:
            print(f"❌ 잔고 조회 실패: {data['msg1']}")
    else:
        print(f"❌ 잔고 조회 API 호출 실패: {response.text}")


# ==============================================================================
# ========== 2. 한국투자증권 Websocket (실시간 시세) ==========
# ==============================================================================
def on_message(ws, message):
    """웹소켓 메시지 수신 시 호출되는 함수"""
    global realtime_data
    try:
        if message == "PINGPONG":
            ws.pong(message)
            return

        if message.startswith('0|') or message.startswith('1|'):
            parts = message.split('|')
            tr_id = parts[1]
            data_str = parts[3]

            if tr_id == "H0STNAV0":  # 실시간 ETF NAV
                fields = data_str.split('^')
                if len(fields) > 1:
                    realtime_data["nav"] = float(fields[1])
                    realtime_data["nav_time"] = datetime.now().strftime("%H:%M:%S")

            elif tr_id == "H0STCNT0":  # 실시간 주식 체결가
                fields = data_str.split('^')
                if len(fields) > 2:
                    realtime_data["current_price"] = int(fields[2])
                    realtime_data["price_time"] = datetime.now().strftime("%H:%M:%S")

        elif message.startswith('{'):
            msg_json = json.loads(message)
            if msg_json.get('header', {}).get('tr_id'):
                print(f"[응답] {msg_json['header']['tr_id']} - {msg_json['msg1']}")

    except Exception as e:
        print(f"메시지 처리 오류: {e} | 원본 메시지: {message}")


def on_error(ws, error):
    print(f"[오류] {error}")


def on_close(ws, close_status_code, close_msg):
    print("[웹소켓 연결 종료]")


def on_open(ws):
    """웹소켓 연결 성공 시, 실시간 데이터 구독 요청"""
    print("[웹소켓 연결 성공] 실시간 시세 구독을 요청합니다.")
    # NAV 구독 요청
    nav_subscribe = {
        "header": {"approval_key": APPROVAL_KEY, "custtype": "P", "tr_type": "1", "content-type": "utf-8"},
        "body": {"input": {"tr_id": "H0STNAV0", "tr_key": STOCK_CODE}}
    }
    # 현재가 구독 요청
    price_subscribe = {
        "header": {"approval_key": APPROVAL_KEY, "custtype": "P", "tr_type": "1", "content-type": "utf-8"},
        "body": {"input": {"tr_id": "H0STCNT0", "tr_key": STOCK_CODE}}
    }
    ws.send(json.dumps(nav_subscribe))
    time.sleep(0.5)
    ws.send(json.dumps(price_subscribe))


# ==============================================================================
# ========== 3. 매매 로직 실행 (Trading Logic) ==========
# ==============================================================================
def run_trading_logic():
    """1초마다 NAV와 현재가를 비교하여 매매 조건을 확인하고 실행하는 함수"""
    global position, should_exit
    
    # TR_ID 설정 (모의투자/실전투자)
    buy_tr_id = "VTTC0802U" if not IS_REAL else "TTTC0802U"
    sell_tr_id = "VTTC0801U" if not IS_REAL else "TTTC0801U"
    
    while not should_exit:
        time.sleep(1)  # 1초 대기
        
        # 현재 시간 확인
        now = datetime.now()
        current_time_str = now.strftime('%H:%M:%S')
        
        # 장마감 시간(15:30:00) 체크
        if current_time_str >= MARKET_CLOSE_TIME:
            print("\n" + "=" * 80)
            print(f"⏰ 장마감 시간({MARKET_CLOSE_TIME})이 되었습니다.")
            print("🧹 전체 포지션 청산을 시작합니다...")
            print("=" * 80)
            
            # 전체 청산 실행
            result = all_clear(
                access_token=ACCESS_TOKEN,
                base_url=BASE_URL,
                app_key=APP_KEY,
                app_secret=APP_SECRET,
                account_no=ACCOUNT_NO,
                tr_id=sell_tr_id,
                delay=0.5
            )
            
            if result:
                print(f"\n✅ 장마감 청산 완료")
                print(f"📊 청산 결과: 성공 {len(result.get('success', []))}건 / 실패 {len(result.get('failed', []))}건")
                
                # 청산 시 수익률 기록 (포지션이 있었다면)
                if current_position_info["type"] is not None:
                    # 청산 금액 계산
                    sell_amount = 0
                    for item in result.get('success', []):
                        # 실시간 가격으로 계산 (근사치)
                        if item['stock_code'] == STOCK_CODE:
                            # ETF
                            sell_amount = calculate_etf_amount(item['quantity'])
                        else:
                            # 바스켓 종목들
                            from GetBasketQty import _client
                            if _client:
                                live_prices = _client.get_current_prices()
                                if item['stock_name'] in live_prices:
                                    price = live_prices[item['stock_name']]["price"]
                                    sell_amount += price * item['quantity']
                    
                    if sell_amount > 0:
                        record_sell(sell_amount)
            else:
                print("\n⚠️ 장마감 청산 중 오류 발생")
            
            # 거래 기록 저장
            save_trade_history()
            
            # 프로그램 종료 플래그 설정
            should_exit = True
            print("\n👋 프로그램을 종료합니다.")
            break
        
        nav = realtime_data.get("nav")
        price = realtime_data.get("current_price")
        
        # 현재 상태 출력
        print(f"\n[{current_time_str}] 현재 포지션: {position.upper()}")
        print(f"  - NAV      : {nav if nav is not None else '수신 대기 중...'}")
        print(f"  - 현재가   : {price if price is not None else '수신 대기 중...'}")
        
        # NAV와 현재가 데이터가 모두 수신된 경우에만 로직 실행
        if nav is not None and price is not None:
            # diff = price - nav로 수정
            diff = price - nav
            print(f"  - 괴리     : {diff:+.2f} 원 (현재가 - NAV)")

            # --- 매수 조건 1: ETF 미보유 시 바스켓 매수 ---
            if diff >= 2 and position == "none":
                print("  >> 바스켓 매수 신호 발생 (현재가 - NAV >= 2)")
                
                # 백그라운드에서 계산된 최적 바스켓 가져오기
                with optimal_basket["lock"]:
                    basket_dict = optimal_basket["data"]
                    last_updated = optimal_basket["last_updated"]
                
                if basket_dict is None:
                    print("⚠️ 최적 바스켓이 아직 계산되지 않았습니다. 대기 중...")
                else:
                    print(f"✅ 최신 바스켓 사용 (업데이트: {last_updated.strftime('%H:%M:%S')})")
                    result = buy_basket_direct(
                        access_token=ACCESS_TOKEN,
                        base_url=BASE_URL,
                        app_key=APP_KEY,
                        app_secret=APP_SECRET,
                        account_no=ACCOUNT_NO,
                        basket_dict=basket_dict,
                        tr_id=buy_tr_id,
                        delay=0.5
                    )
                    if result and len(result.get("success", [])) > 0:
                        position = "holding_basket"
                        print("✅ 포지션 변경: none -> holding_basket")
                        
                        # 매수 금액 계산 및 기록
                        buy_amount = calculate_basket_amount(result)
                        record_buy("basket", buy_amount, result.get("success"))

            # --- 매도 조건 1: 바스켓 보유 시 매도 ---
            elif diff <= 0 and position == "holding_basket":
                print("  >> 바스켓 매도 신호 발생 (현재가 - NAV <= 0)")
                result = sell_basket(
                    access_token=ACCESS_TOKEN,
                    base_url=BASE_URL,
                    app_key=APP_KEY,
                    app_secret=APP_SECRET,
                    account_no=ACCOUNT_NO,
                    tr_id=sell_tr_id,
                    delay=0.5
                )
                if result and len(result.get("success", [])) > 0:
                    position = "none"
                    print("✅ 포지션 변경: holding_basket -> none")
                    
                    # 매도 금액 계산 및 수익률 기록
                    sell_amount = calculate_basket_amount(result)
                    record_sell(sell_amount, result.get("success"))

            # --- 매수 조건 2: 바스켓 미보유 시 ETF 매수 ---
            elif diff <= -2 and position == "none":
                print("  >> ETF 매수 신호 발생 (현재가 - NAV <= -2)")
                etf_quantity = 100
                result = buy_etf(
                    access_token=ACCESS_TOKEN,
                    base_url=BASE_URL,
                    app_key=APP_KEY,
                    app_secret=APP_SECRET,
                    account_no=ACCOUNT_NO,
                    stock_code=STOCK_CODE,
                    quantity=etf_quantity,
                    stock_name=STOCK_NAME,
                    tr_id=buy_tr_id
                )
                if result and result.get("rt_cd") == "0":
                    position = "holding_etf"
                    print("✅ 포지션 변경: none -> holding_etf")
                    
                    # 매수 금액 계산 및 기록
                    buy_amount = calculate_etf_amount(etf_quantity)
                    record_buy("etf", buy_amount)

            # --- 매도 조건 2: ETF 보유 시 매도 ---
            elif diff >= 0 and position == "holding_etf":
                print("  >> ETF 매도 신호 발생 (현재가 - NAV >= 0)")
                etf_quantity = 100
                result = sell_etf(
                    access_token=ACCESS_TOKEN,
                    base_url=BASE_URL,
                    app_key=APP_KEY,
                    app_secret=APP_SECRET,
                    account_no=ACCOUNT_NO,
                    stock_code=STOCK_CODE,
                    quantity=etf_quantity,
                    stock_name=STOCK_NAME,
                    tr_id=sell_tr_id
                )
                if result and result.get("rt_cd") == "0":
                    position = "none"
                    print("✅ 포지션 변경: holding_etf -> none")
                    
                    # 매도 금액 계산 및 수익률 기록
                    sell_amount = calculate_etf_amount(etf_quantity)
                    record_sell(sell_amount)


# ==============================================================================
# ========== 4. 메인 프로그램 실행 (Main Execution) ==========
# ==============================================================================
if __name__ == "__main__":
    print("=" * 60)
    print("=== 자동 ETF 괴리율 매매 프로그램을 시작합니다 ===")
    print(f"=== 대상 종목: {STOCK_NAME} ({STOCK_CODE}) ===")
    print(f"=== 실행 환경: {'실전투자' if IS_REAL else '모의투자'} ===")
    print(f"=== 장마감 청산 시간: {MARKET_CLOSE_TIME} ===")
    print("=" * 60)
    
    # 1. API 접근 토큰 발급
    if not get_access_token():
        exit()  # 토큰 발급 실패 시 프로그램 종료
        
    # 2. 바스켓 계산용 웹소켓 연결
    print("\n📡 바스켓 계산용 웹소켓 연결 중...")
    try:
        initialize_websocket(APP_KEY, APP_SECRET, IS_REAL)
        print("✅ 바스켓 계산용 웹소켓 연결 완료")
    except Exception as e:
        print(f"❌ 웹소켓 연결 실패: {e}")
        exit()
    
    # 3. 백그라운드 바스켓 계산 스레드 시작
    basket_thread = threading.Thread(target=calculate_optimal_basket_background, daemon=True)
    basket_thread.start()
    time.sleep(3)  # 초기 바스켓 계산 대기
    
    # 4. 초기 보유 잔고 확인 및 포지션 설정
    get_initial_balance()
    
    # 5. 매매 로직을 별도의 스레드에서 실행
    trading_thread = threading.Thread(target=run_trading_logic, daemon=True)
    trading_thread.start()
    
    # 6. 메인 스레드에서 NAV/현재가 웹소켓 실행
    print("\n📡 웹소켓 연결 시작...")
    ws = websocket.WebSocketApp(
        WS_URL,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close,
        on_open=on_open
    )
    
    # 웹소켓을 별도 스레드에서 실행
    ws_thread = threading.Thread(target=ws.run_forever, daemon=True)
    ws_thread.start()
    
    # 7. 메인 루프에서 종료 플래그 확인
    try:
        while not should_exit:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n\n⚠️ 사용자가 프로그램을 중단했습니다.")
        # 거래 기록 저장
        save_trade_history()
    finally:
        ws.close()
        print("프로그램이 종료되었습니다.")
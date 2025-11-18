import requests
import json
import time
import pandas as pd
from datetime import datetime
from utils import get_basket_qty, SAMSUNG_STOCKS
import traceback

# ==============================================================================
# ===================== part 1. 전역 변수: 거래 기록 관리 ======================
# ==============================================================================

# 거래 기록 저장
trade_history = []

# [수정] 현재 보유 포지션 정보 (basket_details 추가)
# 이 변수는 get_current_position() 또는 매수/매도 함수에 의해 갱신됩니다.
current_position = {
    "type": None,  # "etf" or "basket"
    "buy_price": 0,  # 매수 단가 (ETF)
    "buy_quantity": 0,  # 매수 수량 (ETF)
    "buy_amount": 0,  # 총 매수 금액
    "buy_time": None,  # 매수 시간
    "order_no": None,  # 주문 번호 (ETF)
    "basket_details": []  # 바스켓 상세 내역 (List[dict]
    
}

# ==============================================================================
# ====================== part 2.유틸리티 함수 (내부함수) =======================
# ==============================================================================

### 체결여부 확인 함수 
def _check_order_filled(access_token, base_url, app_key, app_secret, 
                        account_no, order_no, tr_id, max_attempts=60):
    """
    Args:
        access_token: 접근 토큰
        base_url: API 기본 URL
        app_key: 앱 키
        app_secret: 앱 시크릿
        account_no: 계좌번호 (예: "50154524-01")
        order_no: 주문번호
        tr_id: TR ID (VTTC8001R: 모의투자, TTTC8001R: 실전투자)
        max_attempts: 최대 확인 횟수 (기본 60회, 약 1분)
    
    Returns:
        bool: 체결 완료 여부
    """
    cano, acnt_prdt_cd = account_no.split('-')
    
    url = f"{base_url}/uapi/domestic-stock/v1/trading/inquire-psbl-rvsecncl"
    headers = {
        "content-type": "application/json; charset=utf-8",
        "authorization": f"Bearer {access_token}",
        "appkey": app_key,
        "appsecret": app_secret,
        "tr_id": tr_id
    }
    
    for attempt in range(max_attempts):
        try:
            params = {
                "CANO": cano,
                "ACNT_PRDT_CD": acnt_prdt_cd,
                "INQR_STRT_DT": datetime.now().strftime("%Y%m%d"),
                "INQR_END_DT": datetime.now().strftime("%Y%m%d"),
                "SLL_BUY_DVSN_CD": "00",  # 00: 전체, 01: 매도, 02: 매수
                "INQR_DVSN": "00",        # <-- ★★★ 이 줄이 오류를 해결합니다 ★★★
                "PDNO": "",               # <-- (추가) 종목번호 (전체)
                "CCLD_DVSN": "00",        # <-- (추가) 체결구분 (전체)
                "ORD_GNO_BRNO": "",       # <-- (추가) 주문그룹번호
                "ODNO": "",               # <-- (추가) 주문번호 (전체 미체결 조회를 위해 비워둠)
                "INQR_DVSN_1": "0",       # 0: 전체, 1: 현금, 2: 융자
                "INQR_DVSN_2": "0",       # 0: 전체, 1: 미체결, 2: 체결, 3: 확인, 4: 거부, 5: 정정...
                "INQR_DVSN_3": "00",
                "CTX_AREA_FK100": "",
                "CTX_AREA_NK100": ""
            }
            # 디버그: 보낸 파라미터 출력
            # print(f"DEBUG: _check_order_filled params={params}")

            response = requests.get(url, headers=headers, params=params)
            
            if response.status_code == 200:
                data = response.json()
                
                if data.get("rt_cd") == "0":
                    orders = data.get("output", [])
                    
                    # 해당 주문번호가 미체결 목록에 있는지 확인
                    order_found = False
                    for order in orders:
                        if order.get("odno") == order_no:
                            order_found = True
                            psbl_qty = int(order.get("psbl_qty", 0))  # 정정취소 가능 수량
                            
                            if psbl_qty == 0:
                                # 완전 체결
                                print(f"✅ 주문 체결 완료 (주문번호: {order_no})")
                                return True
                            else:
                                # 아직 미체결 또는 부분 체결
                                print(f"⏳ 체결 대기 중... ({attempt + 1}/{max_attempts})")
                                break
                    
                    # 미체결 목록에 없으면 체결 완료
                    if not order_found:
                        print(f"✅ 주문 체결 완료 (주문번호: {order_no})")
                        return True
                else:
                    print(f"⚠️  미체결 조회 응답 오류: {data.get('msg1')}")
                    print(f"   전체 응답: {response.text}")
            else:
                print(f"⚠️  미체결 조회 실패: {response.status_code}")
        
        except Exception as e:
            print(f"⚠️  체결 확인 중 오류: {e}")
        
        # 1초 대기 후 재시도
        time.sleep(1)
    
    print(f"⚠️  체결 확인 타임아웃 (주문번호: {order_no})")
    return False

### 체결가 조회 함수 (수정본: 내부 재시도 로직 및 상세 로그 추가)
def _get_filled_price(access_token, base_url, app_key, app_secret, 
                      account_no, order_no, tr_id, 
                      max_attempts=10, delay_sec=2.5): # <-- 추가: 5회 * 2초 = 최대 10초간 내부 재시도
    """
    주문번호로 실제 체결가를 조회하는 함수 (데이터 전파 지연을 고려한 내부 재시도 로직 추가)
    
    Args:
        access_token: 접근 토큰
        base_url: API 기본 URL
        app_key: 앱 키
        app_secret: 앱 시크릿
        account_no: 계좌번호
        order_no: 주문번호
        tr_id: TR ID (VTTC8001R: 모의투자, TTTC8001R: 실전투자)
        max_attempts: (내부) 최대 재시도 횟수
        delay_sec: (내부) 재시도 간 대기 시간 (초)
    
    Returns:
        tuple: (체결가, 체결수량) 또는 (None, None)
    """
    
    for attempt in range(max_attempts):
        try:
            # --- [로그 추가] ---
            if attempt > 0:
                print(f"   [로그] _get_filled_price 재시도 ({attempt + 1}/{max_attempts}) (주문번호: {order_no})")
            else:
                print(f"   [로그] _get_filled_price 호출 시작 (주문번호: {order_no})")
            # --- [로그 끝] ---

            cano, acnt_prdt_cd = account_no.split('-')
            
            url = f"{base_url}/uapi/domestic-stock/v1/trading/inquire-daily-ccld"
            headers = {
                "content-type": "application/json; charset=utf-8",
                "authorization": f"Bearer {access_token}",
                "appkey": app_key,
                "appsecret": app_secret,
                "tr_id": tr_id
            }
            
            params = {
                "CANO": cano,
                "ACNT_PRDT_CD": acnt_prdt_cd,
                "INQR_STRT_DT": datetime.now().strftime("%Y%m%d"),  # 오늘
                "INQR_END_DT": datetime.now().strftime("%Y%m%d"),   # 오늘
                "SLL_BUY_DVSN_CD": "00",  # 전체
                "INQR_DVSN": "00",  # 역순
                "PDNO": "",  # 전체
                "CCLD_DVSN": "01",  # 체결
                "ORD_GNO_BRNO": "",
                "ODNO": "",
                "INQR_DVSN_3": "00",
                "INQR_DVSN_1": "",
                "CTX_AREA_FK100": "",
                "CTX_AREA_NK100": ""
            }
            
            response = requests.get(url, headers=headers, params=params)
            
            if response.status_code != 200:
                print(f"   [실패] API 호출 실패 (HTTP Status: {response.status_code}) (주문번호: {order_no})")
                print(f"   [실패] 응답 내용: {response.text}")
                # HTTP 오류는 일시적일 수 있으므로 재시도
                time.sleep(delay_sec)
                continue 
            
            data = response.json()
            
            if data.get("rt_cd") != "0":
                print(f"   [실패] API 응답 오류 (rt_cd: {data.get('rt_cd')}) (주문번호: {order_no})")
                print(f"   [실패] 응답 메시지: {data.get('msg1')}")
                # API 논리 오류는 재시도해도 소용없을 수 있으나, 일단 재시도
                time.sleep(delay_sec)
                continue

            orders = data.get("output1", [])
            
            if not orders:
                # [시나리오 3B] 데이터 지연의 가장 유력한 증거
                print(f"   [지연] API 응답 성공(rt_cd:0)했으나 'output1' 데이터가 비어있음.")
                print(f"   [지연] (원인: 체결 데이터 전파 지연. {delay_sec}초 후 재시도...) (주문번호: {order_no})")
                time.sleep(delay_sec)
                continue # 재시도

            print(f"   [로그] 'output1'에 {len(orders)}건의 체결 내역 응답받음. 주문번호 {order_no} 탐색 시작...")

            order_found = False # 주문번호를 찾았는지 여부
            for idx, order in enumerate(orders):
                if order.get("odno") == order_no:
                    order_found = True
                    print(f"   [로그] {idx+1}번째에서 주문번호 일치함. (odno: {order_no})")
                    
                    filled_price = int(order.get("avg_prvs", 0))  # 평균 체결가
                    filled_qty = int(order.get("tot_ccld_qty", 0))  # 총 체결수량
                    
                    if not (filled_price > 0 and filled_qty > 0):
                        # [시나리오 4] 주문은 찾았으나 가격/수량이 0 (데이터 부분 전파)
                        print(f"   [지연] 주문은 찾았으나 체결가 또는 수량이 0입니다. (avg_prvs: {filled_price}, tot_ccld_qty: {filled_qty})")
                        print(f"   [지연] (원인: 데이터 부분 전파. {delay_sec}초 후 재시도...) (주문번호: {order_no})")
                        # for-loop를 빠져나가서 재시도
                        break 
                    
                    print(f"   [성공] 체결가/수량 확인 완료: {filled_price:,}원, {filled_qty:,}주 (주문번호: {order_no})")
                    return filled_price, filled_qty # <<<--- ★★★ 성공 시 즉시 반환 ★★★
            
            # for-loop를 다 돌았는데
            # 1. order_found == False (odno가 목록에 없음)
            # 2. order_found == True 였으나, 가격/수량이 0이라 break로 빠져나옴
            # 두 경우 모두 데이터 지연으로 간주하고 재시도
            if order_found:
                # 가격/수량이 0이라 break로 빠져나온 경우
                pass # 이미 로그 찍혔으므로 재시도
            else:
                # odno가 목록에 아예 없는 경우
                print(f"   [지연] 'output1' {len(orders)}건 중 주문번호 {order_no}를 찾지 못함. {delay_sec}초 후 재시도.")
                
            time.sleep(delay_sec)
            continue # for-loop(max_attempts) 재시도
        
        except Exception as e:
            # [시나리오 1]
            print(f"⚠️  _get_filled_price 함수 실행 중 예외(Exception) 발생: {e} (주문번호: {order_no})")
            traceback.print_exc()
            time.sleep(delay_sec)
            continue # 재시도
    
    # for-loop(max_attempts)가 모두 실패한 경우
    print(f"   [최종 실패] {max_attempts}회 내부 재시도했으나 주문번호 {order_no}의 체결가/수량 확보 실패.")
    return None, None
# ==============================================================================
# ====================== part 3. ETF 매수/매도 함수 ===========================
# ==============================================================================

### 1) 삼성그룹 ETF 매수 함수 (수정본: sell_etf와 동일한 5단계 구조 적용)
def buy_etf(access_token, base_url, app_key, app_secret, account_no, tr_id):
    """
    삼성그룹 ETF 매수 함수
    [로직 수정] sell_etf와 동일하게 단계별 로직 분리
    1. 1단계: 주문 접수 (재시도)
    2. 2단계: 체결 확인 (재시도)
    2.5단계: 포지션 '즉시' 업데이트 (type, time 등)
    3. 3단계: 체결가 조회 (재시도)
    4. 4단계: 최종 결과 출력
    5. 5단계: '포지션 상세' 업데이트 (가격, 수량)
    """
    global current_position
    
    # ------ 종목, 수량 설정 !!! --------
    stock_code = "102780" 
    stock_name = "KODEX 삼성그룹"
    quantity = 1  # 1주 (주문 수량)
    # ----------------------------------
    
    print(f"\n{'='*80}")
    print(f"🟢 ETF 매수 주문 시작 (로직: 선-주문, 후-확인, 2.5단계 포지션 업데이트)")
    print(f"   종목: {stock_name} ({stock_code})")
    print(f"   수량: {quantity}주")
    print(f"{'='*80}")
    
    try:
        # 0단계: 포지션 확인 (매수는 포지션 없어야 함)
        if current_position["type"] != "none":
            print(f"❌ 이미 보유 중인 포지션({current_position['type']})이 있습니다. 매수 주문을 진행할 수 없습니다.")
            return {"rt_cd": "-1", "msg1": "이미 포지션 보유 중", "success": False}

        cano, acnt_prdt_cd = account_no.split('-')
        
        # [신규] 단계별 목록 관리 (sell_etf와 구조 동일화)
        pending_orders = [] # 주문 접수 성공 (1단계 -> 2단계)
        failed_orders = []  # 주문 접수 실패 (1단계)
        confirmed_filled_orders = [] # 체결 확인 통과 (2단계 -> 3단계)
        success_orders = [] # 최종 가격조회 성공 (3단계 -> 5단계)
        price_fetch_failed_orders = [] # 가격조회 실패 (3단계)

        # 1단계 재시도 로직을 위한 상수
        MAX_RETRY_ATTEMPTS = 5
        RETRY_DELAY_SEC = 1
        
        # ==========================================================
        # 1단계: '매수 주문 접수' 실행
        # ==========================================================
        print(f"--- 1단계: 1개 종목 매수 주문 접수 시작 (실패 시 최대 {MAX_RETRY_ATTEMPTS}회 재시도) ---")
        
        is_order_placed = False
        attempt = 0
        last_reason = "N/A"
        order_no = None

        while not is_order_placed and attempt < MAX_RETRY_ATTEMPTS:
            attempt += 1
            print(f"   [1/1] {stock_name} ({stock_code}) {quantity}주 매수 시도... (시도 {attempt}/{MAX_RETRY_ATTEMPTS})")
            
            try:
                url = f"{base_url}/uapi/domestic-stock/v1/trading/order-cash"
                headers = {
                    "content-type": "application/json; charset=utf-8",
                    "authorization": f"Bearer {access_token}",
                    "appkey": app_key,
                    "appsecret": app_secret,
                    "tr_id": tr_id
                }
                body = {
                    "CANO": cano,
                    "ACNT_PRDT_CD": acnt_prdt_cd,
                    "PDNO": stock_code,
                    "ORD_DVSN": "01",  # 시장가
                    "ORD_QTY": str(quantity),
                    "ORD_UNPR": "0"
                }
                
                response = requests.post(url, headers=headers, data=json.dumps(body))
                
                if response.status_code == 200:
                    result = response.json()
                    if result.get("rt_cd") == "0":
                        order_no = result["output"]["ODNO"]
                        print(f"    ✅ 주문 접수 성공 (주문번호: {order_no})")
                        
                        pending_orders.append({
                            "code": stock_code,
                            "name": stock_name,
                            "quantity": quantity, # 주문 수량
                            "order_no": order_no
                        })
                        is_order_placed = True
                    else:
                        last_reason = result.get('msg1', '알 수 없는 오류')
                        print(f"    ⚠️ 주문 접수 실패 (API 오류): {last_reason}")
                else:
                    last_reason = f"API 호출 실패: {response.status_code}"
                    print(f"    ⚠️ 주문 접수 실패 (HTTP 오류): {last_reason}")
            
            except Exception as e:
                last_reason = str(e)
                print(f"    ⚠️ 주문 중 오류 (Exception): {last_reason}")
            
            time.sleep(0.3) # API 호출 제한
            
            if not is_order_placed and attempt < MAX_RETRY_ATTEMPTS:
                print(f"    ... {RETRY_DELAY_SEC}초 후 재시도 ...")
                time.sleep(RETRY_DELAY_SEC)
        
        # 1단계 최종 실패 시
        if not is_order_placed:
            print(f"    ❌ 최종 주문 접수 실패 (재시도 횟수 초과)")
            failed_orders.append({
                "code": stock_code,
                "name": stock_name,
                "reason": f"주문 접수 최종 실패: {last_reason}"
            })
            print(f"--- 1단계 완료 (성공: 0 / 실패: 1) ---\n")
            # 기존 buy_etf 반환값 형식 유지
            return {"rt_cd": "-1", "msg1": last_reason, "success": False}

        # 1단계 성공 시
        print(f"--- 1단계 완료 (성공: 1 / 실패: 0) ---\n")
        time.sleep(3) # 체결 대기

        # ==========================================================
        # 2단계: '체결 확인' 실행
        # ==========================================================
        print(f"--- 2단계: {len(pending_orders)}개 주문 체결 확인 시작 ---")
        
        check_tr_id = "VTTC8001R" if "VTT" in tr_id else "TTTC8001R"
        
        while pending_orders:
            print(f"\n   ... (현재 {len(pending_orders)}개 주문 체결 확인 필요) ...")
            
            order = pending_orders[0] # 어차피 1개
            print(f"   [확인 시도] {order['name']} ({order['order_no']}) 체결 확인 중...")
            
            try:
                is_filled = _check_order_filled(
                    access_token, base_url, app_key, app_secret,
                    account_no, order["order_no"], check_tr_id, max_attempts=60
                )
                
                if is_filled:
                    print(f"   \t✅ 체결 확인 완료. 2.5단계 포지션 업데이트로 이동.")
                    confirmed_filled_orders.append(order)
                    pending_orders.remove(order) # 성공
                else:
                    print(f"   \t⚠️ 체결 확인 타임아웃 (60초). 5초 후 재시도...")
                    time.sleep(5) # 다음 루프 전 대기
            
            except Exception as e:
                print(f"   \t❌ 체결 확인 중 오류: {e}. 5초 후 재시도...")
                time.sleep(5) # 예외 발생 시 대기

        print(f"--- 2단계 완료 (체결 확인 성공: {len(confirmed_filled_orders)}건) ---\n")

        # ==========================================================
        # 2.5단계: 포지션 '즉시' 업데이트 (기본 정보)
        # ==========================================================
        print(f"--- 2.5단계: 포지션 정보 우선 업데이트 (타입/시간) 시작 ---")
        
        buy_time = datetime.now() # 체결 확인 시점을 매수 시간으로
        
        if confirmed_filled_orders:
            order = confirmed_filled_orders[0]
            current_position["type"] = "etf"
            current_position["buy_time"] = buy_time
            current_position["order_no"] = order["order_no"]
            # (가격/수량/금액은 3단계 완료 후 5단계에서 업데이트)
            current_position["buy_price"] = 0
            current_position["buy_quantity"] = 0
            current_position["buy_amount"] = 0
            
            print(f"   ✅ 포지션 정보 즉시 업데이트 완료 (체결 확인 시점):", current_position["type"])
            print(f"      - 타입: etf, 매수시간: {buy_time.strftime('%H:%M:%S')}, 주문번호: {order['order_no']}")
        else:
            # 1단계는 성공했으나 2단계 체결 확인이 안 된 경우
            print("   ⚠️ 2단계 체결 확인된 주문이 없어 포지션 변경 없음.")
            # 기존 buy_etf 반환값 형식 유지
            return {"rt_cd": "-1", "msg1": "체결 확인 실패 (2단계)", "success": False}

        print(f"--- 2.5단계 완료 ---\n")


        # ==========================================================
        # 3단계: '체결가 조회' 실행
        # ==========================================================
        print(f"--- 3단계: {len(confirmed_filled_orders)}개 주문 체결가 조회 시작 ---")
        
        if confirmed_filled_orders:
            order = confirmed_filled_orders[0] # 어차피 1개
            stock_name = order["name"]
            order_no = order["order_no"]
            
            print(f"   [조회 시도] {stock_name} ({order_no}) 체결가 조회...")
            try:
                # _get_filled_price는 내부에 재시도 로직 포함
                filled_price, filled_qty = _get_filled_price(
                    access_token, base_url, app_key, app_secret,
                    account_no, order_no, check_tr_id
                )
                
                if filled_price and filled_qty:
                    buy_amount = filled_price * filled_qty
                    
                    success_orders.append({
                        "code": order["code"],
                        "name": stock_name,
                        "order_no": order_no,
                        "filled_qty": filled_qty,
                        "filled_price": filled_price,
                        "buy_amount": buy_amount,
                        "buy_time": buy_time # 2.5단계에서 기록한 시간
                    })
                    print(f"   \t💰 체결가 조회 완료: {filled_price:,}원 x {filled_qty}주 = {buy_amount:,}원")

                else:
                    # 2단계는 통과했으나 3단계 실패
                    reason = "체결가 조회 실패 (API가 가격/수량 반환 안함)"
                    print(f"   \t⚠️ {reason}")
                    price_fetch_failed_orders.append({**order, "reason": reason})

            except Exception as e:
                reason = f"체결가 조회 중 오류: {e}"
                print(f"   \t❌ {reason}")
                price_fetch_failed_orders.append({**order, "reason": reason})
        
        print(f"--- 3단계 완료 (최종 성공: {len(success_orders)} / 가격조회 실패: {len(price_fetch_failed_orders)}) ---\n")
        
        # ==========================================================
        # 4. 최종 결과 출력
        # ==========================================================
        
        print(f"\n{'='*80}")
        print(f"🎯 ETF 매수 최종 완료")
        print(f"{'='*80}")

        if success_orders:
            result_data = success_orders[0]
            print(f"✅ 최종 성공: 1/1개 종목")
            print(f"💰 매수 금액: {result_data['buy_amount']:,}원")
            print(f"   매수 단가: {result_data['filled_price']:,}원")
            print(f"   매수 수량: {result_data['filled_qty']}주")
            print(f"   매수 시간: {result_data['buy_time'].strftime('%Y-%m-%d %H:%M:%S')}")
        
        elif price_fetch_failed_orders: 
            # 3단계 실패 (2.5단계에서 포지션은 이미 업데이트됨)
            print(f"⚠️ 체결가 조회 실패 (3단계): 1/1개 종목")
            print(f"   - {price_fetch_failed_orders[0]['name']}: {price_fetch_failed_orders[0]['reason']}")
            print(f"   - [중요] 체결은 되었으나(2단계 성공) 가격 조회를 실패했습니다.")
            print(f"   - (참고: 포지션은 2.5단계에서 'etf' 타입으로 설정되었으나, 가격/수량 정보는 0입니다.)")
        
        # 1, 2단계 실패는 이미 함수 중간에 return 되었음
        
        print(f"{'='*80}\n")
        
        # ==========================================================
        # 5. 포지션 정보 저장 (가격/수량 갱신)
        # ==========================================================
        if success_orders:
            # 3단계 성공 시, 2.5단계에서 저장한 포지션에 가격/수량/금액 갱신
            result_data = success_orders[0]
            current_position["buy_price"] = result_data['filled_price']
            current_position["buy_quantity"] = result_data['filled_qty']
            current_position["buy_amount"] = result_data['buy_amount']
            
            print(f"--- 5단계: 📝 포지션 상세 정보(가격/수량) 갱신 완료 ---\n")
            
            # (4단계에서 못다 한) 상세 정보 마저 출력
            print(f"   매수 수량: {result_data['filled_qty']}주")
            print(f"   매수 시간: {result_data['buy_time'].strftime('%Y-%m-%d %H:%M:%S')}")
            
            # 최종 반환 (성공)
            return {
                "rt_cd": "0",
                "success": True,
                "filled_price": result_data['filled_price'],
                "filled_qty": result_data['filled_qty']
            }
        
        elif price_fetch_failed_orders:
            # 2.5단계에서 type='etf'로 설정되었으나 3단계에서 가격 조회 실패
            # [사용자 요청] 2단계(체결)는 성공했으므로 success: True 반환
            
            print(f"--- 5단계: ⚠️ 3단계 가격 조회 실패로 상세 정보 갱신 생략 (포지션은 'etf' 상태) ---\n")
            
            # 최종 반환 (부분 성공)
            return {
                "rt_cd": "0",  # 체결(2단계)은 성공했으므로 rt_cd는 "0"
                "success": True,
                "msg1": "체결가 조회 실패 (3단계)", # 실패 사유 전달
                "filled_price": 0,                # 가격/수량은 0으로 반환
                "filled_qty": 0
            }
        
        else:
             # 1, 2단계 실패는 이미 위에서 return 처리됨
             print(f"--- 5단계: ⚠️ 알 수 없는 오류로 포지션 갱신 실패 ---\n")
             return {"rt_cd": "-1", "msg1": "알 수 없는 오류 (5단계)", "success": False}

    except Exception as e:
        print(f"❌ ETF 매수 중 치명적 오류 발생: {e}")
        import traceback
        traceback.print_exc()
        return {"rt_cd": "-1", "msg1": str(e), "success": False}
    
### 2) 삼성그룹 ETF 매도 함수 (수정본: 5단계 구조 적용, 2/3단계 분리)
def sell_etf(access_token, base_url, app_key, app_secret, account_no, tr_id):
    """
    삼성그룹 ETF 매도 함수
    [로직 수정] buy_basket_direct와 동일하게 단계별 로직 분리
    1. 1단계: 주문 접수 (재시도)
    2. 2단계: 체결 확인 (재시도)
    2.5단계: 포지션 '즉시' 업데이트 (초기화)
    3. 3단계: 체결가 조회 (재시도)
    4. 4단계: 최종 결과 출력
    5. 5단계: '거래 기록' 저장
    """
    global current_position, trade_history
    
    # ------ 종목, 수량 설정 (기존 로직 유지) --------
    stock_code = "102780" 
    stock_name = "KODEX 삼성그룹"
    quantity = 1  # 1주
    # ----------------------------------
    
    print(f"\n{'='*80}")
    print(f"🔴 ETF 매도 주문 시작 (로직: 선-주문, 후-확인, 2.5단계 포지션 업데이트)")
    print(f"   종목: {stock_name} ({stock_code})")
    print(f"   수량: {quantity}주")
    print(f"{'='*80}")
    
    try:
        # 0단계: 포지션 확인
        if current_position["type"] != "etf":
            print("❌ 보유 중인 ETF 포지션이 없습니다.")
            return {"rt_cd": "-1", "msg1": "이미 포지션 보유 중", "success": False}
        
        # 매수 정보 미리 가져오기 (수익률 계산용)
        buy_amount = current_position.get("buy_amount", 0)
        buy_time = current_position.get("buy_time")

        cano, acnt_prdt_cd = account_no.split('-')
        
        # [신규] 단계별 목록 관리
        pending_orders = [] # 주문 접수 성공 목록 (1단계 -> 2단계)
        failed_orders = []  # 주문 접수 실패 목록 (1단계)
        confirmed_filled_orders = [] # 2단계 (체결 확인) 통과 목록 (2단계 -> 3단계)
        success_orders = [] # 3단계 (가격 조회)까지 최종 성공 목록
        price_fetch_failed_orders = [] # 3단계 실패 목록

        # 1단계 재시도 로직을 위한 상수
        MAX_RETRY_ATTEMPTS = 5
        RETRY_DELAY_SEC = 1
        
        # ==========================================================
        # 1단계: '매도 주문 접수' 실행
        # ==========================================================
        print(f"--- 1단계: 1개 종목 매도 주문 접수 시작 (실패 시 최대 {MAX_RETRY_ATTEMPTS}회 재시도) ---")
        
        is_order_placed = False
        attempt = 0
        last_reason = "N/A"
        order_no = None

        while not is_order_placed and attempt < MAX_RETRY_ATTEMPTS:
            attempt += 1
            print(f"   [1/1] {stock_name} ({stock_code}) {quantity}주 매도 시도... (시도 {attempt}/{MAX_RETRY_ATTEMPTS})")
            
            try:
                url = f"{base_url}/uapi/domestic-stock/v1/trading/order-cash"
                headers = {
                    "content-type": "application/json; charset=utf-8",
                    "authorization": f"Bearer {access_token}",
                    "appkey": app_key,
                    "appsecret": app_secret,
                    "tr_id": tr_id
                }
                body = {
                    "CANO": cano,
                    "ACNT_PRDT_CD": acnt_prdt_cd,
                    "PDNO": stock_code,
                    "ORD_DVSN": "01",  # 시장가
                    "ORD_QTY": str(quantity),
                    "ORD_UNPR": "0"
                }
                
                response = requests.post(url, headers=headers, data=json.dumps(body))
                
                if response.status_code == 200:
                    result = response.json()
                    if result.get("rt_cd") == "0":
                        order_no = result["output"]["ODNO"]
                        print(f"    ✅ 주문 접수 성공 (주문번호: {order_no})")
                        
                        # [구조 동일화] pending_orders 리스트에 추가
                        pending_orders.append({
                            "code": stock_code,
                            "name": stock_name,
                            "quantity": quantity,
                            "order_no": order_no,
                            "buy_amount_total": buy_amount, # [추가] 전체 매수금액
                            "buy_time": buy_time           # [추가] 매수 시간
                        })
                        is_order_placed = True
                    else:
                        last_reason = result.get('msg1', '알 수 없는 오류')
                        print(f"    ⚠️ 주문 접수 실패 (API 오류): {last_reason}")
                else:
                    last_reason = f"API 호출 실패: {response.status_code}"
                    print(f"    ⚠️ 주문 접수 실패 (HTTP 오류): {last_reason}")
            
            except Exception as e:
                last_reason = str(e)
                print(f"    ⚠️ 주문 중 오류 (Exception): {last_reason}")
            
            time.sleep(0.3) # API 호출 제한
            
            if not is_order_placed and attempt < MAX_RETRY_ATTEMPTS:
                print(f"    ... {RETRY_DELAY_SEC}초 후 재시도 ...")
                time.sleep(RETRY_DELAY_SEC)
        
        # 1단계 최종 실패 시
        if not is_order_placed:
            print(f"    ❌ 최종 주문 접수 실패 (재시도 횟수 초과)")
            failed_orders.append({
                "code": stock_code,
                "name": stock_name,
                "reason": f"주문 접수 최종 실패: {last_reason}"
            })
            print(f"--- 1단계 완료 (성공: 0 / 실패: 1) ---\n")
            return {"rt_cd": "-1", "msg1": last_reason, "success": False}

        # 1단계 성공 시
        print(f"--- 1단계 완료 (성공: 1 / 실패: 0) ---\n")
        time.sleep(3) # 체결 대기

        # ==========================================================
        # 2단계: '체결 확인' 실행
        # _check_order_filled 호출
        # ==========================================================
        print(f"--- 2단계: {len(pending_orders)}개 주문 체결 확인 시작 ---")
        
        check_tr_id = "VTTC8001R" if "VTT" in tr_id else "TTTC8001R"
        
        while pending_orders:
            print(f"\n   ... (현재 {len(pending_orders)}개 주문 체결 확인 필요) ...")
            
            order = pending_orders[0] # 어차피 1개
            print(f"   [확인 시도] {order['name']} ({order['order_no']}) 체결 확인 중...")
            
            try:
                # 1. 체결 확인
                is_filled = _check_order_filled(
                    access_token, base_url, app_key, app_secret,
                    account_no, order["order_no"], check_tr_id, max_attempts=60
                )
                
                if is_filled:
                    print(f"   \t✅ 체결 확인 완료. 2.5단계 포지션 업데이트로 이동.")
                    confirmed_filled_orders.append(order)
                    pending_orders.remove(order) # 성공
                else:
                    print(f"   \t⚠️ 체결 확인 타임아웃 (60초). 5초 후 재시도...")
                    time.sleep(5) # 다음 루프 전 대기
            
            except Exception as e:
                print(f"   \t❌ 체결 확인 중 오류: {e}. 5초 후 재시도...")
                time.sleep(5) # 예외 발생 시 대기

        print(f"--- 2단계 완료 (체결 확인 성공: {len(confirmed_filled_orders)}건) ---\n")

        # ==========================================================
        # 2.5단계: 포지션 '즉시' 업데이트 (초기화)
        # ==========================================================
        print(f"--- 2.5단계: 포지션 정보 업데이트 (초기화) 시작 ---")
        
        if confirmed_filled_orders:
            current_position["type"] = "none"
            
            print("   ✅ 포지션 정보 즉시 초기화 완료 (체결 확인 시점).", current_position["type"])
        else:
            print("   ⚠️ 2단계 체결 확인된 주문이 없어 포지션 변경 없음.")
            return {"rt_cd": "-1", "msg1": "체결 확인 실패 (2단계)", "success": False}

        print(f"--- 2.5단계 완료 ---\n")


        # ==========================================================
        # 3단계: '체결가 조회' 실행
        # _get_filled_price 호출 (2단계와 분리됨)
        # ==========================================================
        print(f"--- 3단계: {len(confirmed_filled_orders)}개 주문 체결가 조회 시작 ---")
        
        total_sell_amount = 0

        if confirmed_filled_orders:
            order = confirmed_filled_orders[0] # 어차피 1개
            stock_name = order["name"]
            order_no = order["order_no"]
            
            print(f"   [조회 시도] {stock_name} ({order_no}) 체결가 조회...")
            try:
                # 3. 체결가 조회
                filled_price, filled_qty = _get_filled_price(
                    access_token, base_url, app_key, app_secret,
                    account_no, order_no, check_tr_id
                )
                
                if filled_price and filled_qty:
                    sell_amount = filled_price * filled_qty
                    total_sell_amount = sell_amount
                    
                    # 수익률 계산 (백업된 정보 사용)
                    profit = sell_amount - order["buy_amount_total"]
                    return_rate = (profit / order["buy_amount_total"]) * 100 if order["buy_amount_total"] > 0 else 0

                    success_orders.append({
                        "code": order["code"],
                        "name": stock_name,
                        "order_no": order_no,
                        "quantity": filled_qty,
                        "sell_price": filled_price,
                        "sell_amount": sell_amount,
                        "buy_amount": order["buy_amount_total"],
                        "buy_time": order["buy_time"],
                        "profit": profit,
                        "return_rate": return_rate
                    })
                    print(f"   \t💰 체결가 조회 완료: {filled_price:,}원 x {filled_qty}주 = {sell_amount:,}원")

                else:
                    # 2단계는 통과했으나 3단계 실패
                    reason = "체결가 조회 실패 (API가 가격/수량 반환 안함)"
                    print(f"   \t⚠️ {reason}")
                    price_fetch_failed_orders.append({**order, "reason": reason})

            except Exception as e:
                reason = f"체결가 조회 중 오류: {e}"
                print(f"   \t❌ {reason}")
                price_fetch_failed_orders.append({**order, "reason": reason})
        
        print(f"--- 3단계 완료 (최종 성공: {len(success_orders)} / 가격조회 실패: {len(price_fetch_failed_orders)}) ---\n")
        
        # ==========================================================
        # 4. 최종 결과 출력
        # ==========================================================
        sell_time = datetime.now()
        
        print(f"\n{'='*80}")
        print(f"🎯 ETF 매도 최종 완료")
        print(f"{'='*80}")

        if success_orders:
            # 3단계까지 모두 성공
            result_data = success_orders[0]
            print(f"✅ 최종 성공: 1/1개 종목")
            print(f"💰 매도 금액: {result_data['sell_amount']:,}원")
            print(f"{'─'*80}")
            print(f"   매수 금액: {result_data['buy_amount']:,}원")
            print(f"   총 손익: {result_data['profit']:+,}원")
            print(f"   수익률: {result_data['return_rate']:+.2f}%")
        
        elif failed_orders: 
            # 1단계 실패
            print(f"❌ 주문 접수 실패 (1단계): 1/1개 종목")
            print(f"   - {failed_orders[0]['name']}: {failed_orders[0]['reason']}")

        elif price_fetch_failed_orders: 
            # 3단계 실패 (2.5단계에서 포지션은 이미 초기화됨)
            print(f"⚠️ 체결가 조회 실패 (3단계): 1/1개 종목")
            print(f"   - {price_fetch_failed_orders[0]['name']}: {price_fetch_failed_orders[0]['reason']}")
            print(f"   - [중요] 체결은 되었으나(2단계 성공) 가격 조회를 실패했습니다.")
            print(f"   - (참고: 포지션은 2.5단계에서 이미 초기화되었습니다.)")
        
        else:
             # 2단계 체결 확인 실패 (confirmed_filled_orders가 0건)
             print(f"❌ ETF 매도 실패 (2단계 체결 확인 실패 또는 타임아웃)")
             print(f"   - (참고: 포지션이 초기화되지 않았을 수 있습니다. 잔고 확인 필요)")

        print(f"{'='*80}\n")
        
        # ==========================================================
        # 5. 거래 기록 저장 
        # (포지션 초기화는 2.5단계로 이동됨)
        # ==========================================================
        if success_orders:
            # === [Scenario 1: Step 3 Success] ===
            result_data = success_orders[0]
            
            # 5-1. Save History
            trade_record = {
                "거래일시": sell_time.strftime('%Y-%m-%d %H:%M:%S'),
                "포지션": "ETF",
                "매수시간": result_data['buy_time'].strftime('%Y-%m-%d %H:%M:%S') if result_data['buy_time'] else "N/A",
                "매도시간": sell_time.strftime('%Y-%m-%d %H:%M:%S'),
                "매수금액": result_data['buy_amount'],
                "매도금액": result_data['sell_amount'],
                "손익": result_data['profit'],
                "수익률(%)": round(result_data['return_rate'], 2)
            }
            trade_history.append(trade_record)
            print(f"--- 5단계: 📝 거래 기록 저장 완료 ---\n")
            
            # 5-2. Return (Simple Success)
            return {
                "rt_cd": "0",
                "success": True,
                "sell_price": result_data['sell_price'],
                "sell_qty": result_data['quantity'],
                "sell_amount": result_data['sell_amount'],
                "profit": result_data['profit'],
                "return_rate": result_data['return_rate']
            }

        elif price_fetch_failed_orders:
            # === [Scenario 2: Step 3 Fail, but Step 2 Success] ===
            # [사용자 요청]
            result_data = price_fetch_failed_orders[0] # 2단계 통과 정보 (매수 시간/금액 포함)

            # 5-1. Save History (Partial)
            trade_record = {
                "거래일시": sell_time.strftime('%Y-%m-%d %H:%M:%S'),
                "포지션": "ETF",
                "매수시간": result_data['buy_time'].strftime('%Y-%m-%d %H:%M:%S') if result_data.get('buy_time') else "N/A",
                "매도시간": sell_time.strftime('%Y-%m-%d %H:%M:%S'),
                "매수금액": result_data.get('buy_amount_total', 0), # 1단계에서 저장한 매수금액
                "매도금액": 0, # 알 수 없음
                "손익": 0, # 알 수 없음
                "수익률(%)": 0.0,
                "비고": "3단계(가격조회) 실패" # [개선] 실패 기록
            }
            trade_history.append(trade_record)
            print(f"--- 5단계: 📝 (불완전) 거래 기록 저장 완료 (가격 조회 실패) ---\n")
            
            # 5-2. Return (Partial Success)
            return {
                "rt_cd": "0",  # 체결(2단계)은 성공했으므로 rt_cd는 "0"
                "success": True,
                "msg1": "체결가 조회 실패 (3단계)",
                "sell_price": 0,
                "sell_qty": 0,
                "sell_amount": 0,
                "profit": 0, 
                "return_rate": 0
            }
            
        else:
            # 1, 2단계 실패는 이미 위에서 return 처리됨
            print(f"--- 5단계: ⚠️ 알 수 없는 오류로 포지션 갱신 실패 ---\n")
            return {"rt_cd": "-1", "msg1": "알 수 없는 오류 (5단계)", "success": False}
        
    except Exception as e:
        print(f"❌ ETF 매도 중 치명적 오류 발생: {e}")
        import traceback
        traceback.print_exc()
        return {"rt_cd": "-1", "msg1": str(e), "success": False} # [수정] success 키 추가

### 3) 바스켓 매수 함수 (수정본: 주문과 체결 확인 분리)
def buy_basket_direct(access_token, base_url, app_key, app_secret, account_no,
                      tr_id, live_prices: dict):
    """
    삼성그룹 바스켓(개별 종목들) 매수 함수
    [로직 수정]
    1. 1단계: 모든 종목의 주문을 '먼저' 접수
    2. 2단계: 접수된 주문들의 체결 여부를 '나중에' 확인
    """
    global current_position
    
    print(f"\n{'='*80}")
    print(f"🟢 바스켓 매수 주문 시작 (로직: 선-주문, 후-확인)")
    print(f"{'='*80}")
    
    try:
        # 1. 바스켓 수량 가져오기
        basket_qty = get_basket_qty(live_prices)
        
        print(f"\n📋 매수 예정 종목:")
        total_requested_stocks = len(basket_qty) # [수정] 변수명 변경
        for i, (stock_code, qty) in enumerate(basket_qty.items(), 1):
            name = SAMSUNG_STOCKS.get(stock_code, "알 수 없음")
            print(f"   [{i:2d}/{total_requested_stocks}] {name:15s} ({stock_code}): {qty:3d}주")    
        print(f"{'='*80}\n")
        
        cano, acnt_prdt_cd = account_no.split('-')
        
        pending_orders = [] # 주문 접수 성공 목록
        failed_orders = []  # 주문 접수 실패 목록

        # [추가] 1단계 재시도 로직을 위한 상수
        MAX_RETRY_ATTEMPTS = 5  # 종목당 최대 주문 시도 횟수
        RETRY_DELAY_SEC = 1     # 주문 실패 시 재시도 대기 시간 (초)
        
        # ==========================================================
        # 1단계: 모든 종목에 대해 '주문 접수' 먼저 실행
        # ==========================================================
        print(f"--- 1단계: {total_requested_stocks}개 종목 주문 접수 시작 (실패 시 최대 {MAX_RETRY_ATTEMPTS}회 재시도) ---")
        for idx, (stock_code, quantity) in enumerate(basket_qty.items(), 1):
            stock_name = SAMSUNG_STOCKS.get(stock_code, "알 수 없음")
            
            is_order_placed = False # 주문 접수 성공 플래그
            attempt = 0             # 시도 횟수
            last_reason = "N/A"     # 마지막 실패 사유

            # [추가] 주문 접수 성공 또는 최대 시도 횟수에 도달할 때까지 반복
            while not is_order_placed and attempt < MAX_RETRY_ATTEMPTS:
                attempt += 1
                print(f"   [{idx}/{total_requested_stocks}] {stock_name} ({stock_code}) {quantity}주 주문 시도... (시도 {attempt}/{MAX_RETRY_ATTEMPTS})")
                
                try:
                    url = f"{base_url}/uapi/domestic-stock/v1/trading/order-cash"
                    headers = {
                        "content-type": "application/json; charset=utf-8",
                        "authorization": f"Bearer {access_token}",
                        "appkey": app_key,
                        "appsecret": app_secret,
                        "tr_id": tr_id
                    }
                    body = {
                        "CANO": cano,
                        "ACNT_PRDT_CD": acnt_prdt_cd,
                        "PDNO": stock_code,
                        "ORD_DVSN": "01", # 시장가
                        "ORD_QTY": str(quantity),
                        "ORD_UNPR": "0"
                    }
                    
                    response = requests.post(url, headers=headers, data=json.dumps(body))
                    
                    if response.status_code == 200:
                        result = response.json()
                        if result.get("rt_cd") == "0":
                            order_no = result["output"]["ODNO"]
                            print(f"    ✅ 주문 접수 성공 (주문번호: {order_no})")
                            pending_orders.append({
                                "code": stock_code,
                                "name": stock_name,
                                "quantity": quantity,
                                "order_no": order_no
                            })
                            is_order_placed = True # [추가] 성공 플래그 설정 (while 루프 탈출)
                        else:
                            last_reason = result.get('msg1', '알 수 없는 오류')
                            print(f"    ⚠️ 주문 접수 실패 (API 오류): {last_reason}")
                    else:
                        last_reason = f"API 호출 실패: {response.status_code}"
                        print(f"    ⚠️ 주문 접수 실패 (HTTP 오류): {last_reason}")
                    
                except Exception as e:
                    last_reason = str(e)
                    print(f"    ⚠️ 주문 중 오류 (Exception): {last_reason}")
                    
                time.sleep(0.3)  # API 호출 제한 고려 (초당 4건)
                    
                # [추가] 주문 실패했고, 재시도 횟수가 남았다면 대기
                if not is_order_placed and attempt < MAX_RETRY_ATTEMPTS:
                    print(f"    ... {RETRY_DELAY_SEC}초 후 재시도 ...")
                    time.sleep(RETRY_DELAY_SEC)
            
            # [추가] while 루프 종료 후, 최종적으로 주문이 실패했는지 확인
            if not is_order_placed:
                print(f"    ❌ 최종 주문 접수 실패 (재시도 횟수 초과)")
                failed_orders.append({
                    "code": stock_code,
                    "name": stock_name,
                    "reason": f"주문 접수 최종 실패: {last_reason}"
                })

        print(f"--- 1단계 완료 (성공: {len(pending_orders)} / 실패: {len(failed_orders)}) ---\n")
        
        # [추천] 주문 시스템 전파를 위해 1~2초 정도 대기
        if pending_orders:
            time.sleep(3) #3초 후부터 체결확인

        # ==========================================================
        # [신규] 2단계: 접수 성공한 주문들의 '체결 확인' 선-실행
        # ==========================================================
        print(f"--- 2단계: {len(pending_orders)}개 주문 체결 확인 시작 ---")
        
        confirmed_filled_orders = [] # 2단계 (체결 확인) 통과 목록
        check_tr_id = "VTTC8001R" if "VTT" in tr_id else "TTTC8001R"
        
        while pending_orders:
            print(f"\n   ... (현재 {len(pending_orders)}개 주문 체결 확인 필요) ...")
            
            for order in pending_orders.copy(): 
                stock_name = order["name"]
                order_no = order["order_no"]
                
                print(f"   [확인 시도] {stock_name} ({order_no}) 체결 확인 중...")
                try:
                    # 1. 체결 확인
                    is_filled = _check_order_filled(
                        access_token, base_url, app_key, app_secret,
                        account_no, order_no, check_tr_id, max_attempts=60 
                    )
                    
                    if is_filled:
                        print(f"   \t✅ 체결 확인 완료. 가격 조회 대기열로 이동.")
                        confirmed_filled_orders.append(order)
                        pending_orders.remove(order) # 성공했으므로 대기 목록에서 제거
                    else:
                        print(f"   \t⚠️ 체결 확인 타임아웃 (60초). 다음 루프에서 재시도...")
                        # (주문이 pending_orders에 남아있음)
                
                except Exception as e:
                    reason = f"체결 확인 중 오류: {e}"
                    print(f"   \t❌ {reason}. 5초 후 재시도...")
                    time.sleep(5) # 예외 발생 시 잠시 대기

            if pending_orders:
                print(f"   ... (미체결 {len(pending_orders)}건) 5초 후 재확인 시작 ...")
                time.sleep(5)

        print(f"--- 2단계 완료 (체결 확인 성공: {len(confirmed_filled_orders)}건) ---\n")

        # ==========================================================
        # [신규] 2.5단계: 포지션 '타입' 및 '체결 목록' 우선 업데이트
        # ==========================================================
        if confirmed_filled_orders:
            # 3단계(가격 조회) 전에 포지션 상태를 먼저 'basket'으로 변경
            current_position["type"] = "basket"
            current_position["buy_amount"] = 0 # 아직 금액을 알 수 없음
            current_position["buy_time"] = datetime.now()
            # basket_details에 가격/금액 정보가 빠진 채로 우선 저장
            current_position["basket_details"] = confirmed_filled_orders 
            
            print(f"\n📝 포지션 정보 우선 업데이트 (체결 확인 시점):")
            print(f"   - 포지션 타입: 바스켓")
            print(f"   - 매수 시간: {current_position['buy_time'].strftime('%H:%M:%S')}")
            print(f"   - (참고: 총 매수 금액과 상세 내역은 3단계 완료 후 갱신됨)")
        
        
        # ==========================================================
        # [신규] 3단계: 체결 완료된 주문들의 '체결가 조회' 후-실행
        # ==========================================================
        print(f"--- 3단계: {len(confirmed_filled_orders)}개 주문 체결가 조회 시작 ---")
        
        success_orders = [] # 3단계 (가격 조회)까지 최종 성공 목록
        price_fetch_failed_orders = [] # [신규] 2단계는 통과했으나 3단계(가격 조회) 실패 목록
        total_amount = 0

        for order in confirmed_filled_orders:
            stock_name = order["name"]
            order_no = order["order_no"]
            
            print(f"   [조회 시도] {stock_name} ({order_no}) 체결가 조회...")
            try:
                filled_price, filled_qty = _get_filled_price(
                    access_token, base_url, app_key, app_secret,
                    account_no, order_no, check_tr_id
                )
                
                if filled_price and filled_qty:
                    amount = filled_price * filled_qty
                    total_amount += amount
                    
                    success_orders.append({
                        "code": order["code"],
                        "name": stock_name,
                        "order_no": order_no,
                        "quantity": filled_qty,
                        "price": filled_price,
                        "amount": amount
                    })
                    print(f"   \t💰 체결가 조회 완료: {filled_price:,}원 x {filled_qty}주 = {amount:,}원")
                
                else:
                    reason = "체결가 조회 실패 (API가 가격/수량 반환 안함)"
                    print(f"   \t⚠️ {reason}")
                    price_fetch_failed_orders.append({**order, "reason": reason})

            except Exception as e:
                reason = f"체결가 조회 중 오류: {e}"
                print(f"   \t❌ {reason}")
                price_fetch_failed_orders.append({**order, "reason": reason})
            
            time.sleep(0.5) # 가격 조회도 API 호출이므로 딜레이

        print(f"--- 3단계 완료 (최종 성공: {len(success_orders)} / 가격조회 실패: {len(price_fetch_failed_orders)}) ---\n")

        # ==========================================================
        # 4. 최종 결과 출력
        # ==========================================================
        print(f"\n{'='*80}")
        print(f"🎯 바스켓 매수 최종 완료")
        print(f"{'='*80}")
        
        print(f"✅ 최종 성공: {len(success_orders)}/{total_requested_stocks}개 종목")
        print(f"❌ 주문 접수 실패 (1단계): {len(failed_orders)}/{total_requested_stocks}개 종목")
        print(f"⚠️ 체결가 조회 실패 (3단계): {len(price_fetch_failed_orders)}/{total_requested_stocks}개 종목 (체결은 되었으나 가격/수량 조회 실패)")
        print(f"💰 총 매수 금액 (최종 성공 건 기준): {total_amount:,}원")
        
        if failed_orders:
            print(f"\n⚠️ 실패한 종목 (1단계 주문 접수 실패):")
            for order in failed_orders:
                print(f"   - {order['name']} ({order.get('code', 'N/A')}): {order['reason']}")
        
        if price_fetch_failed_orders:
            print(f"\n⚠️ 실패한 종목 (3단계 체결가 조회 실패 - [중요] 체결은 되었을 수 있음!):")
            for order in price_fetch_failed_orders:
                print(f"   - {order['name']} ({order['code']}) (주문번호: {order['order_no']}): {order['reason']}")
        
        # ==========================================================
        # 5. 포지션 정보 저장 (금액 및 상세내역 갱신)
        # ==========================================================
        if success_orders:
            # [수정] 2.5단계에서 이미 'basket'으로 설정됨.
            # 'buy_amount'와 'basket_details'를 3단계 결과로 갱신
            current_position["buy_amount"] = total_amount
            current_position["basket_details"] = success_orders
            # [수정] buy_time은 2.5단계에서 설정된 시간(최초 체결 확인 시점)을 유지
            
            print(f"\n📝 포지션 정보 갱신 (가격/금액 반영):")
            print(f"   - 포지션 타입: 바스켓 (유지)")
            print(f"   - 총 매수 금액: {total_amount:,}원 (갱신)")
            print(f"   - 매수 시간: {current_position['buy_time'].strftime('%H:%M:%S')} (최초 체결 확인 시점)")
            print(f"   - 종목 수: {len(success_orders)}개")
        
        else:
             # 2.5단계에서 basket으로 설정되었으나 3단계에서 모두 실패한 경우
             if current_position["type"] == "basket":
                 print(f"\n⚠️ 3단계 가격 조회 실패로 포지션 정보가 불완전합니다.")
                 print(f"   - (포지션 타입: 'basket', 매수 금액: 0)")
        
        print(f"{'='*80}\n")
        
        return {
            "rt_cd": "0" if success_orders else "-1",
            "success": success_orders,
            "failed_step1_place_order": failed_orders, 
            "failed_step3_get_price": price_fetch_failed_orders, 
            "total_amount": total_amount
        }
        
    except Exception as e:
        print(f"❌ 바스켓 매수 중 치명적 오류 발생: {e}")
        traceback.print_exc()
        return {"rt_cd": "-1", "msg1": str(e)}

### 4) 바스켓 매도 함수 (수정본: 2.5단계 포지션 즉시 초기화 적용)
def sell_basket(access_token, base_url, app_key, app_secret, account_no, tr_id):
    """
    삼성그룹 바스켓(개별 종목들) 매도 함수
    [로직 수정] buy_basket_direct와 동일하게 단계별 로직 분리
    1. 1단계: 모든 종목의 주문을 '먼저' 접수
    2. 2단계: 접수된 주문들의 체결 여부를 '나중에' 확인
    2.5단계: 포지션 '즉시' 업데이트 (초기화)  <-- ★★★ 수정된 부분 ★★★
    3. 3단계: 체결 확인된 주문들의 '체결가'를 조회
    4. 4단계: 최종 결과 출력
    5. 5단계: '거래 기록' 저장
    """
    global current_position, trade_history
    
    print(f"\n{'='*80}")
    print(f"🔴 바스켓 매도 주문 시작 (로직: 선-주문, 후-확인, 2.5단계 포지션 업데이트)")
    print(f"{'='*80}")
    
    try:
        # 1. 매수한 바스켓 정보 확인
        if current_position["type"] != "basket":
            print("❌ 보유 중인 바스켓 포지션이 없습니다.")
            return {"rt_cd": "-1", "msg1": "바스켓 포지션 없음"}
        
        basket_details = current_position.get("basket_details", [])
        
        if not basket_details:
            print("❌ 바스켓 상세 정보가 없습니다.")
            # 포지션 타입은 basket인데 상세 내역이 없는 경우, 포지션 초기화
            current_position["type"] = "none"
            current_position["buy_amount"] = 0
            current_position["buy_time"] = None
            print("📝 포지션 정보 초기화 완료\n")
            return {"rt_cd": "-1", "msg1": "바스켓 상세 정보 없음"}
        
        buy_amount = current_position["buy_amount"]
        buy_time = current_position["buy_time"]
        
        print(f"\n📋 매도 예정 종목:")
        total_stocks = len(basket_details)
        for i, stock in enumerate(basket_details, 1):
            print(f"   [{i:2d}/{total_stocks}] {stock['name']:15s} ({stock['code']}): {stock['quantity']:3d}주")
        print(f"{'='*80}\n")
        
        cano, acnt_prdt_cd = account_no.split('-')
        pending_orders = [] # 주문 접수 성공 목록 (1단계 -> 2단계)
        failed_orders = []  # 주문 접수 실패 목록 (1단계)
        
        # 1단계 재시도 로직을 위한 상수
        MAX_RETRY_ATTEMPTS = 5
        RETRY_DELAY_SEC = 1

        # ==========================================================
        # 1단계: 모든 종목에 대해 '매도 주문 접수' 먼저 실행
        # ==========================================================
        print(f"--- 1단계: {total_stocks}개 종목 매도 주문 접수 시작 (실패 시 최대 {MAX_RETRY_ATTEMPTS}회 재시도) ---")
        
        for idx, stock_info in enumerate(basket_details, 1):
            stock_code = stock_info["code"]
            stock_name = stock_info["name"]
            quantity = stock_info["quantity"]
            buy_price = stock_info.get("price", 0) # 수익률 계산을 위해 매수가 저장
            
            is_order_placed = False
            attempt = 0
            last_reason = "N/A"
            
            while not is_order_placed and attempt < MAX_RETRY_ATTEMPTS:
                attempt += 1
                print(f"   [{idx}/{total_stocks}] {stock_name} ({stock_code}) {quantity}주 매도 시도... (시도 {attempt}/{MAX_RETRY_ATTEMPTS})")
                
                try:
                    url = f"{base_url}/uapi/domestic-stock/v1/trading/order-cash"
                    headers = {
                        "content-type": "application/json; charset=utf-8",
                        "authorization": f"Bearer {access_token}",
                        "appkey": app_key,
                        "appsecret": app_secret,
                        "tr_id": tr_id
                    }
                    body = {
                        "CANO": cano,
                        "ACNT_PRDT_CD": acnt_prdt_cd,
                        "PDNO": stock_code,
                        "ORD_DVSN": "01",  # 시장가
                        "ORD_QTY": str(quantity),
                        "ORD_UNPR": "0"
                    }
                    
                    response = requests.post(url, headers=headers, data=json.dumps(body))
                    
                    if response.status_code == 200:
                        result = response.json()
                        if result.get("rt_cd") == "0":
                            order_no = result["output"]["ODNO"]
                            print(f"    ✅ 주문 접수 성공 (주문번호: {order_no})")
                            pending_orders.append({
                                "code": stock_code,
                                "name": stock_name,
                                "quantity": quantity, # 매도 주문 수량 (매수했던 수량)
                                "buy_price": buy_price, # 매수 단가
                                "order_no": order_no
                            })
                            is_order_placed = True
                        else:
                            last_reason = result.get('msg1', '알 수 없는 오류')
                            print(f"    ⚠️ 주문 접수 실패 (API 오류): {last_reason}")
                    else:
                        last_reason = f"API 호출 실패: {response.status_code}"
                        print(f"    ⚠️ 주문 접수 실패 (HTTP 오류): {last_reason}")
                
                except Exception as e:
                    last_reason = str(e)
                    print(f"    ⚠️ 주문 중 오류 (Exception): {last_reason}")
                
                time.sleep(0.3) # API 호출 제한
                
                if not is_order_placed and attempt < MAX_RETRY_ATTEMPTS:
                    print(f"    ... {RETRY_DELAY_SEC}초 후 재시도 ...")
                    time.sleep(RETRY_DELAY_SEC)
            
            if not is_order_placed:
                print(f"    ❌ 최종 주문 접수 실패 (재시도 횟수 초과)")
                failed_orders.append({
                    "code": stock_code,
                    "name": stock_name,
                    "reason": f"주문 접수 최종 실패: {last_reason}"
                })

        print(f"--- 1단계 완료 (성공: {len(pending_orders)} / 실패: {len(failed_orders)}) ---\n")
        
        if pending_orders:
            time.sleep(3) # 3초 후부터 체결확인

        # ==========================================================
        # [신규] 2단계: 접수 성공한 주문들의 '체결 확인' 선-실행
        # ==========================================================
        print(f"--- 2단계: {len(pending_orders)}개 주문 체결 확인 시작 ---")
        
        confirmed_filled_orders = [] # 2단계 (체결 확인) 통과 목록 (2단계 -> 3단계)
        check_tr_id = "VTTC8001R" if "VTT" in tr_id else "TTTC8001R"
        
        while pending_orders:
            print(f"\n   ... (현재 {len(pending_orders)}개 주문 체결 확인 필요) ...")
            
            for order in pending_orders.copy():
                stock_name = order["name"]
                order_no = order["order_no"]
                
                print(f"   [확인 시도] {stock_name} ({order_no}) 체결 확인 중...")
                
                try:
                    # 1. 체결 확인
                    is_filled = _check_order_filled(
                        access_token, base_url, app_key, app_secret,
                        account_no, order_no, check_tr_id, max_attempts=60 
                    )
                    
                    if is_filled:
                        print(f"   \t✅ 체결 확인 완료. 2.5단계 포지션 업데이트로 이동.")
                        confirmed_filled_orders.append(order)
                        pending_orders.remove(order) # 성공했으므로 대기 목록에서 제거
                    else:
                        print(f"   \t⚠️ 체결 확인 타임아웃 (60초). 다음 루프에서 재시도...")
                        # (주문이 pending_orders에 남아있음)
                
                except Exception as e:
                    reason = f"체결 확인 중 오류: {e}"
                    print(f"   \t❌ {reason}. 5초 후 재시도...")
                    time.sleep(5) # 예외 발생 시 잠시 대기

            if pending_orders:
                print(f"   ... (미체결 {len(pending_orders)}건) 5초 후 재확인 시작 ...")
                time.sleep(5)

        print(f"--- 2단계 완료 (체결 확인 성공: {len(confirmed_filled_orders)}건) ---\n")
        
        # ==========================================================
        # [수정] 2.5단계: 포지션 '즉시' 업데이트 (초기화)
        # (buy_etf/sell_etf와 동일한 구조)
        # ==========================================================
        print(f"--- 2.5단계: 포지션 정보 업데이트 (초기화) 시작 ---")
        
        # 2단계(체결)를 통과한 주문이 하나라도 있으면,
        # 3단계(가격조회) 성공 여부와 관계없이 포지션은 즉시 초기화
        if confirmed_filled_orders:
            current_position["type"] = "none"
            current_position["buy_price"] = 0
            current_position["buy_quantity"] = 0
            current_position["buy_amount"] = 0
            current_position["buy_time"] = None
            current_position["order_no"] = None
            current_position["basket_details"] = []
            print("   ✅ 포지션 정보 즉시 초기화 완료 (체결 확인 시점).")
        else:
            # 1단계에서 주문은 성공했으나, 2단계에서 체결 확인이 하나도 안 된 경우
            print("   ⚠️ 2단계 체결 확인된 주문이 없어 포지션 변경 없음.")
            
        print(f"--- 2.5단계 완료 ---\n")


        # ==========================================================
        # [신규] 3단계: 체결 완료된 주문들의 '체결가 조회' 후-실행
        # ==========================================================
        print(f"--- 3단계: {len(confirmed_filled_orders)}개 주문 체결가 조회 시작 ---")
        
        success_orders = [] # 3단계 (가격 조회)까지 최종 성공 목록
        price_fetch_failed_orders = [] # 2단계는 통과했으나 3단계(가격 조회) 실패 목록
        total_sell_amount = 0
        
        for order in confirmed_filled_orders:
            stock_name = order["name"]
            order_no = order["order_no"]
            buy_price = order["buy_price"]
            original_quantity = order["quantity"] # 매도 주문 수량
            
            print(f"   [조회 시도] {stock_name} ({order_no}) 체결가 조회...")
            try:
                filled_price, filled_qty = _get_filled_price(
                    access_token, base_url, app_key, app_secret,
                    account_no, order_no, check_tr_id
                )
                
                if filled_price and filled_qty:
                    if filled_qty != original_quantity:
                        print(f"    ⚠️ 경고: 주문 수량({original_quantity})과 체결 수량({filled_qty})이 다름")
                    
                    sell_amount = filled_price * filled_qty
                    total_sell_amount += sell_amount
                    
                    # 개별 종목 손익
                    stock_buy_amount = buy_price * original_quantity # 매수금액 = 매수가 * 매수수량(==매도주문수량)
                    stock_profit = sell_amount - stock_buy_amount
                    stock_return = (stock_profit / stock_buy_amount) * 100 if stock_buy_amount > 0 else 0
                    
                    success_orders.append({
                        "code": order["code"],
                        "name": stock_name,
                        "order_no": order_no,
                        "quantity": filled_qty,
                        "buy_price": buy_price,
                        "sell_price": filled_price,
                        "amount": sell_amount,
                        "profit": stock_profit,
                        "return_rate": stock_return
                    })
                    
                    print(f"    💰 체결가 조회 완료: {filled_price:,}원 x {filled_qty}주 = {sell_amount:,}원")
                    print(f"    📊 종목 손익: {stock_profit:+,}원 ({stock_return:+.2f}%)")

                else:
                    reason = "체결가 조회 실패 (API가 가격/수량 반환 안함)"
                    print(f"   \t⚠️ {reason}")
                    price_fetch_failed_orders.append({**order, "reason": reason})

            except Exception as e:
                reason = f"체결가 조회 중 오류: {e}"
                print(f"   \t❌ {reason}")
                price_fetch_failed_orders.append({**order, "reason": reason})
            
            time.sleep(0.5) # 가격 조회도 API 호출이므로 딜레이

        print(f"--- 3단계 완료 (최종 성공: {len(success_orders)} / 가격조회 실패: {len(price_fetch_failed_orders)}) ---\n")

        # ==========================================================
        # 4. 최종 결과 출력
        # ==========================================================
        sell_time = datetime.now()
        total_profit = total_sell_amount - buy_amount
        total_return_rate = (total_profit / buy_amount) * 100 if buy_amount > 0 else 0
        
        print(f"\n{'='*80}")
        print(f"🎯 바스켓 매도 최종 완료")
        print(f"{'='*80}")
        
        print(f"✅ 최종 성공: {len(success_orders)}/{total_stocks}개 종목")
        print(f"❌ 주문 접수 실패 (1단계): {len(failed_orders)}/{total_stocks}개 종목")
        print(f"⚠️ 체결가 조회 실패 (3단계): {len(price_fetch_failed_orders)}/{total_stocks}개 종목")
        print(f"   - (참고: 3단계 실패 종목은 2.5단계에서 포지션이 이미 초기화되었습니다.)")
        print(f"{'─'*80}")
        print(f"💰 매수 금액: {buy_amount:,}원")
        print(f"💰 매도 금액: {total_sell_amount:,}원")
        print(f"📊 총 손익: {total_profit:+,}원")
        print(f"📈 수익률: {total_return_rate:+.2f}%")
        
        if failed_orders:
            print(f"\n⚠️  실패한 종목 (1단계 주문 접수 실패):")
            for order in failed_orders:
                print(f"   - {order['name']} ({order['code']}): {order['reason']}")
        
        if price_fetch_failed_orders:
            print(f"\n⚠️ 실패한 종목 (3단계 체결가 조회 실패 - [중요] 체결은 되었음!):")
            for order in price_fetch_failed_orders:
                print(f"   - {order['name']} ({order['code']}) (주문번호: {order['order_no']}): {order['reason']}")

        if success_orders:
            print(f"\n📋 종목별 수익률:")
            for order in success_orders:
                print(f"   {order['name']:15s}: {order['profit']:+8,}원 ({order['return_rate']:+6.2f}%)")
        
        print(f"{'='*80}\n")
        
        # ==========================================================
        # 5. 거래 기록 저장 
        # (포지션 초기화는 2.5단계로 이동됨)
        # ==========================================================
        
        # 5-1. 거래 기록 저장
        if success_orders or price_fetch_failed_orders: # 2단계(체결)를 통과한 것이 하나라도 있으면 기록
            trade_record = {
                "거래일시": sell_time.strftime('%Y-%m-%d %H:%M:%S'),
                "포지션": "바스켓",
                "매수시간": buy_time.strftime('%Y-%m-%d %H:%M:%S'),
                "매도시간": sell_time.strftime('%Y-%m-%d %H:%M:%S'),
                "매수금액": buy_amount,
                "매도금액": total_sell_amount,
                "손익": total_profit,
                "수익률(%)": round(total_return_rate, 2),
                "성공종목수": len(success_orders),
                "1단계실패종목수": len(failed_orders),
                "3단계실패종목수": len(price_fetch_failed_orders) # [추가]
            }
            
            trade_history.append(trade_record)
            print(f"--- 5단계: 📝 거래 기록 저장 완료 ---\n")
        else:
            print(f"--- 5단계: ⚠️ 3단계 최종 성공 건이 없어 거래 기록 저장 생략 ---\n")
        
        # 5-2. 포지션 초기화 (2.5단계로 이동함)
        
        return {
            "rt_cd": "0" if success_orders else "-1",
            "success": success_orders,
            "failed_step1_place_order": failed_orders,
            "failed_step3_get_price": price_fetch_failed_orders,
            "total_sell_amount": total_sell_amount,
            "total_profit": total_profit,
            "total_return_rate": total_return_rate
        }
        
    except Exception as e:
        print(f"❌ 바스켓 매도 중 치명적 오류 발생: {e}")
        import traceback
        traceback.print_exc()
        return {"rt_cd": "-1", "msg1": str(e)}

    
# ==============================================================================
# ======================== part 4. 기타 필요 함수 ==============================
# ==============================================================================

### 수익률 저장
def save_df_to_csv(filename=None, save_dir="data"):
    """
    거래 기록을 DataFrame으로 변환하여 CSV 파일로 저장
    
    Args:
        filename: 저장할 파일명 (None이면 자동 생성)
        save_dir: 저장할 디렉토리 (기본값: "data")
    
    Returns:
        str: 저장된 파일 경로 또는 None
    """
    global trade_history
    
    try:
        # 거래 기록이 없는 경우
        if not trade_history:
            print("⚠️  저장할 거래 기록이 없습니다.")
            return None
        
        # DataFrame 생성
        df = pd.DataFrame(trade_history)
        
        # 저장 디렉토리 생성 (없으면)
        import os
        if not os.path.exists(save_dir):
            os.makedirs(save_dir)
            print(f"📁 디렉토리 생성: {save_dir}")
        
        # 파일명 생성 (지정되지 않은 경우)
        if filename is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"trade_history_{timestamp}.csv"
        
        # 전체 경로 생성
        filepath = os.path.join(save_dir, filename)
        
        # CSV 파일로 저장 (한글 깨짐 방지)
        df.to_csv(filepath, index=False, encoding='utf-8-sig')
        
        # 저장 결과 출력
        print(f"\n{'='*80}")
        print(f"💾 거래 기록 저장 완료")
        print(f"{'='*80}")
        print(f"   파일 경로: {filepath}")
        print(f"   총 거래 수: {len(df)}건")
        print(f"{'─'*80}")
        
        # 통계 정보 출력
        if len(df) > 0:
            total_profit = df['손익'].sum()
            avg_return = df['수익률(%)'].mean()
            win_trades = len(df[df['손익'] > 0])
            lose_trades = len(df[df['손익'] < 0])
            win_rate = (win_trades / len(df)) * 100 if len(df) > 0 else 0
            
            print(f"   📊 거래 통계")
            print(f"      - 총 손익: {total_profit:+,.0f}원")
            print(f"      - 평균 수익률: {avg_return:+.2f}%")
            print(f"      - 승리 거래: {win_trades}건")
            print(f"      - 패배 거래: {lose_trades}건")
            print(f"      - 승률: {win_rate:.1f}%")
            
            # 포지션별 통계
            if '포지션' in df.columns:
                print(f"\n   📈 포지션별 통계")
                for position_type in df['포지션'].unique():
                    position_df = df[df['포지션'] == position_type]
                    position_profit = position_df['손익'].sum()
                    position_avg_return = position_df['수익률(%)'].mean()
                    position_count = len(position_df)
                    
                    print(f"      - {position_type}: {position_count}건, "
                          f"손익 {position_profit:+,.0f}원, "
                          f"평균 수익률 {position_avg_return:+.2f}%")
        
        print(f"{'='*80}\n")
        
        return filepath
        
    except Exception as e:
        print(f"❌ CSV 저장 중 오류 발생: {e}")
        import traceback
        traceback.print_exc()
        return None

### 보유종목 전체 매도
def clear_all_stocks(access_token, base_url, app_key, app_secret, account_no, tr_id):
    """
    계좌의 모든 보유 종목을 전량 매도하는 함수 (2단계 분리 및 재시도 로직 적용)
    
    [로직 수정]
    1. 1단계: 매도 가능한 모든 종목의 주문을 '먼저' 접수
    2. 2단계: 접수된 주문들의 체결 여부를 '나중에' 확인
    
    Args:
        access_token: 접근 토큰
        base_url: API 기본 URL
        app_key: 앱 키
        app_secret: 앱 시크릿
        account_no: 계좌번호
        tr_id: 매도 주문용 TR ID (VTTC0801U: 모의투자, TTTC0801U: 실전투자)
    
    Returns:
        dict: 매도 결과 정보
    """
    global current_position
    
    print(f"\n{'='*80}")
    print(f"🧹 보유 종목 전량 매도 시작 (로직: 선-주문, 후-확인)")
    print(f"{'='*80}")
    
    try:
        cano, acnt_prdt_cd = account_no.split('-')
        
        # 1. 잔고 조회 (보유 종목 확인)
        balance_url = f"{base_url}/uapi/domestic-stock/v1/trading/inquire-balance"
        
        # TR ID 설정 (잔고조회용)
        balance_tr_id = "VTTC8434R" if "VTT" in tr_id else "TTTC8434R"
        
        headers = {
            "content-type": "application/json; charset=utf-8",
            "authorization": f"Bearer {access_token}",
            "appkey": app_key,
            "appsecret": app_secret,
            "tr_id": balance_tr_id
        }
        
        params = {
            "CANO": cano,
            "ACNT_PRDT_CD": acnt_prdt_cd,
            "AFHR_FLPR_YN": "N",  # 시간외단일가여부
            "OFL_YN": "",  # 오프라인여부
            "INQR_DVSN": "02",  # 조회구분(01:대출일별, 02:종목별)
            "UNPR_DVSN": "01",  # 단가구분
            "FUND_STTL_ICLD_YN": "N",  # 펀드결제분포함여부
            "FNCG_AMT_AUTO_RDPT_YN": "N",  # 융자금액자동상환여부
            "PRCS_DVSN": "01",  # 처리구분(00:전일매매포함, 01:전일매매미포함)
            "CTX_AREA_FK100": "",
            "CTX_AREA_NK100": ""
        }
        
        response = requests.get(balance_url, headers=headers, params=params)
        
        if response.status_code != 200:
            print(f"❌ 잔고 조회 실패: {response.status_code}")
            return {"rt_cd": "-1", "msg1": f"잔고 조회 실패: {response.status_code}"}
        
        data = response.json()
        
        if data.get("rt_cd") != "0":
            print(f"❌ 잔고 조회 응답 오류: {data.get('msg1')}")
            return {"rt_cd": "-1", "msg1": data.get('msg1')}
        
        # 2. 보유 종목 리스트 추출
        holdings = data.get("output1", [])
        
        if not holdings:
            print("ℹ️  보유 중인 종목이 없습니다.")
            # 보유 종목 없어도 포지션은 초기화
            current_position = {k: v for k, v in current_position.items() if k not in ["type", "buy_price", "buy_quantity", "buy_amount", "buy_time", "order_no", "basket_details"]}
            current_position.update({"type": None, "buy_price": 0, "buy_quantity": 0, "buy_amount": 0, "buy_time": None, "order_no": None, "basket_details": []})
            print("📝 포지션 정보 초기화 완료\n")
            return {"rt_cd": "0", "msg1": "보유 종목 없음"}
        
        # 매도 가능한 종목만 필터링
        sellable_stocks = []
        for stock in holdings:
            stock_code = stock.get("pdno", "")
            stock_name = stock.get("prdt_name", "")
            quantity = int(stock.get("hldg_qty", 0))  # 보유수량
            sellable_qty = int(stock.get("ord_psbl_qty", 0))  # 매도가능수량
            
            if sellable_qty > 0:
                sellable_stocks.append({
                    "code": stock_code,
                    "name": stock_name,
                    "quantity": quantity,
                    "sellable_qty": sellable_qty,
                    "current_price": int(stock.get("prpr", 0))  # 현재가
                })
        
        if not sellable_stocks:
            print("ℹ️  매도 가능한 종목이 없습니다.")
            # 매도 가능 종목 없어도 포지션은 초기화
            current_position = {k: v for k, v in current_position.items() if k not in ["type", "buy_price", "buy_quantity", "buy_amount", "buy_time", "order_no", "basket_details"]}
            current_position.update({"type": None, "buy_price": 0, "buy_quantity": 0, "buy_amount": 0, "buy_time": None, "order_no": None, "basket_details": []})
            print("📝 포지션 정보 초기화 완료\n")
            return {"rt_cd": "0", "msg1": "매도 가능 종목 없음"}
        
        print(f"\n📋 매도 예정 종목: 총 {len(sellable_stocks)}개")
        for i, stock in enumerate(sellable_stocks, 1):
            print(f"   [{i:2d}] {stock['name']:15s} ({stock['code']}): "
                  f"{stock['sellable_qty']:,}주 (현재가: {stock['current_price']:,}원)")
        print(f"{'='*80}\n")
        
        # 1단계 재시도 로직을 위한 상수
        MAX_RETRY_ATTEMPTS = 5
        RETRY_DELAY_SEC = 1

        pending_orders = [] # 주문 접수 성공 목록
        failed_orders = []  # 주문 접수 실패 목록 (1단계)
        success_orders = [] # 체결 확인 성공 목록 (2단계)
        total_sell_amount = 0
        
        # ==========================================================
        # 3. 1단계: 모든 종목에 대해 '매도 주문 접수' 먼저 실행
        # ==========================================================
        print(f"--- 1단계: {len(sellable_stocks)}개 종목 매도 주문 접수 시작 (실패 시 최대 {MAX_RETRY_ATTEMPTS}회 재시도) ---")
        
        for idx, stock in enumerate(sellable_stocks, 1):
            stock_code = stock["code"]
            stock_name = stock["name"]
            quantity = stock["sellable_qty"] # 매도 가능 수량
            
            is_order_placed = False
            attempt = 0
            last_reason = "N/A"

            while not is_order_placed and attempt < MAX_RETRY_ATTEMPTS:
                attempt += 1
                print(f"   [{idx}/{len(sellable_stocks)}] {stock_name} ({stock_code}) {quantity}주 매도 시도... (시도 {attempt}/{MAX_RETRY_ATTEMPTS})")
                
                try:
                    # 매도 주문
                    sell_url = f"{base_url}/uapi/domestic-stock/v1/trading/order-cash"
                    sell_headers = {
                        "content-type": "application/json; charset=utf-8",
                        "authorization": f"Bearer {access_token}",
                        "appkey": app_key,
                        "appsecret": app_secret,
                        "tr_id": tr_id
                    }
                    
                    body = {
                        "CANO": cano,
                        "ACNT_PRDT_CD": acnt_prdt_cd,
                        "PDNO": stock_code,
                        "ORD_DVSN": "01",  # 시장가
                        "ORD_QTY": str(quantity),
                        "ORD_UNPR": "0"
                    }
                    
                    sell_response = requests.post(sell_url, headers=sell_headers, data=json.dumps(body))
                    
                    if sell_response.status_code == 200:
                        result = sell_response.json()
                        
                        if result.get("rt_cd") == "0":
                            order_no = result["output"]["ODNO"]
                            print(f"    ✅ 주문 접수 성공 (주문번호: {order_no})")
                            pending_orders.append({
                                "code": stock_code,
                                "name": stock_name,
                                "quantity": quantity, # 매도 주문 수량
                                "order_no": order_no
                            })
                            is_order_placed = True
                        else:
                            last_reason = result.get('msg1', '알 수 없는 오류')
                            print(f"    ⚠️ 주문 접수 실패 (API 오류): {last_reason}")
                    else:
                        last_reason = f"API 호출 실패: {sell_response.status_code}"
                        print(f"    ⚠️ 주문 접수 실패 (HTTP 오류): {last_reason}")
                    
                except Exception as e:
                    last_reason = str(e)
                    print(f"    ⚠️ 주문 중 오류 (Exception): {last_reason}")
                
                time.sleep(0.3) # API 호출 제한
                
                if not is_order_placed and attempt < MAX_RETRY_ATTEMPTS:
                    print(f"    ... {RETRY_DELAY_SEC}초 후 재시도 ...")
                    time.sleep(RETRY_DELAY_SEC)
            
            if not is_order_placed:
                print(f"    ❌ 최종 주문 접수 실패 (재시도 횟수 초과)")
                failed_orders.append({
                    "code": stock_code,
                    "name": stock_name,
                    "reason": f"주문 접수 최종 실패: {last_reason}"
                })
        
        print(f"--- 1단계 완료 (성공: {len(pending_orders)} / 실패: {len(failed_orders)}) ---\n")
        
        if pending_orders:
            time.sleep(3) # 3초 후부터 체결확인

        # ==========================================================
        # 4. 2단계: 접수 성공한 주문들의 '체결 확인' 실행
        # ==========================================================
        print(f"--- 2단계: {len(pending_orders)}개 주문 체결 확인 시작 ---")
        
        check_tr_id = "VTTC8001R" if "VTT" in tr_id else "TTTC8001R"
        
        while pending_orders:
            print(f"\n   ... (현재 {len(pending_orders)}개 주문 체결 확인 필요) ...")
            
            for order in pending_orders.copy():
                stock_name = order["name"]
                order_no = order["order_no"]
                original_quantity = order["quantity"] # 매도 주문 수량
                
                print(f"   [확인 시도] {stock_name} ({order_no}) 체결 확인 중...")
                
                try:
                    # 체결 확인 (기존 180초 타임아웃 유지)
                    is_filled = _check_order_filled(
                        access_token, base_url, app_key, app_secret,
                        account_no, order_no, check_tr_id, max_attempts=180 
                    )
                    
                    if is_filled:
                        # 체결가 조회
                        filled_price, filled_qty = _get_filled_price(
                            access_token, base_url, app_key, app_secret,
                            account_no, order_no, check_tr_id
                        )
                        
                        if filled_price and filled_qty:
                            if filled_qty != original_quantity:
                                print(f"    ⚠️ 경고: 주문 수량({original_quantity})과 체결 수량({filled_qty})이 다름")

                            sell_amount = filled_price * filled_qty
                            total_sell_amount += sell_amount
                            
                            success_orders.append({
                                "code": order["code"],
                                "name": stock_name,
                                "order_no": order_no,
                                "quantity": filled_qty,
                                "price": filled_price,
                                "amount": sell_amount
                            })
                            
                            print(f"    💰 체결 완료: {filled_price:,}원 x {filled_qty}주 = {sell_amount:,}원")
                            
                            pending_orders.remove(order)
                        
                        else:
                            print(f"    ⚠️ 체결가 조회 실패 (체결은 됨). 5초 후 재시도...")
                            time.sleep(3)
                    else:
                        print(f"    ⚠️ 체결 확인 타임아웃 (180초). 다음 루프에서 재시도...")
                
                except Exception as e:
                    reason = f"체결 확인 중 오류: {e}"
                    print(f"    ❌ {reason}. 5초 후 재시도...")
                    time.sleep(5)

            if pending_orders:
                print(f"   ... (미체결 {len(pending_orders)}건) 5초 후 재확인 시작 ...")
                time.sleep(5)

        print(f"--- 2단계 완료 (체결 확인 성공: {len(success_orders)}건) ---\n")
        
        # 5. 최종 결과 출력
        print(f"\n{'='*80}")
        print(f"🎯 전량 매도 최종 완료")
        print(f"{'='*80}")
        print(f"✅ 최종 성공: {len(success_orders)}/{len(sellable_stocks)}개 종목")
        print(f"❌ 최종 실패: {len(failed_orders)}/{len(sellable_stocks)}개 종목 (1단계 주문 접수 실패)")
        print(f"💰 총 매도 금액: {total_sell_amount:,}원")
        
        if failed_orders:
            print(f"\n⚠️  실패한 종목 (1단계 주문 접수 실패):")
            for order in failed_orders:
                print(f"   - {order['name']} ({order['code']}): {order['reason']}")
        
        if success_orders:
            print(f"\n📋 매도 완료 종목:")
            for order in success_orders:
                print(f"   {order['name']:15s}: {order['quantity']:,}주 x {order['price']:,}원 = {order['amount']:,}원")
        
        print(f"{'='*80}\n")
        
        # 6. 포지션 초기화 (전량 청산이므로)
        current_position["type"] = "none"
        current_position["buy_price"] = 0
        current_position["buy_quantity"] = 0
        current_position["buy_amount"] = 0
        current_position["buy_time"] = None
        current_position["order_no"] = None
        if "basket_details" in current_position:
            current_position["basket_details"] = []
        
        print("📝 포지션 정보 초기화 완료\n")
        
        return {
            "rt_cd": "0" if success_orders else "-1",
            "success": success_orders,
            "failed": failed_orders,
            "total_sell_amount": total_sell_amount
        }
        
    except Exception as e:
        print(f"❌ 전량 매도 중 치명적 오류 발생: {e}")
        import traceback
        traceback.print_exc()
        return {"rt_cd": "-1", "msg1": str(e)}
    
### 현재 포지션 확인 함수 (live_trading.py에서 이동 및 수정)
def get_current_position(access_token, base_url, app_key, app_secret, account_no, is_real):
    """
    현재 잔고를 조회하여 포지션 상태를 반환
    [수정]
    - (1) trading_function.py의 전역 변수 'current_position' 딕셔너리를 업데이트
    - (2) live_trading.py의 메인 로직을 위해 포지션 상태 문자열(str)을 반환
    
    Args:
        access_token: 접근 토큰
        base_url: API 기본 URL
        app_key: 앱 키
        app_secret: 앱 시크릿
        account_no: 계좌번호 (예: "50154524-01")
        is_real: 실전투자 여부 (bool)
    
    Returns:
        str: 포지션 상태 ("none", "basket", "etf")
    """
    
    global current_position # [추가] 전역 변수 사용 선언
    
    try:
        print(f"\n🔍 현재 포지션 확인 중... (global 'current_position' 갱신)")
        
        cano, acnt_prdt_cd = account_no.split('-')
        
        # 잔고 조회 파라미터
        params = {
            "CANO": cano,
            "ACNT_PRDT_CD": acnt_prdt_cd,
            "AFHR_FLPR_YN": "N",
            "OFL_YN": "",
            "INQR_DVSN": "02",  # 종목별 조회
            "UNPR_DVSN": "01",
            "FUND_STTL_ICLD_YN": "N",
            "FNCG_AMT_AUTO_RDPT_YN": "N",
            "PRCS_DVSN": "00",
            "CTX_AREA_FK100": "",
            "CTX_AREA_NK100": ""
        }
        
        # REST API 호출
        url = f"{base_url}/uapi/domestic-stock/v1/trading/inquire-balance"
        headers = {
            "content-type": "application/json; charset=utf-8",
            "authorization": f"Bearer {access_token}",
            "appkey": app_key,
            "appsecret": app_secret,
            "tr_id": "VTTC8434R" if not is_real else "TTTC8434R"
        }
        
        response = requests.get(url, headers=headers, params=params)
        
        # [수정] 전역 변수 초기화 (기존 상태를 지움)
        current_position = {
            "type": None, "buy_price": 0, "buy_quantity": 0, "buy_amount": 0,
            "buy_time": None, "order_no": None, "basket_details": []
        }
        
        if response.status_code != 200:
            print(f"❌ 잔고 조회 실패: {response.status_code}")
            print(f"   응답: {response.text}")
            current_position["type"] = "none"
            return "none"
        
        result = response.json()
        
        if result.get('rt_cd') != '0':
            print(f"❌ 잔고 조회 오류: {result.get('msg1', 'Unknown error')}")
            current_position["type"] = "none"
            return "none"
        
        # 보유 종목 리스트
        holdings = result.get('output1', [])
        
        if not holdings or len(holdings) == 0:
            print("✅ 포지션 없음 (잔고 비어있음)")
            current_position["type"] = "none"
            return "none"
        
        # 삼성그룹 종목 코드 리스트
        samsung_codes = [
            "028050", "006400", "028260", "032830", "018260",
            "009150", "005930", "010140", "016360", "029780",
            "000810", "012750", "030000", "008770"
        ]
        
        # ETF 코드
        etf_code = "102780"
        
        # 보유 종목 확인
        has_etf = False
        basket_stocks_found = [] # [수정] 바스켓 상세내역 저장
        
        for item in holdings:
            stock_code = item.get('pdno', '')
            quantity = int(item.get('hldg_qty', 0))
            stock_name = item.get('prdt_name', stock_code)
            
            if quantity > 0:
                if stock_code == etf_code:
                    has_etf = True
                    print(f"  📊 ETF 보유: {stock_code} ({quantity}주)")
                    
                    # [추가] 전역 변수 업데이트
                    current_position["type"] = "etf"
                    current_position["buy_quantity"] = quantity
                    # [경고] 알 수 없는 값
                    current_position["buy_price"] = 0 
                    current_position["buy_amount"] = 0
                    current_position["buy_time"] = datetime.now() # 임시로 현재시간
                    
                    print("   ⚠️  [경고] ETF 포지션 감지. 'buy_price'/'buy_amount'는 알 수 없으므로 0으로 설정됩니다.")
                    print("   ⚠️  첫 매도 시 손익 계산이 정확하지 않을 수 있습니다.")
                    
                    break # ETF가 1순위
                
                elif stock_code in samsung_codes:
                    print(f"  📦 바스켓 종목: {stock_name} ({quantity}주)")
                    basket_stocks_found.append({
                        "code": stock_code,
                        "name": stock_name,
                        "quantity": quantity,
                        "price": 0, # [경고] 매수 단가 알 수 없음
                        "amount": 0
                    })
        
        # 포지션 판단
         #1. ETF 우선 체크
        if has_etf:
            print("✅ 현재 포지션: ETF 보유 중")
            return "etf" # current_position은 이미 위에서 set됨
        
         #2. 바스켓 체크
        BASKET_COMPLETE_THRESHOLD = len(samsung_codes)
        basket_stock_count = len(basket_stocks_found)

        if basket_stock_count >= BASKET_COMPLETE_THRESHOLD:
            print(f"✅ 현재 포지션: 바스켓 보유 중 ({basket_stock_count}/{len(samsung_codes)}개)")
            
            # [추가] 전역 변수 업데이트
            current_position["type"] = "basket"
            current_position["basket_details"] = basket_stocks_found
            current_position["buy_amount"] = 0 # 알 수 없음
            current_position["buy_time"] = datetime.now() # 임시로 현재시간
            
            print("   ⚠️  [경고] 바스켓 포지션 감지. 개별 'buy_price'는 알 수 없으므로 0으로 설정됩니다.")
            print("   ⚠️  첫 매도 시 손익 계산이 정확하지 않을 수 있습니다.")
            
            return "basket"
        
         #3. 포지션 없음
        else:
            print("✅ 현재 포지션: 없음 (ETF/바스켓 완성 안됨)")
            current_position["type"] = "none" # 이미 위에서 초기화됨
            return "none"
        
    except Exception as e:
        print(f"❌ 포지션 확인 중 오류: {e}")
        traceback.print_exc()
        
        # [추가] 오류 발생 시에도 전역 변수 초기화
        current_position = {
            "type": "none", "buy_price": 0, "buy_quantity": 0, "buy_amount": 0,
            "buy_time": None, "order_no": None, "basket_details": []
        }
        return "none"
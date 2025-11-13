import requests
import json
import time
import pandas as pd
from datetime import datetime
from utils import get_basket_qty, SAMSUNG_STOCKS

# ==============================================================================
# ===================== part 1. 전역 변수: 거래 기록 관리 ======================
# ==============================================================================

# 거래 기록 저장
trade_history = []

# 현재 보유 포지션 정보
current_position = {
    "type": None,  # "etf" or "basket"
    "buy_price": 0,  # 매수 단가
    "buy_quantity": 0,  # 매수 수량
    "buy_amount": 0,  # 총 매수 금액
    "buy_time": None,  # 매수 시간
    "order_no": None  # 주문 번호
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
                # "CTX_AREA_FK100": "",
                # "CTX_AREA_NK100": "",
                # "INQR_DVSN_1": "0",  # 전체
                # "INQR_DVSN_2": "0"   # 전체
                # 필수 조회 기간 추가
                "INQR_STRT_DT": datetime.now().strftime("%Y%m%d"),
                "INQR_END_DT": datetime.now().strftime("%Y%m%d"),
                # 추가 필드(문서 확인 필요: 필요 시 값 조정)
                "CTX_AREA_FK100": "",
                "CTX_AREA_NK100": "",
                "INQR_DVSN_1": "0",  # 전체
                "INQR_DVSN_2": "0"   # 전체
            }
            # 디버그: 보낸 파라미터 출력
            print(f"DEBUG: _check_order_filled params={params}")

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

### 체결가 조회 함수
def _get_filled_price(access_token, base_url, app_key, app_secret, 
                      account_no, order_no, tr_id):
    """
    주문번호로 실제 체결가를 조회하는 함수
    
    Args:
        access_token: 접근 토큰
        base_url: API 기본 URL
        app_key: 앱 키
        app_secret: 앱 시크릿
        account_no: 계좌번호
        order_no: 주문번호
        tr_id: TR ID (VTTC8001R: 모의투자, TTTC8001R: 실전투자)
    
    Returns:
        tuple: (체결가, 체결수량) 또는 (None, None)
    """
    try:
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
        
        if response.status_code == 200:
            data = response.json()
            
            if data.get("rt_cd") == "0":
                orders = data.get("output1", [])
                
                # 해당 주문번호 찾기
                for order in orders:
                    if order.get("odno") == order_no:
                        # 체결가와 체결수량
                        filled_price = int(order.get("avg_prvs", 0))  # 평균 체결가
                        filled_qty = int(order.get("tot_ccld_qty", 0))  # 총 체결수량
                        
                        if filled_price > 0 and filled_qty > 0:
                            return filled_price, filled_qty
                
                print(f"⚠️  주문번호 {order_no}의 체결 정보를 찾을 수 없습니다.")
    
    except Exception as e:
        print(f"⚠️  체결가 조회 중 오류: {e}")
        import traceback
        traceback.print_exc()
    
    return None, None


# ==============================================================================
# ====================== part 3. ETF 매수/매도 함수 ===========================
# ==============================================================================

### 1) 삼성그룹 ETF 매수 함수
def buy_etf(access_token, base_url, app_key, app_secret, account_no, tr_id):

    global current_position
    
    # ------ 종목, 수량 설정 !!! --------
    stock_code = "102780" 
    stock_name = "KODEX 삼성그룹"
    quantity = 1  # 1주
    # ----------------------------------
    print(f"\n{'='*80}")
    print(f"🟢 ETF 매수 주문 시작")
    print(f"   종목: {stock_name} ({stock_code})")
    print(f"   수량: {quantity}주")
    print(f"{'='*80}")
    
    try:
        cano, acnt_prdt_cd = account_no.split('-')
        
        # 1. 매수 주문
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
            "ORD_DVSN": "01",  # 주문구분코드(시장가는 01)
            "ORD_QTY": str(quantity),
            "ORD_UNPR": "0"  # 주문단가 (시장가는 0)
        }
        
        response = requests.post(url, headers=headers, data=json.dumps(body))
        
        if response.status_code == 200:
            result = response.json()
            
            if result.get("rt_cd") == "0":
                order_no = result["output"]["ODNO"]
                print(f"✅ 매수 주문 접수 성공")
                print(f"   주문번호: {order_no}")
                
                # 3. 체결 확인
                check_tr_id = "VTTC8001R" if "VTT" in tr_id else "TTTC8001R"
                is_filled = _check_order_filled(
                    access_token, base_url, app_key, app_secret,
                    account_no, order_no, check_tr_id
                )
                
                if is_filled:
                    # 4. 체결가 조회
                    filled_price, filled_qty = _get_filled_price(
                        access_token, base_url, app_key, app_secret,
                        account_no, order_no, check_tr_id
                    )
                    if filled_price is None:
                        print("⚠️  체결가 조회 실패 (현재가로 대체)")
                        filled_price = 0
                    
                    # 5. 매수 정보 기록
                    buy_time = datetime.now()
                    buy_amount = filled_price * quantity
                    
                    current_position["type"] = "etf"
                    current_position["buy_price"] = filled_price
                    current_position["buy_quantity"] = quantity
                    current_position["buy_amount"] = buy_amount
                    current_position["buy_time"] = buy_time
                    current_position["order_no"] = order_no
                    
                    print(f"\n💰 매수 완료!")
                    print(f"   매수 단가: {filled_price:,}원")
                    print(f"   매수 수량: {quantity}주")
                    print(f"   매수 금액: {buy_amount:,}원")
                    print(f"   매수 시간: {buy_time.strftime('%Y-%m-%d %H:%M:%S')}")
                    
                    return result
                else:
                    print("⚠️  체결 확인 실패")
                    return {"rt_cd": "-1", "msg1": "체결 확인 실패"}
            else:
                print(f"❌ 매수 주문 실패: {result.get('msg1')}")
                return result
        else:
            print(f"❌ 매수 주문 API 호출 실패: {response.status_code}")
            return {"rt_cd": "-1", "msg1": f"API 호출 실패: {response.status_code}"}
    
    except Exception as e:
        print(f"❌ 매수 중 오류 발생: {e}")
        import traceback
        traceback.print_exc()
        return {"rt_cd": "-1", "msg1": str(e)}

### 2) 삼성그룹 ETF 매도 함수
def sell_etf(access_token, base_url, app_key, app_secret, account_no, tr_id):
    global current_position, trade_history
    
    # ------ 종목, 수량 설정 !!! --------
    stock_code = "102780" 
    stock_name = "KODEX 삼성그룹"
    quantity = 1  # 1주
    # ----------------------------------
    
    print(f"\n{'='*80}")
    print(f"🔴 ETF 매도 주문 시작")
    print(f"   종목: {stock_name} ({stock_code})")
    print(f"   수량: {quantity}주")
    print(f"{'='*80}")
    
    try:
        cano, acnt_prdt_cd = account_no.split('-')
        
        # 1. 매도 주문
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
            "ORD_DVSN": "01",  #주문구분코드 (시장가는 01)
            "ORD_QTY": str(quantity),
            "ORD_UNPR": "0"  #주문단가 (시장가는 0)
        }
        
        response = requests.post(url, headers=headers, data=json.dumps(body))
        
        if response.status_code == 200:
            result = response.json()
            
            if result.get("rt_cd") == "0":
                order_no = result["output"]["ODNO"]
                print(f"✅ 매도 주문 접수 성공")
                print(f"   주문번호: {order_no}")
                
                # 3. 체결 확인
                check_tr_id = "VTTC8001R" if "VTT" in tr_id else "TTTC8001R"
                is_filled = _check_order_filled(
                    access_token, base_url, app_key, app_secret,
                    account_no, order_no, check_tr_id
                )
                
                if is_filled:
                    # 4. 체결가 조회
                    filled_price, filled_qty = _get_filled_price(
                        access_token, base_url, app_key, app_secret,
                        account_no, order_no, check_tr_id
                    )
                    if filled_price is None:
                        print("⚠️  체결가 조회 실패 (현재가로 대체)")
                        filled_price = 0
                    
                    # 5. 수익률 계산 및 기록
                    sell_time = datetime.now()
                    sell_amount = filled_price * quantity
                    
                    # 매수 정보가 있는 경우에만 수익률 계산
                    if current_position["type"] == "etf" and current_position["buy_amount"] > 0:
                        buy_amount = current_position["buy_amount"]
                        buy_time = current_position["buy_time"]
                        
                        profit = sell_amount - buy_amount
                        return_rate = (profit / buy_amount) * 100
                        
                        # 거래 기록 저장
                        trade_record = {
                            "거래일시": sell_time.strftime('%Y-%m-%d %H:%M:%S'),
                            "포지션": "ETF",
                            "매수시간": buy_time.strftime('%Y-%m-%d %H:%M:%S'),
                            "매도시간": sell_time.strftime('%Y-%m-%d %H:%M:%S'),
                            "매수금액": buy_amount,
                            "매도금액": sell_amount,
                            "손익": profit,
                            "수익률(%)": round(return_rate, 2)
                        }
                        
                        trade_history.append(trade_record)
                        
                        print(f"\n💰 매도 완료 및 수익률 기록!")
                        print(f"{'='*80}")
                        print(f"   매도 단가: {filled_price:,}원")
                        print(f"   매도 수량: {quantity}주")
                        print(f"   매도 금액: {sell_amount:,}원")
                        print(f"   매도 시간: {sell_time.strftime('%Y-%m-%d %H:%M:%S')}")
                        print(f"{'─'*80}")
                        print(f"   매수 금액: {buy_amount:,}원")
                        print(f"   손익: {profit:+,}원")
                        print(f"   수익률: {return_rate:+.2f}%")
                        print(f"{'='*80}")
                        
                        # 포지션 초기화
                        current_position["type"] = None
                        current_position["buy_price"] = 0
                        current_position["buy_quantity"] = 0
                        current_position["buy_amount"] = 0
                        current_position["buy_time"] = None
                        current_position["order_no"] = None
                    else:
                        print(f"\n💰 매도 완료!")
                        print(f"   매도 단가: {filled_price:,}원")
                        print(f"   매도 수량: {quantity}주")
                        print(f"   매도 금액: {sell_amount:,}원")
                        print(f"   ⚠️  매수 정보 없음 (수익률 계산 불가)")
                    
                    return result
                else:
                    print("⚠️  체결 확인 실패")
                    return {"rt_cd": "-1", "msg1": "체결 확인 실패"}
            else:
                print(f"❌ 매도 주문 실패: {result.get('msg1')}")
                return result
        else:
            print(f"❌ 매도 주문 API 호출 실패: {response.status_code}")
            return {"rt_cd": "-1", "msg1": f"API 호출 실패: {response.status_code}"}
    
    except Exception as e:
        print(f"❌ 매도 중 오류 발생: {e}")
        import traceback
        traceback.print_exc()
        return {"rt_cd": "-1", "msg1": str(e)}

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
        total_stocks = len(basket_qty)
        for i, (stock_code, qty) in enumerate(basket_qty.items(), 1):
            name = SAMSUNG_STOCKS.get(stock_code, "알 수 없음")
            print(f"   [{i:2d}/{total_stocks}] {name:15s} ({stock_code}): {qty:3d}주")
        print(f"{'='*80}\n")
        
        cano, acnt_prdt_cd = account_no.split('-')
        
        pending_orders = [] # 주문 접수 성공 목록
        failed_orders = []  # 주문 접수 실패 목록
        
        # ==========================================================
        # 1단계: 모든 종목에 대해 '주문 접수' 먼저 실행
        # ==========================================================
        print(f"--- 1단계: {total_stocks}개 종목 주문 접수 시작 ---")
        for idx, (stock_code, quantity) in enumerate(basket_qty.items(), 1):
            stock_name = SAMSUNG_STOCKS.get(stock_code, "알 수 없음")
            
            print(f"  [{idx}/{total_stocks}] {stock_name} ({stock_code}) {quantity}주 주문 시도...")
            
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
                    else:
                        reason = result.get('msg1', '알 수 없는 오류')
                        print(f"    ❌ 주문 접수 실패: {reason}")
                        failed_orders.append({
                            "code": stock_code,
                            "name": stock_name,
                            "reason": f"주문 실패: {reason}"
                        })
                else:
                    reason = f"API 호출 실패: {response.status_code}"
                    print(f"    ❌ 주문 접수 실패: {reason}")
                    failed_orders.append({
                        "code": stock_code,
                        "name": stock_name,
                        "reason": reason
                    })
                
                # API 호출 제한 고려 (초당 4건)
                time.sleep(0.25) 
                
            except Exception as e:
                reason = str(e)
                print(f"    ❌ 주문 중 오류: {reason}")
                failed_orders.append({
                    "code": stock_code,
                    "name": stock_name,
                    "reason": reason
                })
        
        print(f"--- 1단계 완료 (성공: {len(pending_orders)} / 실패: {len(failed_orders)}) ---\n")
        
        # ==========================================================
        # 2단계: 접수 성공한 주문들의 '체결 확인' 실행
        # ==========================================================
        print(f"--- 2단계: {len(pending_orders)}개 주문 체결 확인 시작 ---")
        
        success_orders = []
        total_amount = 0
        check_tr_id = "VTTC8001R" if "VTT" in tr_id else "TTTC8001R"
        
        for idx, order in enumerate(pending_orders, 1):
            stock_name = order["name"]
            order_no = order["order_no"]
            
            print(f"  [{idx}/{len(pending_orders)}] {stock_name} ({order_no}) 체결 확인 중...")
            
            try:
                # 1. 체결 확인
                is_filled = _check_order_filled(
                    access_token, base_url, app_key, app_secret,
                    account_no, order_no, check_tr_id, max_attempts=30 
                )
                
                if is_filled:
                    # 2. 체결가 조회
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
                        print(f"    💰 체결 완료: {filled_price:,}원 x {filled_qty}주 = {amount:,}원")
                    else:
                        print(f"    ⚠️ 체결가 조회 실패")
                        failed_orders.append({
                            "code": order["code"],
                            "name": stock_name,
                            "reason": "체결 완료했으나 체결가 조회 실패"
                        })
                else:
                    print(f"    ⚠️ 체결 확인 실패 (타임아웃)")
                    failed_orders.append({
                        "code": order["code"],
                        "name": stock_name,
                        "reason": "체결 확인 타임아웃"
                    })
            
            except Exception as e:
                reason = f"체결 확인 중 오류: {e}"
                print(f"    ❌ {reason}")
                failed_orders.append({
                    "code": order["code"],
                    "name": stock_name,
                    "reason": reason
                })

        print(f"--- 2단계 완료 (체결 성공: {len(success_orders)} / 체결 실패: {len(pending_orders) - len(success_orders)}) ---\n")

        # 3. 최종 결과 출력
        print(f"\n{'='*80}")
        print(f"🎯 바스켓 매수 최종 완료")
        print(f"{'='*80}")
        print(f"✅ 최종 성공: {len(success_orders)}/{total_stocks}개 종목")
        print(f"❌ 최종 실패: {len(failed_orders)}/{total_stocks}개 종목")
        print(f"💰 총 매수 금액: {total_amount:,}원")
        
        if failed_orders:
            print(f"\n⚠️ 실패한 종목:")
            for order in failed_orders:
                print(f"   - {order['name']} ({order.get('code', 'N/A')}): {order['reason']}")
        
        # 4. 포지션 정보 저장
        if success_orders:
            current_position["type"] = "basket"
            current_position["buy_amount"] = total_amount
            current_position["buy_time"] = datetime.now()
            current_position["basket_details"] = success_orders
            
            print(f"\n📝 포지션 정보 업데이트:")
            print(f"   - 포지션 타입: 바스켓")
            print(f"   - 총 매수 금액: {total_amount:,}원")
            print(f"   - 매수 시간: {current_position['buy_time'].strftime('%H:%M:%S')}")
            print(f"   - 종목 수: {len(success_orders)}개")
        
        print(f"{'='*80}\n")
        
        return {
            "rt_cd": "0" if success_orders else "-1",
            "success": success_orders,
            "failed": failed_orders,
            "total_amount": total_amount
        }
        
    except Exception as e:
        print(f"❌ 바스켓 매수 중 치명적 오류 발생: {e}")
        import traceback
        traceback.print_exc()
        return {"rt_cd": "-1", "msg1": str(e)}

### 4) 바스켓 매도 함수
def sell_basket(access_token, base_url, app_key, app_secret, account_no, tr_id):
    """
    삼성그룹 바스켓(개별 종목들) 매도 함수
    buy_basket에서 매수한 종목들을 매도
    """
    global current_position, trade_history
    
    print(f"\n{'='*80}")
    print(f"🔴 바스켓 매도 주문 시작")
    print(f"{'='*80}")
    
    try:
        # 1. 매수한 바스켓 정보 확인
        if current_position["type"] != "basket":
            print("❌ 보유 중인 바스켓 포지션이 없습니다.")
            return {"rt_cd": "-1", "msg1": "바스켓 포지션 없음"}
        
        basket_details = current_position.get("basket_details", [])
        
        if not basket_details:
            print("❌ 바스켓 상세 정보가 없습니다.")
            return {"rt_cd": "-1", "msg1": "바스켓 상세 정보 없음"}
        
        buy_amount = current_position["buy_amount"]
        buy_time = current_position["buy_time"]
        
        print(f"\n📋 매도 예정 종목:")
        total_stocks = len(basket_details)
        for i, stock in enumerate(basket_details, 1):
            print(f"   [{i:2d}/{total_stocks}] {stock['name']:15s} ({stock['code']}): {stock['quantity']:3d}주")
        print(f"{'='*80}\n")
        
        # 2. 각 종목 매도 실행
        cano, acnt_prdt_cd = account_no.split('-')
        success_orders = []
        failed_orders = []
        total_sell_amount = 0
        
        for idx, stock_info in enumerate(basket_details, 1):
            stock_code = stock_info["code"]
            stock_name = stock_info["name"]
            quantity = stock_info["quantity"]
            buy_price = stock_info["price"]
            
            print(f"\n[{idx}/{total_stocks}] {stock_name} ({stock_code}) {quantity}주 매도 중...")
            
            try:
                # 매도 주문
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
                        print(f"   ✅ 주문 접수 성공 (주문번호: {order_no})")
                        
                        # 체결 확인
                        check_tr_id = "VTTC8001R" if "VTT" in tr_id else "TTTC8001R"
                        is_filled = _check_order_filled(
                            access_token, base_url, app_key, app_secret,
                            account_no, order_no, check_tr_id, max_attempts=30
                        )
                        
                        if is_filled:
                            # 체결가 조회
                            filled_price, filled_qty = _get_filled_price(
                                access_token, base_url, app_key, app_secret,
                                account_no, order_no, check_tr_id
                            )
                            
                            if filled_price and filled_qty:
                                sell_amount = filled_price * filled_qty
                                total_sell_amount += sell_amount
                                
                                # 개별 종목 손익
                                stock_profit = sell_amount - (buy_price * quantity)
                                stock_return = (stock_profit / (buy_price * quantity)) * 100
                                
                                success_orders.append({
                                    "code": stock_code,
                                    "name": stock_name,
                                    "order_no": order_no,
                                    "quantity": filled_qty,
                                    "buy_price": buy_price,
                                    "sell_price": filled_price,
                                    "profit": stock_profit,
                                    "return_rate": stock_return
                                })
                                
                                print(f"   💰 체결 완료: {filled_price:,}원 x {filled_qty}주 = {sell_amount:,}원")
                                print(f"   📊 종목 손익: {stock_profit:+,}원 ({stock_return:+.2f}%)")
                            else:
                                print(f"   ⚠️  체결가 조회 실패")
                                failed_orders.append({
                                    "code": stock_code,
                                    "name": stock_name,
                                    "reason": "체결가 조회 실패"
                                })
                        else:
                            print(f"   ⚠️  체결 확인 실패")
                            failed_orders.append({
                                "code": stock_code,
                                "name": stock_name,
                                "reason": "체결 확인 타임아웃"
                            })
                    else:
                        print(f"   ❌ 주문 실패: {result.get('msg1')}")
                        failed_orders.append({
                            "code": stock_code,
                            "name": stock_name,
                            "reason": result.get('msg1', '알 수 없는 오류')
                        })
                else:
                    print(f"   ❌ API 호출 실패: {response.status_code}")
                    failed_orders.append({
                        "code": stock_code,
                        "name": stock_name,
                        "reason": f"API 호출 실패: {response.status_code}"
                    })
                
                # 다음 주문 전 잠시 대기 (API 호출 제한 고려)
                time.sleep(0.5)
                
            except Exception as e:
                print(f"   ❌ 오류 발생: {e}")
                failed_orders.append({
                    "code": stock_code,
                    "name": stock_name,
                    "reason": str(e)
                })
        
        # 3. 전체 수익률 계산
        sell_time = datetime.now()
        total_profit = total_sell_amount - buy_amount
        total_return_rate = (total_profit / buy_amount) * 100 if buy_amount > 0 else 0
        
        # 4. 최종 결과 출력
        print(f"\n{'='*80}")
        print(f"🎯 바스켓 매도 완료")
        print(f"{'='*80}")
        print(f"✅ 성공: {len(success_orders)}/{total_stocks}개 종목")
        print(f"❌ 실패: {len(failed_orders)}/{total_stocks}개 종목")
        print(f"{'─'*80}")
        print(f"💰 매수 금액: {buy_amount:,}원")
        print(f"💰 매도 금액: {total_sell_amount:,}원")
        print(f"📊 총 손익: {total_profit:+,}원")
        print(f"📈 수익률: {total_return_rate:+.2f}%")
        
        if failed_orders:
            print(f"\n⚠️  실패한 종목:")
            for order in failed_orders:
                print(f"   - {order['name']} ({order['code']}): {order['reason']}")
        
        if success_orders:
            print(f"\n📋 종목별 수익률:")
            for order in success_orders:
                print(f"   {order['name']:15s}: {order['profit']:+8,}원 ({order['return_rate']:+6.2f}%)")
        
        print(f"{'='*80}\n")
        
        # 5. 거래 기록 저장
        if success_orders:
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
                "실패종목수": len(failed_orders)
            }
            
            trade_history.append(trade_record)
            print(f"📝 거래 기록 저장 완료")
        
        # 6. 포지션 초기화
        current_position["type"] = None
        current_position["buy_price"] = 0
        current_position["buy_quantity"] = 0
        current_position["buy_amount"] = 0
        current_position["buy_time"] = None
        current_position["order_no"] = None
        current_position["basket_details"] = []
        
        return {
            "rt_cd": "0" if success_orders else "-1",
            "success": success_orders,
            "failed": failed_orders,
            "total_sell_amount": total_sell_amount,
            "total_profit": total_profit,
            "total_return_rate": total_return_rate
        }
        
    except Exception as e:
        print(f"❌ 바스켓 매도 중 오류 발생: {e}")
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
    계좌의 모든 보유 종목을 전량 매도하는 함수
    
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
    print(f"🧹 보유 종목 전량 매도 시작")
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
            return {"rt_cd": "0", "msg1": "매도 가능 종목 없음"}
        
        print(f"\n📋 매도 예정 종목: 총 {len(sellable_stocks)}개")
        for i, stock in enumerate(sellable_stocks, 1):
            print(f"   [{i:2d}] {stock['name']:15s} ({stock['code']}): "
                  f"{stock['sellable_qty']:,}주 (현재가: {stock['current_price']:,}원)")
        print(f"{'='*80}\n")
        
        # 3. 각 종목 순차적으로 매도
        success_orders = []
        failed_orders = []
        total_sell_amount = 0
        
        for idx, stock in enumerate(sellable_stocks, 1):
            stock_code = stock["code"]
            stock_name = stock["name"]
            quantity = stock["sellable_qty"]
            
            print(f"\n[{idx}/{len(sellable_stocks)}] {stock_name} ({stock_code}) {quantity}주 매도 중...")
            
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
                        print(f"   ✅ 주문 접수 성공 (주문번호: {order_no})")
                        
                        # 체결 확인
                        check_tr_id = "VTTC8001R" if "VTT" in tr_id else "TTTC8001R"
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
                                sell_amount = filled_price * filled_qty
                                total_sell_amount += sell_amount
                                
                                success_orders.append({
                                    "code": stock_code,
                                    "name": stock_name,
                                    "order_no": order_no,
                                    "quantity": filled_qty,
                                    "price": filled_price,
                                    "amount": sell_amount
                                })
                                
                                print(f"   💰 체결 완료: {filled_price:,}원 x {filled_qty}주 = {sell_amount:,}원")
                            else:
                                print(f"   ⚠️  체결가 조회 실패")
                                failed_orders.append({
                                    "code": stock_code,
                                    "name": stock_name,
                                    "reason": "체결가 조회 실패"
                                })
                        else:
                            print(f"   ⚠️  체결 확인 실패")
                            failed_orders.append({
                                "code": stock_code,
                                "name": stock_name,
                                "reason": "체결 확인 타임아웃"
                            })
                    else:
                        print(f"   ❌ 주문 실패: {result.get('msg1')}")
                        failed_orders.append({
                            "code": stock_code,
                            "name": stock_name,
                            "reason": result.get('msg1', '알 수 없는 오류')
                        })
                else:
                    print(f"   ❌ API 호출 실패: {sell_response.status_code}")
                    failed_orders.append({
                        "code": stock_code,
                        "name": stock_name,
                        "reason": f"API 호출 실패: {sell_response.status_code}"
                    })
                
                # 다음 주문 전 대기
                time.sleep(0.5)
                
            except Exception as e:
                print(f"   ❌ 오류 발생: {e}")
                failed_orders.append({
                    "code": stock_code,
                    "name": stock_name,
                    "reason": str(e)
                })
        
        # 4. 최종 결과 출력
        print(f"\n{'='*80}")
        print(f"🎯 전량 매도 완료")
        print(f"{'='*80}")
        print(f"✅ 성공: {len(success_orders)}/{len(sellable_stocks)}개 종목")
        print(f"❌ 실패: {len(failed_orders)}/{len(sellable_stocks)}개 종목")
        print(f"💰 총 매도 금액: {total_sell_amount:,}원")
        
        if failed_orders:
            print(f"\n⚠️  실패한 종목:")
            for order in failed_orders:
                print(f"   - {order['name']} ({order['code']}): {order['reason']}")
        
        if success_orders:
            print(f"\n📋 매도 완료 종목:")
            for order in success_orders:
                print(f"   {order['name']:15s}: {order['quantity']:,}주 x {order['price']:,}원 = {order['amount']:,}원")
        
        print(f"{'='*80}\n")
        
        # 5. 포지션 초기화 (전량 청산이므로)
        current_position["type"] = None
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
        print(f"❌ 전량 매도 중 오류 발생: {e}")
        import traceback
        traceback.print_exc()
        return {"rt_cd": "-1", "msg1": str(e)}
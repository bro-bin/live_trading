import requests
import json
import time
from GetBasketQty import get_optimal_basket, initialize_websocket, close_websocket

def get_hashkey(data, base_url, app_key, app_secret):
    """POST 요청시 필요한 해시키 생성"""
    url = f"{base_url}/uapi/hashkey"
    headers = {
        "content-type": "application/json",
        "appkey": app_key,
        "appsecret": app_secret,
    }
    response = requests.post(url, headers=headers, data=json.dumps(data))
    if response.status_code == 200:
        return response.json().get("HASH")
    else:
        print(f"❌ 해시키 생성 실패: {response.text}")
        return None

# --------------------------------------------------------------
def buy_etf(access_token, base_url, app_key, app_secret, account_no, stock_code, quantity, stock_name, tr_id="VTTC0802U"):
    """시장가 매수 주문 (모듈화된 함수)"""
    print(f"\n>>>> 🛒 {stock_name} {quantity}주 시장가 매수 주문 실행!")
    path = "/uapi/domestic-stock/v1/trading/order-cash"
    url = f"{base_url}{path}"

    try:
        cano, acnt_prdt_cd = account_no.split('-')
    except Exception:
        print("❌ ACCOUNT_NO 포맷 오류 (예: '50154524-01')")
        return None

    data = {
        "CANO": cano,
        "ACNT_PRDT_CD": acnt_prdt_cd,
        "PDNO": stock_code,
        "ORD_DVSN": "01",  # 01: 시장가
        "ORD_QTY": str(quantity),
        "ORD_UNPR": "0",
    }

    hashkey = get_hashkey(data, base_url, app_key, app_secret)
    if not hashkey:
        return None

    headers = {
        "content-type": "application/json",
        "authorization": f"Bearer {access_token}",
        "appkey": app_key,
        "appsecret": app_secret,
        "tr_id": tr_id,
        "custtype": "P",
        "hashkey": hashkey
    }

    response = requests.post(url, headers=headers, data=json.dumps(data))
    if response.status_code == 200:
        result = response.json()
        if result.get("rt_cd") == "0":
            odno = result.get("output", {}).get("ODNO")
            print(f"✅ 매수 주문 성공! (주문번호: {odno})")
        else:
            print(f"❌ 매수 주문 실패: {result.get('msg1')}")
        return result
    else:
        print(f"❌ 매수 API 호출 실패: {response.text}")
        return None

# --------------------------------------------------------------
def sell_etf(access_token, base_url, app_key, app_secret, account_no, stock_code, quantity, stock_name, tr_id="VTTC0801U"):
    """시장가 매도 주문 (모듈화된 함수)"""
    print(f"\n>>>> 💰 {stock_name} {quantity}주 시장가 매도 주문 실행!")
    path = "/uapi/domestic-stock/v1/trading/order-cash"
    url = f"{base_url}{path}"

    try:
        cano, acnt_prdt_cd = account_no.split('-')
    except Exception:
        print("❌ ACCOUNT_NO 포맷 오류 (예: '50154524-01')")
        return None

    data = {
        "CANO": cano,
        "ACNT_PRDT_CD": acnt_prdt_cd,
        "PDNO": stock_code,
        "ORD_DVSN": "01",  # 01: 시장가
        "ORD_QTY": str(quantity),
        "ORD_UNPR": "0",
    }

    hashkey = get_hashkey(data, base_url, app_key, app_secret)
    if not hashkey:
        return None

    headers = {
        "content-type": "application/json",
        "authorization": f"Bearer {access_token}",
        "appkey": app_key,
        "appsecret": app_secret,
        "tr_id": tr_id,
        "custtype": "P",
        "hashkey": hashkey
    }

    response = requests.post(url, headers=headers, data=json.dumps(data))
    if response.status_code == 200:
        result = response.json()
        if result.get("rt_cd") == "0":
            odno = result.get("output", {}).get("ODNO")
            print(f"✅ 매도 주문 성공! (주문번호: {odno})")
        else:
            print(f"❌ 매도 주문 실패: {result.get('msg1')}")
        return result
    else:
        print(f"❌ 매도 API 호출 실패: {response.text}")
        return None

# --------------------------------------------------------------
def buy_basket(access_token, base_url, app_key, app_secret, account_no, tr_id="VTTC0802U", tolerance=1.0, delay=0.5, auto_close_websocket=True):
    """
    최적 바스켓 구성에 따라 여러 종목을 일괄 매수하는 함수
    내부에서 웹소켓 연결 및 get_optimal_basket()을 실행하여 실시간 가격 기반으로 최적 수량을 계산
    
    Args:
        access_token (str): 액세스 토큰
        base_url (str): API 기본 URL
        app_key (str): APP KEY
        app_secret (str): APP SECRET
        account_no (str): 계좌번호 (예: '50154524-01')
        tr_id (str): 거래ID (모의투자: 'VTTC0802U', 실전투자: 'TTTC0802U')
        tolerance (float): 허용 오차 (기본값 1.0%)
        delay (float): 각 주문 사이의 대기 시간 (초, 기본값 0.5초)
        auto_close_websocket (bool): 함수 종료 시 웹소켓 자동 종료 여부 (기본값 True)
    
    Returns:
        dict: 각 종목별 주문 결과 요약
    """
    # 종목명 -> 종목코드 매핑
    STOCK_CODE_MAP = {
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
    
    print("=" * 80)
    print("🎯 바스켓 일괄 매수 시작")
    print("=" * 80)
    
    # 1. 웹소켓 연결 (실시간 가격 수신)
    print("\n📡 웹소켓 연결 중...")
    try:
        is_real = "vts" not in base_url.lower()  # URL로 실전/모의 판단
        initialize_websocket(app_key, app_secret, is_real)
        print("✅ 웹소켓 연결 완료")
    except Exception as e:
        print(f"❌ 웹소켓 연결 실패: {e}")
        return None
    
    # 2. 실시간 가격 기반 최적 바스켓 계산
    print("\n📊 실시간 최적 바스켓 계산 중...")
    try:
        basket_dict = get_optimal_basket(tolerance=tolerance)
        print(f"✅ 최적 바스켓 계산 완료: {len(basket_dict)}개 종목")
        print("\n📦 계산된 바스켓 구성:")
        for stock_name, quantity in basket_dict.items():
            print(f"   - {stock_name}: {quantity}주")
    except Exception as e:
        print(f"❌ 최적 바스켓 계산 실패: {e}")
        if auto_close_websocket:
            close_websocket()
        return None
    
    # 결과 저장
    results = {
        "success": [],
        "failed": [],
        "total_stocks": len(basket_dict),
        "total_quantity": sum(basket_dict.values())
    }
    
    # 각 종목별 매수 실행
    for idx, (stock_name, quantity) in enumerate(basket_dict.items(), 1):
        print(f"\n[{idx}/{len(basket_dict)}] {stock_name} 매수 진행 중...")
        
        # 종목코드 확인
        stock_code = STOCK_CODE_MAP.get(stock_name)
        if not stock_code:
            print(f"❌ {stock_name}의 종목코드를 찾을 수 없습니다.")
            results["failed"].append({
                "stock_name": stock_name,
                "quantity": quantity,
                "reason": "종목코드 미등록"
            })
            continue
        
        # 매수 주문 실행
        result = buy_etf(
            access_token=access_token,
            base_url=base_url,
            app_key=app_key,
            app_secret=app_secret,
            account_no=account_no,
            stock_code=stock_code,
            quantity=quantity,
            stock_name=stock_name,
            tr_id=tr_id
        )
        
        # 결과 저장
        if result and result.get("rt_cd") == "0":
            results["success"].append({
                "stock_name": stock_name,
                "stock_code": stock_code,
                "quantity": quantity,
                "order_no": result.get("output", {}).get("ODNO")
            })
        else:
            results["failed"].append({
                "stock_name": stock_name,
                "stock_code": stock_code,
                "quantity": quantity,
                "reason": result.get("msg1") if result else "API 호출 실패"
            })
        
        # API 호출 제한을 고려한 대기 (마지막 주문 후에는 대기하지 않음)
        if idx < len(basket_dict):
            time.sleep(delay)
    
    # 최종 결과 출력
    print("\n" + "=" * 80)
    print("📊 바스켓 매수 결과 요약")
    print("=" * 80)
    print(f"✅ 성공: {len(results['success'])}건 / ❌ 실패: {len(results['failed'])}건")
    print(f"📦 총 종목 수: {results['total_stocks']}개")
    print(f"📈 총 매수 수량: {results['total_quantity']}주")
    
    if results["success"]:
        print("\n✅ 매수 성공 종목:")
        for item in results["success"]:
            print(f"   - {item['stock_name']}: {item['quantity']}주 (주문번호: {item['order_no']})")
    
    if results["failed"]:
        print("\n❌ 매수 실패 종목:")
        for item in results["failed"]:
            print(f"   - {item['stock_name']}: {item['quantity']}주 (사유: {item['reason']})")
    
    print("=" * 80)
    
    # 3. 웹소켓 연결 종료
    if auto_close_websocket:
        print("\n🔌 웹소켓 연결 종료 중...")
        close_websocket()
        print("✅ 웹소켓 종료 완료")
    
    return results
# --------------------------------------------------------------
def sell_basket(access_token, base_url, app_key, app_secret, account_no, tr_id="VTTC0801U", delay=0.5):
    """
    Kodex 삼성그룹 ETF 구성 종목 15개를 모두 매도하는 함수
    현재 계좌에 보유 중인 수량만큼 전량 매도
    
    Args:
        access_token (str): 액세스 토큰
        base_url (str): API 기본 URL
        app_key (str): APP KEY
        app_secret (str): APP SECRET
        account_no (str): 계좌번호 (예: '50154524-01')
        tr_id (str): 거래ID (모의투자: 'VTTC0801U', 실전투자: 'TTTC0801U')
        delay (float): 각 주문 사이의 대기 시간 (초, 기본값 0.5초)
    
    Returns:
        dict: 각 종목별 매도 결과 요약
    """
    # 삼성그룹 ETF 구성 종목 코드 리스트
    SAMSUNG_GROUP_STOCKS = {
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
    
    print("=" * 80)
    print("💰 바스켓 일괄 매도 시작")
    print("=" * 80)
    
    # 1. 현재 보유 잔고 조회
    print("\n📊 보유 잔고 조회 중...")
    try:
        cano, acnt_prdt_cd = account_no.split('-')
    except Exception:
        print("❌ ACCOUNT_NO 포맷 오류 (예: '50154524-01')")
        return None
    
    path = "/uapi/domestic-stock/v1/trading/inquire-balance"
    url = f"{base_url}{path}"
    
    # TR_ID 설정 (모의투자/실전투자)
    balance_tr_id = "VTTC8434R" if tr_id.startswith("VTT") else "TTTC8434R"
    
    headers = {
        "content-type": "application/json",
        "authorization": f"Bearer {access_token}",
        "appkey": app_key,
        "appsecret": app_secret,
        "tr_id": balance_tr_id,
        "custtype": "P",
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
    
    if response.status_code != 200:
        print(f"❌ 잔고 조회 실패: {response.text}")
        return None
    
    balance_data = response.json()
    if balance_data.get("rt_cd") != "0":
        print(f"❌ 잔고 조회 실패: {balance_data.get('msg1')}")
        return None
    
    # 2. 삼성그룹 구성 종목 중 보유 종목 필터링
    holdings = balance_data.get("output1", [])
    stocks_to_sell = {}
    
    for holding in holdings:
        stock_code = holding.get("pdno")
        stock_name = holding.get("prdt_name", "").strip()
        quantity = int(holding.get("hldg_qty", 0))
        
        # 삼성그룹 구성 종목인지 확인
        if stock_code in SAMSUNG_GROUP_STOCKS.values() and quantity > 0:
            # 종목코드로 종목명 찾기
            for name, code in SAMSUNG_GROUP_STOCKS.items():
                if code == stock_code:
                    stocks_to_sell[name] = {
                        "code": stock_code,
                        "quantity": quantity
                    }
                    break
    
    if not stocks_to_sell:
        print("\n⚠️ 매도할 삼성그룹 구성 종목이 없습니다.")
        return {
            "success": [],
            "failed": [],
            "total_stocks": 0,
            "total_quantity": 0
        }
    
    print(f"✅ 매도 대상 종목: {len(stocks_to_sell)}개")
    print("\n📦 매도 예정 종목:")
    for stock_name, info in stocks_to_sell.items():
        print(f"   - {stock_name}: {info['quantity']}주")
    
    # 결과 저장
    results = {
        "success": [],
        "failed": [],
        "total_stocks": len(stocks_to_sell),
        "total_quantity": sum(info["quantity"] for info in stocks_to_sell.values())
    }
    
    # 3. 각 종목별 매도 실행
    print("\n" + "=" * 80)
    for idx, (stock_name, info) in enumerate(stocks_to_sell.items(), 1):
        print(f"\n[{idx}/{len(stocks_to_sell)}] {stock_name} 매도 진행 중...")
        
        stock_code = info["code"]
        quantity = info["quantity"]
        
        # 매도 주문 실행
        result = sell_etf(
            access_token=access_token,
            base_url=base_url,
            app_key=app_key,
            app_secret=app_secret,
            account_no=account_no,
            stock_code=stock_code,
            quantity=quantity,
            stock_name=stock_name,
            tr_id=tr_id
        )
        
        # 결과 저장
        if result and result.get("rt_cd") == "0":
            results["success"].append({
                "stock_name": stock_name,
                "stock_code": stock_code,
                "quantity": quantity,
                "order_no": result.get("output", {}).get("ODNO")
            })
        else:
            results["failed"].append({
                "stock_name": stock_name,
                "stock_code": stock_code,
                "quantity": quantity,
                "reason": result.get("msg1") if result else "API 호출 실패"
            })
        
        # API 호출 제한을 고려한 대기 (마지막 주문 후에는 대기하지 않음)
        if idx < len(stocks_to_sell):
            time.sleep(delay)
    
    # 최종 결과 출력
    print("\n" + "=" * 80)
    print("📊 바스켓 매도 결과 요약")
    print("=" * 80)
    print(f"✅ 성공: {len(results['success'])}건 / ❌ 실패: {len(results['failed'])}건")
    print(f"📦 총 종목 수: {results['total_stocks']}개")
    print(f"📉 총 매도 수량: {results['total_quantity']}주")
    
    if results["success"]:
        print("\n✅ 매도 성공 종목:")
        for item in results["success"]:
            print(f"   - {item['stock_name']}: {item['quantity']}주 (주문번호: {item['order_no']})")
    
    if results["failed"]:
        print("\n❌ 매도 실패 종목:")
        for item in results["failed"]:
            print(f"   - {item['stock_name']}: {item['quantity']}주 (사유: {item['reason']})")
    
    print("=" * 80)
    
    return results

# --------------------------------------------------------------
def all_clear(access_token, base_url, app_key, app_secret, account_no, tr_id="VTTC0801U", delay=0.5):
    """
    보유 중인 모든 주식을 전량 매도하는 함수
    
    Args:
        access_token (str): 액세스 토큰
        base_url (str): API 기본 URL
        app_key (str): APP KEY
        app_secret (str): APP SECRET
        account_no (str): 계좌번호 (예: '50154524-01')
        tr_id (str): 거래ID (모의투자: 'VTTC0801U', 실전투자: 'TTTC0801U')
        delay (float): 각 주문 사이의 대기 시간 (초, 기본값 0.5초)
    
    Returns:
        dict: 각 종목별 매도 결과 요약
    """
    print("=" * 80)
    print("🧹 전체 보유 종목 일괄 매도 (ALL CLEAR)")
    print("=" * 80)
    
    # 1. 현재 보유 잔고 조회
    print("\n📊 보유 잔고 조회 중...")
    try:
        cano, acnt_prdt_cd = account_no.split('-')
    except Exception:
        print("❌ ACCOUNT_NO 포맷 오류 (예: '50154524-01')")
        return None
    
    path = "/uapi/domestic-stock/v1/trading/inquire-balance"
    url = f"{base_url}{path}"
    
    # TR_ID 설정 (모의투자/실전투자)
    balance_tr_id = "VTTC8434R" if tr_id.startswith("VTT") else "TTTC8434R"
    
    headers = {
        "content-type": "application/json",
        "authorization": f"Bearer {access_token}",
        "appkey": app_key,
        "appsecret": app_secret,
        "tr_id": balance_tr_id,
        "custtype": "P",
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
    
    if response.status_code != 200:
        print(f"❌ 잔고 조회 실패: {response.text}")
        return None
    
    balance_data = response.json()
    if balance_data.get("rt_cd") != "0":
        print(f"❌ 잔고 조회 실패: {balance_data.get('msg1')}")
        return None
    
    # 2. 보유 종목 중 수량이 0보다 큰 것만 필터링
    holdings = balance_data.get("output1", [])
    stocks_to_sell = []
    
    for holding in holdings:
        stock_code = holding.get("pdno")
        stock_name = holding.get("prdt_name", "").strip()
        quantity = int(holding.get("hldg_qty", 0))
        
        if quantity > 0:
            stocks_to_sell.append({
                "stock_name": stock_name,
                "stock_code": stock_code,
                "quantity": quantity
            })
    
    if not stocks_to_sell:
        print("\n⚠️ 매도할 보유 종목이 없습니다.")
        return {
            "success": [],
            "failed": [],
            "total_stocks": 0,
            "total_quantity": 0
        }
    
    print(f"✅ 매도 대상 종목: {len(stocks_to_sell)}개")
    print("\n📦 매도 예정 종목:")
    total_quantity = sum(stock["quantity"] for stock in stocks_to_sell)
    for stock in stocks_to_sell:
        print(f"   - {stock['stock_name']}: {stock['quantity']}주")
    print(f"\n📊 총 매도 수량: {total_quantity}주")
    
    # 사용자 확인 메시지
    print("\n⚠️  주의: 보유 중인 모든 종목을 매도합니다!")
    
    # 결과 저장
    results = {
        "success": [],
        "failed": [],
        "total_stocks": len(stocks_to_sell),
        "total_quantity": total_quantity
    }
    
    # 3. 각 종목별 매도 실행
    print("\n" + "=" * 80)
    for idx, stock in enumerate(stocks_to_sell, 1):
        print(f"\n[{idx}/{len(stocks_to_sell)}] {stock['stock_name']} 매도 진행 중...")
        
        # 매도 주문 실행
        result = sell_etf(
            access_token=access_token,
            base_url=base_url,
            app_key=app_key,
            app_secret=app_secret,
            account_no=account_no,
            stock_code=stock["stock_code"],
            quantity=stock["quantity"],
            stock_name=stock["stock_name"],
            tr_id=tr_id
        )
        
        # 결과 저장
        if result and result.get("rt_cd") == "0":
            results["success"].append({
                "stock_name": stock["stock_name"],
                "stock_code": stock["stock_code"],
                "quantity": stock["quantity"],
                "order_no": result.get("output", {}).get("ODNO")
            })
        else:
            results["failed"].append({
                "stock_name": stock["stock_name"],
                "stock_code": stock["stock_code"],
                "quantity": stock["quantity"],
                "reason": result.get("msg1") if result else "API 호출 실패"
            })
        
        # API 호출 제한을 고려한 대기 (마지막 주문 후에는 대기하지 않음)
        if idx < len(stocks_to_sell):
            time.sleep(delay)
    
    # 최종 결과 출력
    print("\n" + "=" * 80)
    print("📊 전체 매도 결과 요약")
    print("=" * 80)
    print(f"✅ 성공: {len(results['success'])}건 / ❌ 실패: {len(results['failed'])}건")
    print(f"📦 총 종목 수: {results['total_stocks']}개")
    print(f"📉 총 매도 수량: {results['total_quantity']}주")
    
    if results["success"]:
        print("\n✅ 매도 성공 종목:")
        for item in results["success"]:
            print(f"   - {item['stock_name']}: {item['quantity']}주 (주문번호: {item['order_no']})")
    
    if results["failed"]:
        print("\n❌ 매도 실패 종목:")
        for item in results["failed"]:
            print(f"   - {item['stock_name']}: {item['quantity']}주 (사유: {item['reason']})")
    
    if len(results["success"]) == results["total_stocks"]:
        print("\n🎉 모든 보유 종목 매도 완료!")
    
    print("=" * 80)
    
    return results
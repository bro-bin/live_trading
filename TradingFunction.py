import requests
import json
import time

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
def buy_basket(access_token, base_url, app_key, app_secret, account_no, 
               current_prices_dict, tr_id="VTTC0802U", delay=0.5):
    
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
def calculate_basket_from_prices(live_prices: dict):
    """
    실시간 가격을 받아서 바스켓 구성을 계산하는 함수
    (웹소켓 연결 없이 가격 데이터만으로 계산)
    """
    ETF_COMPOSITION = {
        "삼성전자": {"quantity": 3845, "code": "005930"}, 
        "삼성바이오로직스": {"quantity": 119, "code": "207940"},
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
    
    # 1. 전체 시가총액 계산
    total_market_cap = 0
    stock_info = {}
    
    for stock_name, comp_info in ETF_COMPOSITION.items():
        if stock_name not in live_prices:
            raise Exception(f"{stock_name}의 가격 정보가 없습니다.")
        
        price = live_prices[stock_name]
        quantity = comp_info["quantity"]
        market_cap = price * quantity
        total_market_cap += market_cap
        
        stock_info[stock_name] = {
            "code": comp_info["code"],
            "price": price,
            "target_weight": (market_cap / total_market_cap * 100) if total_market_cap > 0 else 0
        }
    
    # 비중 재계산 (total_market_cap 확정 후)
    for stock_name in stock_info:
        market_cap = stock_info[stock_name]["price"] * ETF_COMPOSITION[stock_name]["quantity"]
        stock_info[stock_name]["target_weight"] = (market_cap / total_market_cap * 100)
    
    # 2. 삼성카드 4주 기준으로 전체 포트폴리오 계산
    samsung_card_info = stock_info["삼성카드"]
    samsung_card_quantity = 4
    samsung_card_cost = samsung_card_info["price"] * samsung_card_quantity
    total_portfolio_value = samsung_card_cost / (samsung_card_info["target_weight"] / 100)
    
    # 3. 각 종목별 수량 계산
    basket_dict = {}
    for stock_name, info in stock_info.items():
        if stock_name == "삼성카드":
            basket_dict[stock_name] = samsung_card_quantity
        else:
            target_investment = total_portfolio_value * (info["target_weight"] / 100)
            quantity = max(1, round(target_investment / info["price"]))
            basket_dict[stock_name] = quantity
    
    return basket_dict

# --------------------------------------------------------------
def buy_basket(access_token, base_url, app_key, app_secret, account_no, 
               current_prices_dict, tr_id="VTTC0802U", delay=0.5):
    """
    실시간 가격을 받아서 최적 바스켓을 매수하는 함수
    (웹소켓 재연결 없이 외부에서 받은 가격 사용)
    
    Args:
        current_prices_dict (dict): {종목명: 가격} 형태의 딕셔너리
                                    예: {"삼성전자": 50000, "삼성SDI": 300000, ...}
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
    
    # 1. 외부에서 받은 실시간 가격으로 최적 바스켓 계산
    print("\n📊 실시간 가격 기반 최적 바스켓 계산 중...")
    try:
        basket_dict = calculate_basket_from_prices(current_prices_dict)
        print(f"✅ 최적 바스켓 계산 완료: {len(basket_dict)}개 종목")
        print("\n📦 계산된 바스켓 구성:")
        for stock_name, quantity in basket_dict.items():
            print(f"   - {stock_name}: {quantity}주")
    except Exception as e:
        print(f"❌ 최적 바스켓 계산 실패: {e}")
        return None
    
    # 결과 저장
    results = {
        "success": [],
        "failed": [],
        "total_stocks": len(basket_dict),
        "total_quantity": sum(basket_dict.values())
    }
    
    # 2. 각 종목별 매수 실행
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
        
        # API 호출 제한을 고려한 대기
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
    
    return results

# --------------------------------------------------------------
def sell_basket(access_token, base_url, app_key, app_secret, account_no, tr_id="VTTC0801U", delay=0.5):
    """
    Kodex 삼성그룹 ETF 구성 종목 15개를 모두 매도하는 함수
    현재 계좌에 보유 중인 수량만큼 전량 매도
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
        
        # API 호출 제한을 고려한 대기
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
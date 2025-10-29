import yaml
import requests
import json
import time
from datetime import datetime
from TradingFunction import all_clear

# ==============================================================================
# ========== 설정 불러오기 (Configuration) ==========
# ==============================================================================
def get_access_token(base_url, app_key, app_secret):
    """OAuth 인증을 통해 접근 토큰을 발급받습니다."""
    url = f"{base_url}/oauth2/tokenP"
    headers = {"content-type": "application/json"}
    data = {
        "grant_type": "client_credentials",
        "appkey": app_key,
        "appsecret": app_secret
    }
    response = requests.post(url, headers=headers, data=json.dumps(data))
    if response.status_code == 200:
        access_token = response.json()["access_token"]
        print("✅ 접근 토큰 발급 성공")
        return access_token
    else:
        print(f"❌ 접근 토큰 발급 실패: {response.text}")
        return None


def check_balance(access_token, base_url, app_key, app_secret, account_no, is_real):
    """현재 보유 잔고를 조회하여 보유 수량을 확인합니다."""
    try:
        cano, acnt_prdt_cd = account_no.split('-')
    except Exception:
        print("❌ ACCOUNT_NO 포맷 오류")
        return None
    
    path = "/uapi/domestic-stock/v1/trading/inquire-balance"
    url = f"{base_url}{path}"
    
    # TR_ID 설정 (모의투자/실전투자)
    tr_id = "VTTC8434R" if not is_real else "TTTC8434R"
    
    headers = {
        "content-type": "application/json",
        "authorization": f"Bearer {access_token}",
        "appkey": app_key,
        "appsecret": app_secret,
        "tr_id": tr_id,
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
        return None
    
    balance_data = response.json()
    if balance_data.get("rt_cd") != "0":
        return None
    
    # 보유 종목 중 수량이 0보다 큰 것만 반환
    holdings = balance_data.get("output1", [])
    holding_stocks = []
    
    for holding in holdings:
        stock_code = holding.get("pdno")
        stock_name = holding.get("prdt_name", "").strip()
        quantity = int(holding.get("hldg_qty", 0))
        
        if quantity > 0:
            holding_stocks.append({
                "stock_name": stock_name,
                "stock_code": stock_code,
                "quantity": quantity
            })
    
    return holding_stocks


def wait_for_settlement(access_token, base_url, app_key, app_secret, account_no, is_real, 
                        check_interval=5, max_wait_time=300):
    """
    매도 체결이 완료될 때까지 대기하는 함수
    
    Args:
        access_token: API 액세스 토큰
        base_url: API 기본 URL
        app_key: APP KEY
        app_secret: APP SECRET
        account_no: 계좌번호
        is_real: 실전투자 여부
        check_interval: 잔고 확인 주기 (초, 기본값 5초)
        max_wait_time: 최대 대기 시간 (초, 기본값 300초=5분)
    
    Returns:
        bool: 모든 종목 체결 완료 시 True, 타임아웃 시 False
    """
    print("\n" + "=" * 80)
    print("⏳ 매도 체결 대기 중...")
    print("=" * 80)
    
    start_time = time.time()
    check_count = 0
    
    while True:
        check_count += 1
        elapsed_time = time.time() - start_time
        
        # 타임아웃 체크
        if elapsed_time > max_wait_time:
            print(f"\n⚠️  최대 대기 시간({max_wait_time}초) 초과")
            return False
        
        # 현재 시간 출력
        current_time = datetime.now().strftime("%H:%M:%S")
        print(f"\n[{current_time}] 체크 #{check_count} - 경과 시간: {int(elapsed_time)}초")
        
        # 잔고 조회
        holdings = check_balance(access_token, base_url, app_key, app_secret, account_no, is_real)
        
        if holdings is None:
            print("⚠️  잔고 조회 실패, 재시도 중...")
            time.sleep(check_interval)
            continue
        
        # 보유 종목이 없으면 체결 완료
        if len(holdings) == 0:
            print("\n✅ 모든 보유 종목 매도 체결 완료!")
            return True
        
        # 아직 보유 중인 종목 출력
        print(f"📊 현재 보유 종목: {len(holdings)}개")
        for stock in holdings:
            print(f"   - {stock['stock_name']}: {stock['quantity']}주")
        
        print(f"⏳ {check_interval}초 후 다시 확인...")
        time.sleep(check_interval)


# ==============================================================================
# ========== 메인 프로그램 실행 (Main Execution) ==========
# ==============================================================================
if __name__ == "__main__":
    print("=" * 80)
    print("=== 전체 보유 종목 일괄 매도 프로그램 ===")
    print("=" * 80)
    
    # 1. config.yaml에서 설정 정보 로드
    try:
        with open('config.yaml', encoding='UTF-8') as f:
            _cfg = yaml.load(f, Loader=yaml.FullLoader)
        
        APP_KEY = _cfg['APP_KEY']
        APP_SECRET = _cfg['APP_SECRET']
        ACCOUNT_NO = _cfg['ACCOUNT_NO']
        BASE_URL = _cfg['URL_BASE']
        
        # 실전/모의 판단
        IS_REAL = "vts" not in BASE_URL.lower()
        print(f"=== 실행 환경: {'실전투자' if IS_REAL else '모의투자'} ===")
        print("=" * 80)
        
    except Exception as e:
        print(f"❌ 설정 파일 로드 실패: {e}")
        exit(1)
    
    # 2. API 접근 토큰 발급
    print("\n🔐 접근 토큰 발급 중...")
    access_token = get_access_token(BASE_URL, APP_KEY, APP_SECRET)
    if not access_token:
        print("❌ 토큰 발급 실패로 프로그램을 종료합니다.")
        exit(1)
    
    # 3. TR_ID 설정 (모의투자/실전투자)
    tr_id = "VTTC0801U" if not IS_REAL else "TTTC0801U"
    
    # 4. 사용자 확인
    print("\n⚠️  경고: 보유 중인 모든 종목을 매도합니다!")
    user_input = input("계속 진행하시겠습니까? (yes/no): ").strip().lower()
    
    if user_input != "yes":
        print("\n❌ 사용자가 취소했습니다. 프로그램을 종료합니다.")
        exit(0)
    
    # 5. 전체 보유 종목 매도 실행
    print("\n🚀 전체 매도 시작...\n")
    result = all_clear(
        access_token=access_token,
        base_url=BASE_URL,
        app_key=APP_KEY,
        app_secret=APP_SECRET,
        account_no=ACCOUNT_NO,
        tr_id=tr_id,
        delay=0.5
    )
    
    # 6. 매도 주문 결과 확인
    if not result:
        print("\n❌ 매도 프로세스 실행 중 오류가 발생했습니다.")
        exit(1)
    
    if result["total_stocks"] == 0:
        print("\nℹ️  매도할 보유 종목이 없습니다.")
        print("\n프로그램을 종료합니다.")
        exit(0)
    
    if len(result["success"]) == 0:
        print("\n❌ 모든 매도 주문이 실패했습니다.")
        exit(1)
    
    # 7. 매도 체결 완료 대기
    print(f"\n📝 매도 주문 제출 완료: {len(result['success'])}건")
    print("💡 이제 체결이 완료될 때까지 대기합니다...")
    
    settlement_success = wait_for_settlement(
        access_token=access_token,
        base_url=BASE_URL,
        app_key=APP_KEY,
        app_secret=APP_SECRET,
        account_no=ACCOUNT_NO,
        is_real=IS_REAL,
        check_interval=5,      # 5초마다 확인
        max_wait_time=300      # 최대 5분 대기
    )
    
    # 8. 최종 결과 출력
    print("\n" + "=" * 80)
    print("🎯 프로그램 실행 완료")
    print("=" * 80)
    
    if settlement_success:
        print("✅ 모든 보유 종목 매도 체결 완료!")
        print("🎉 계좌가 성공적으로 청산되었습니다.")
    else:
        print("⚠️  일부 종목의 체결이 지연되고 있습니다.")
        print("💡 HTS/MTS에서 미체결 내역을 확인해주세요.")
    
    print("\n프로그램을 종료합니다.")
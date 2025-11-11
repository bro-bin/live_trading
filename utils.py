# utils.py 전체 수정

import pandas as pd
from typing import Dict

# 종목 코드 <-> 종목명 매핑
SAMSUNG_STOCKS = {
    "028050": "삼성E&A",
    "006400": "삼성SDI",
    "028260": "삼성물산",
    "032830": "삼성생명",
    "018260": "삼성에스디에스",
    "009150": "삼성전기",
    "005930": "삼성전자",
    "010140": "삼성중공업",
    "016360": "삼성증권",
    "029780": "삼성카드",
    "000810": "삼성화재",
    "012750": "에스원",
    "030000": "제일기획",
    "008770": "호텔신라"
}

# 역매핑 (종목명 -> 종목코드)
STOCK_NAME_TO_CODE = {name: code for code, name in SAMSUNG_STOCKS.items()}

# KODEX 삼성그룹 ETF 원본 구성 (2025년 기준)
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


def get_basket_qty(live_prices: dict, tolerance: float = 1.0) -> dict:
    """
    실시간 가격 기반으로 최적 바스켓 수량 계산
    삼성카드 4주를 기준으로 ETF 구성 비중에 맞춰 각 종목 수량 산출
    
    Args:
        live_prices: {종목명: {"price": 가격, "code": 종목코드}} 형태의 실시간 가격 딕셔너리
        tolerance: 허용 오차 (기본값 1.0%, 현재는 사용하지 않음)
    
    Returns:
        dict: {종목코드: 수량} 형태의 딕셔너리
    
    Raises:
        ValueError: 필수 종목 가격 데이터가 없거나, 가격이 0이거나, 삼성카드 비중이 0인 경우
    """
    
    # 1단계: 실시간 가격으로 ETF 원본 구성의 시가총액 및 비중 계산
    data = []
    total_market_cap = 0
    
    for stock_name, comp_info in ETF_COMPOSITION.items():
        # ✅ 추가: 종목 가격 데이터 유효성 검증
        if stock_name not in live_prices:
            raise ValueError(f"'{stock_name}' 종목의 실시간 가격 데이터가 없습니다.")
        
        price_info = live_prices[stock_name]
        price = price_info["price"]
        code = price_info["code"]
        
        # ✅ 추가: 가격 0 검증
        if price is None or price <= 0:
            raise ValueError(f"'{stock_name}' 종목의 가격이 유효하지 않습니다. (가격: {price})")
        
        quantity = comp_info["quantity"]
        market_cap = price * quantity
        total_market_cap += market_cap
        
        data.append({
            '종목명': stock_name,
            '종목코드': code,
            '가격': price,
            '수량': quantity,
            '시가총액': market_cap
        })
    
    df = pd.DataFrame(data)
    df['비중(%)'] = (df['시가총액'] / total_market_cap * 100).round(2)
    
    # 2단계: 삼성카드 4주 기준으로 전체 포트폴리오 규모 역산
    # ✅ 개선: 삼성카드 데이터 누락 체크
    samsung_card_rows = df[df['종목명'] == '삼성카드']
    if samsung_card_rows.empty:
        raise ValueError("삼성카드 데이터가 DataFrame에 없습니다.")
    
    samsung_card_row = samsung_card_rows.iloc[0]
    samsung_card_weight = samsung_card_row['비중(%)']
    samsung_card_price = samsung_card_row['가격']
    samsung_card_quantity = 4  # 기준 수량 고정
    
    if samsung_card_weight == 0:
        raise ValueError("삼성카드의 비중이 0입니다. 계산 불가.")
    
    # 삼성카드 4주의 비용으로 전체 포트폴리오 목표 금액 계산
    samsung_card_cost = samsung_card_price * samsung_card_quantity
    total_portfolio_value = samsung_card_cost / (samsung_card_weight / 100)
    
    # 3단계: 각 종목별 수량 계산
    basket_dict = {}
    
    for _, row in df.iterrows():
        stock_name = row['종목명']
        stock_code = row['종목코드']
        target_weight = row['비중(%)']
        stock_price = row['가격']
        
        if stock_name == '삼성카드':
            quantity = samsung_card_quantity
        else:
            # 목표 투자 금액 = 전체 포트폴리오 가치 * 목표 비중
            target_investment = total_portfolio_value * (target_weight / 100)
            # 수량 = 목표 투자 금액 / 주가 (소수점 반올림, 최소 1주)
            quantity = max(1, round(target_investment / stock_price))
        
        basket_dict[stock_code] = quantity
    
    return basket_dict
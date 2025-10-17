sample_price = {
        "삼성전자": {"price": 95000, "code": "005930"},
        "삼성바이오로직스": {"price": 1127000, "code": "207940"},
        "삼성물산": {"price": 206000, "code": "028260"},
        "삼성화재": {"price": 447500, "code": "000810"},
        "삼성중공업": {"price": 21550, "code": "010140"},
        "삼성생명": {"price": 162200, "code": "032830"},
        "삼성SDI": {"price": 221500, "code": "006400"},
        "삼성전기": {"price": 200000, "code": "009150"},
        "삼성에스디에스": {"price": 165100, "code": "018260"},
        "삼성증권": {"price": 74900, "code": "016360"},
        "삼성E&A": {"price": 28300, "code": "028050"},
        "에스원": {"price": 76500, "code": "012750"},
        "호텔신라": {"price": 49800, "code": "008770"},
        "제일기획": {"price": 20200, "code": "030000"},
        "삼성카드": {"price": 49300, "code": "029780"}
    }

def calculate_total_market_cap():
    """각 종목의 price와 quantity를 곱한 시가총액의 합을 계산하는 함수"""
    import pandas as pd
    
    # ETF 구성 종목 및 수량
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
    
    # 데이터 저장용 리스트
    data = []
    total_market_cap = 0
    
    # 각 종목별 시가총액 계산
    for stock_name in ETF_COMPOSITION:
        if stock_name in sample_price:
            price = sample_price[stock_name]["price"]
            quantity = ETF_COMPOSITION[stock_name]["quantity"]
            market_cap = price * quantity
            total_market_cap += market_cap
            
            data.append({
                '종목명': stock_name,
                '종목코드': ETF_COMPOSITION[stock_name]["code"],
                '가격': price,
                '수량': quantity,
                '시가총액': market_cap
            })
    
    # DataFrame 생성
    df = pd.DataFrame(data)
    
    # 비중 계산 (백분율)
    df['비중(%)'] = (df['시가총액'] / total_market_cap * 100).round(2)
    
    # 컬럼 순서 재정렬
    df = df[['종목명', '종목코드', '가격', '수량', '시가총액', '비중(%)']]
    
    return df, total_market_cap

def make_basket() :
    
    df, total_market_cap = calculate_total_market_cap()
    
    print("=== ETF 구성 종목별 시가총액 및 비중 ===")
    print(df.to_string(index=False))
    print(f"\n총 시가총액: {total_market_cap:,}원")
    
    return df, total_market_cap

def create_minimum_cost_portfolio(target_df, tolerance=1.0):
    """
    삼성카드를 기준으로 역산하여 최소 비용 포트폴리오를 생성
    
    Args:
        target_df: 목표 비중이 포함된 DataFrame
        tolerance: 허용 오차 범위 (%)
    
    Returns:
        최적 포트폴리오 DataFrame, 총 비용
    """
    import pandas as pd
    import math
    
    print("🔍 삼성카드 기준 역산 방식으로 최적화 시도")
    print("="*70)
    
    # 삼성카드 정보 찾기
    samsung_card_row = target_df[target_df['종목명'] == '삼성카드'].iloc[0]
    samsung_card_weight = samsung_card_row['비중(%)']
    samsung_card_price = samsung_card_row['가격']
    
    print(f"기준 종목: 삼성카드 (목표 비중: {samsung_card_weight:.2f}%, 가격: {samsung_card_price:,}원)")
    
    best_portfolio = None
    best_cost = float('inf')
    best_error = float('inf')
    
    # 삼성카드를 1개부터 시작해서 최적해 찾기
    for samsung_card_quantity in range(1, 21):  # 1~20개까지 시도
        samsung_card_cost = samsung_card_price * samsung_card_quantity
        
        # 전체 포트폴리오 시가총액 역산
        total_portfolio_value = samsung_card_cost / (samsung_card_weight / 100)
        
        print(f"\n--- 삼성카드 {samsung_card_quantity}개 ({samsung_card_cost:,}원) 기준으로 계산 ---")
        print(f"역산된 전체 포트폴리오 가치: {total_portfolio_value:,.0f}원")
        
        portfolio_data = []
        actual_total_cost = 0
        
        for _, row in target_df.iterrows():
            stock_name = row['종목명']
            target_weight = row['비중(%)']
            stock_price = row['가격']
            stock_code = row['종목코드']
            
            if stock_name == '삼성카드':
                quantity = samsung_card_quantity
                cost = samsung_card_cost
            else:
                # 목표 비중에 따른 투자금액 계산
                target_investment = total_portfolio_value * (target_weight / 100)
                # 필요한 주식 수량 계산
                quantity = max(1, round(target_investment / stock_price))
                cost = stock_price * quantity
            
            actual_total_cost += cost
            
            portfolio_data.append({
                '종목명': stock_name,
                '종목코드': stock_code,
                '가격': stock_price,
                '수량': quantity,
                '투자금액': cost,
                '목표비중(%)': target_weight
            })
        
        # 실제 비중 계산
        portfolio_df = pd.DataFrame(portfolio_data)
        portfolio_df['실제비중(%)'] = (portfolio_df['투자금액'] / actual_total_cost * 100).round(2)
        portfolio_df['오차(%)'] = (portfolio_df['실제비중(%)'] - portfolio_df['목표비중(%)']).round(2)
        portfolio_df['오차절댓값'] = abs(portfolio_df['오차(%)'])
        
        max_error = portfolio_df['오차절댓값'].max()
        avg_error = portfolio_df['오차절댓값'].mean()
        
        print(f"실제 총 투자금액: {actual_total_cost:,}원")
        print(f"최대 오차: {max_error:.2f}%")
        print(f"평균 오차: {avg_error:.2f}%")
        
        # 최적해 업데이트
        if max_error < best_error or (max_error == best_error and actual_total_cost < best_cost):
            best_error = max_error
            best_portfolio = portfolio_df.copy()
            best_cost = actual_total_cost
        
        # 허용 오차 내에 있는지 확인 (모든 종목이 1% 이내여야 함)
        stocks_within_tolerance = portfolio_df[portfolio_df['오차절댓값'] <= tolerance]
        stocks_over_tolerance = portfolio_df[portfolio_df['오차절댓값'] > tolerance]
        
        print(f"허용 오차 {tolerance}% 이내 종목: {len(stocks_within_tolerance)}개")
        print(f"허용 오차 {tolerance}% 초과 종목: {len(stocks_over_tolerance)}개")
        
        if len(stocks_over_tolerance) == 0:
            print(f"✅ 성공! 모든 종목이 허용 오차 {tolerance}% 이내입니다.")
            final_df = portfolio_df[['종목명', '종목코드', '가격', '수량', '투자금액', '목표비중(%)', '실제비중(%)', '오차(%)']]
            return final_df, actual_total_cost
        else:
            # 오차 초과 종목들 출력 (상위 5개까지만)
            top_error_stocks = stocks_over_tolerance.nlargest(5, '오차절댓값')
            print("주요 오차 초과 종목들:")
            for _, stock in top_error_stocks.iterrows():
                print(f"  {stock['종목명']}: 목표 {stock['목표비중(%)']}% vs 실제 {stock['실제비중(%)']}% (오차: {stock['오차(%)']}%)")
    
    # 허용 오차 내 해를 찾지 못한 경우 최선의 결과 반환
    print(f"\n⚠️ 허용 오차 {tolerance}% 내 해를 찾지 못했습니다.")
    print(f"🔶 최선의 결과 (최대 오차 {best_error:.2f}%)")
    
    if best_portfolio is not None:
        final_df = best_portfolio[['종목명', '종목코드', '가격', '수량', '투자금액', '목표비중(%)', '실제비중(%)', '오차(%)']]
        return final_df, best_cost
    
    print("❌ 해를 찾지 못했습니다.")
    return None, 0

if __name__ == "__main__":
    # 함수 실행 및 결과 확인
    print("ETF 바스켓 구성 분석을 시작합니다...\n")
    
    # 원본 ETF 구성 분석
    df, total_cap = make_basket()
    
    print("\n" + "="*70)
    print("삼성카드 기준 역산 방식 최소 비용 포트폴리오 생성")
    print("="*70)
    
    # 삼성카드 기준 역산 방식 최소 비용 포트폴리오 생성
    optimal_portfolio, optimal_cost = create_minimum_cost_portfolio(df, tolerance=1.0)
    
    if optimal_portfolio is not None:
        print("\n" + "="*70)
        print("🎯 최적 포트폴리오 결과")
        print("="*70)
        print(optimal_portfolio.to_string(index=False))
        print(f"\n💰 총 투자 필요 금액: {optimal_cost:,}원")
        print(f"📊 원본 ETF 대비 비용 절감: {total_cap - optimal_cost:,}원 ({((total_cap - optimal_cost) / total_cap * 100):.1f}%)")
        
        # 추가 분석
        print(f"\n📈 포트폴리오 분석:")
        print(f"   • 구성 종목 수: {len(optimal_portfolio)}개")
        print(f"   • 최대 오차: {abs(optimal_portfolio['오차(%)']).max():.2f}%")
        print(f"   • 평균 오차: {abs(optimal_portfolio['오차(%)']).mean():.2f}%")
    else:
        print("❌ 최적 포트폴리오를 찾지 못했습니다.")





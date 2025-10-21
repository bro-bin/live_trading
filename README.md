# live_trading
LiveTrading.py에서 시그널에 따라 매매 실행

매매함수는 TradingFunction.py에 모여있음
 1) buy_etf
 2) sell_etf
 3) buy_basket
 4) sell_basket
 5) all_clear 장마감시 일괄매도

 GetBasketQty는 TradingFunction을 위한 모듈

---------------------------시그널-----------------------------  
시가 - nav > 2 시그마 : 바스켓 매수(ETF가 과평가 구간)  
시가 - nav < -2 시그마 : ETF 매수  

공매도가 안되기 떄문에 하나의 포지션만 매수  
2시그마를 2로 가정/ 평균을 0으로 가정  
-------------------------------------------------------.----

10/21 남은 할 일
1. TradingFunction.py의 buy_basket() 호출시 웹소켓 초기화 하는 현상 발생. 기존 웹소켓으로 연결하게 수정.
2. 장종료시 일괄매도 함수 all_clear()구현

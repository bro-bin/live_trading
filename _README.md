# live_trading
live_trading.py에서 시그널에 따라 매매 실행

매매함수는 trading_function.py에 모여있음
 1) buy_etf
 2) sell_etf
 3) buy_basket
 4) sell_basket

get_rate.py에서 basket 실제 비중 금액까지 도출한 상태인데 웹소켓 이슈로 실제 값은 안나옴

MJ가 해줄일: 거기서 나온 실제 비중금액으로make_basket에서 basket 정수수량까지 도출하면 됨.
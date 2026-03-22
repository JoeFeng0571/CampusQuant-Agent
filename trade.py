from fastapi import FastAPI, HTTPException, Depends, Header
from pydantic import BaseModel
import pymysql
import random
from typing import Optional
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 数据库连接配置 (请修改为你自己的账号密码)
DB_CONFIG = {
    'host': '8.156.85.111',
    'user': 'monijiaoyishuju',
    'password': 'fGNFEYSf66tmTeCD',
    'database': 'monijiaoyishuju',  # 你的数据库名
    'charset': 'utf8mb4',
    'cursorclass': pymysql.cursors.DictCursor
}


class OrderRequest(BaseModel):
    symbol: str
    action: str  # "BUY" or "SELL"
    quantity: int


def get_current_user_email(authorization: Optional[str] = Header(None)):
    # 临时模拟，假设传入的 Bearer token 就是邮箱
    if not authorization:
        raise HTTPException(status_code=401, detail="请先登录")
    return authorization.split(" ")[1]


# 辅助函数：根据股票代码判断是哪个市场
def get_market_type_and_currency_field(symbol: str):
    symbol = symbol.upper()
    if symbol.endswith('.HK'):
        return 'HK', '港股可用资金'
    elif symbol.endswith('.SH') or symbol.endswith('.SZ') or symbol.endswith('.BJ'):
        return 'A', 'A股可用资金'
    else:
        return 'US', '美股可用资金'


@app.post("/api/v1/trade/order")
def place_order(order: OrderRequest, email: str = Depends(get_current_user_email)):
    market_type, currency_field = get_market_type_and_currency_field(order.symbol)

    # 1. 模拟实时成交价 (实际项目中应从第三方行情API获取真实价格)
    base_price = 100.0 if market_type != 'HK' else 50.0
    exec_price = round(base_price + random.uniform(-1, 1), 3)

    # 计算交易费用 (这里用 Python 算一次是为了扣减账户余额，数据库的虚拟列会自动再算一次总金额)
    amount = exec_price * order.quantity
    fee = round(amount * 0.0003, 4)  # 万分之三手续费
    total_cost = amount + fee

    # 连接数据库
    conn = pymysql.connect(**DB_CONFIG)
    try:
        with conn.cursor() as cursor:
            # 开启事务 (非常重要：确保扣钱、更新持仓、写流水要么全部成功，要么全部失败回滚)
            conn.begin()

            # --- 查询当前账户 ---
            cursor.execute("SELECT * FROM `资金账户表` WHERE `邮箱` = %s FOR UPDATE", (email,))
            account = cursor.fetchone()
            if not account:
                raise HTTPException(status_code=400, detail="账户不存在，请先初始化资金账户")

            # 获取当前对应市场的现金余额
            current_cash = account[currency_field]

            # ==========================================
            # 分支一：买入逻辑 (BUY)
            # ==========================================
            if order.action == 'BUY':
                if current_cash < total_cost:
                    raise HTTPException(status_code=400,
                                        detail=f"资金不足，需要 {total_cost:.2f}，当前可用 {current_cash:.2f}")

                # 1. 扣减资金，增加成交笔数
                cursor.execute(f"""
                    UPDATE `资金账户表` 
                    SET `{currency_field}` = `{currency_field}` - %s, `累计成交笔数` = `累计成交笔数` + 1 
                    WHERE `邮箱` = %s
                """, (total_cost, email))

                # 2. 查询是否已经持有该股票
                cursor.execute("SELECT * FROM `持仓记录` WHERE `邮箱` = %s AND `股票和标的代码` = %s",
                               (email, order.symbol))
                position = cursor.fetchone()

                if position:
                    # ✅ 加仓逻辑：计算加权平均价
                    old_qty = position['持有数量']
                    old_avg_cost = position['持仓均价']
                    new_qty = old_qty + order.quantity
                    # 新均价 = (旧数量 * 旧均价 + 本次交易总金额) / 新数量
                    new_avg_cost = ((old_qty * old_avg_cost) + amount) / new_qty

                    cursor.execute("""
                        UPDATE `持仓记录` 
                        SET `持有数量` = %s, `持仓均价` = %s 
                        WHERE `标识` = %s
                    """, (new_qty, new_avg_cost, position['标识']))
                else:
                    # 建仓逻辑：直接插入新记录
                    cursor.execute("""
                        INSERT INTO `持仓记录` (`邮箱`, `股票和标的代码`, `标的名称`, `市场种类`, `持有数量`, `持仓均价`) 
                        VALUES (%s, %s, %s, %s, %s, %s)
                    """, (email, order.symbol, "模拟标的", market_type, order.quantity, exec_price))

            # ==========================================
            # 分支二：卖出逻辑 (SELL)
            # ==========================================
            elif order.action == 'SELL':
                # 1. 检查持仓数量是否足够
                cursor.execute("SELECT * FROM `持仓记录` WHERE `邮箱` = %s AND `股票和标的代码` = %s",
                               (email, order.symbol))
                position = cursor.fetchone()

                if not position or position['持有数量'] < order.quantity:
                    raise HTTPException(status_code=400, detail="持仓不足，无法卖出")

                # 2. 增加资金 (卖出得到钱，扣掉手续费)，增加成交笔数
                net_income = amount - fee
                cursor.execute(f"""
                    UPDATE `资金账户表` 
                    SET `{currency_field}` = `{currency_field}` + %s, `累计成交笔数` = `累计成交笔数` + 1 
                    WHERE `邮箱` = %s
                """, (net_income, email))

                # 3. 减少持仓数量 (卖出不改变持仓均价，只变数量)
                new_qty = position['持有数量'] - order.quantity
                if new_qty > 0:
                    cursor.execute("UPDATE `持仓记录` SET `持有数量` = %s WHERE `标识` = %s",
                                   (new_qty, position['标识']))
                else:
                    cursor.execute("DELETE FROM `持仓记录` WHERE `标识` = %s", (position['标识'],))

            # ==========================================
            # 记录订单流水 (买卖都要执行)
            # ==========================================
            # 💡 注意：跳过了虚拟列 `交易总金额`，只需插入其他字段
            cursor.execute("""
                INSERT INTO `订单流水` (`邮箱`, `交易的标的代码`, `买入和卖出`, `交易的股的数量`, `实际成交价`, `交易手续费`) 
                VALUES (%s, %s, %s, %s, %s, %s)
            """, (email, order.symbol, order.action, order.quantity, exec_price, fee))

            # 提交事务！所有改动生效
            conn.commit()

            return {
                "success": True,
                "symbol": order.symbol,
                "action": order.action,
                "quantity": order.quantity,
                "exec_price": exec_price,
                "amount": amount,
                "fee": fee,
                "cash_after": current_cash - total_cost if order.action == 'BUY' else current_cash + (amount - fee),
                "is_spot_price": True
            }

    except Exception as e:
        # 发生任何错误，撤销上述所有数据库操作，保证资金安全
        conn.rollback()
        print("Transaction Error:", e)  # 在控制台打印具体错误方便调试
        raise HTTPException(status_code=500, detail=f"交易失败: {str(e)}")
    finally:
        # 关闭数据库连接
        conn.close()


@app.get("/api/v1/trade/account")
def get_account(email: str = Depends(get_current_user_email)):
    conn = pymysql.connect(**DB_CONFIG)
    try:
        with conn.cursor() as cursor:
            # 1. 查询资金账户状态
            cursor.execute("SELECT * FROM `资金账户表` WHERE `邮箱` = %s", (email,))
            account = cursor.fetchone()

            if not account:
                # 如果数据库里还没这个人的资金记录，返回全部为 0 的空状态
                return {
                    "cash_cnh": 0, "cash_usd": 0, "cash_hkd": 0,
                    "order_count": 0, "positions": []
                }

            # 2. 查询持仓记录
            cursor.execute("SELECT * FROM `持仓记录` WHERE `邮箱` = %s", (email,))
            positions_db = cursor.fetchall()

            # 3. 将数据库字段映射为前端期望的英文字段格式
            positions = []
            for p in positions_db:
                positions.append({
                    "symbol": p["股票和标的代码"],
                    "name": p["标的名称"],
                    "market_type": p["市场种类"],
                    "quantity": p["持有数量"],
                    "avg_cost": p["持仓均价"],
                    # 现价和盈亏理论上需要调用实时行情计算，这里为了跑通流程，先用持仓价模拟
                    "current_price": p["持仓均价"],
                    "market_value": p["持有数量"] * p["持仓均价"],
                    "unrealized_pnl": 0,
                    "change_pct": 0,
                    "pnl_pct": 0
                })

            return {
                "cash_cnh": account["A股可用资金"],
                "cash_usd": account["美股可用资金"],
                "cash_hkd": account["港股可用资金"],
                "order_count": account["累计成交笔数"],
                "positions": positions
            }
    finally:
        conn.close()


@app.get("/api/v1/trade/orders")
def get_orders(limit: int = 100, email: str = Depends(get_current_user_email)):
    conn = pymysql.connect(**DB_CONFIG)
    try:
        with conn.cursor() as cursor:
            # 按照标识（ID）倒序排列，最新的交易记录排在最前面
            cursor.execute("SELECT * FROM `订单流水` WHERE `邮箱` = %s ORDER BY `标识` DESC LIMIT %s", (email, limit))
            orders_db = cursor.fetchall()

            orders = []
            for o in orders_db:
                orders.append({
                    "symbol": o["交易的标的代码"],
                    "action": o["买入和卖出"],
                    "quantity": o["交易的股的数量"],
                    "exec_price": o["实际成交价"],
                    "amount": o["交易总金额"],
                    "fee": o["交易手续费"],
                    # 你的数据表目前没有时间字段，先用当前时间补齐前端需求
                    "created_at": "2026-03-21T15:30:00"
                })
            return {"orders": orders}
    finally:
        conn.close()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8001)

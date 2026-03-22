from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import pymysql
import uuid

app = FastAPI()

# 允许跨域请求（前端调用必备）
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 宝塔数据库配置
DB_CONFIG = {
    'host': '8.156.85.111',
    'user': 'monijiaoyishuju',
    'password': 'fGNFEYSf66tmTeCD',
    'database': 'monijiaoyishuju',
    'charset': 'utf8mb4',
    'cursorclass': pymysql.cursors.DictCursor
}


# 接收前端传来的数据格式
class RegisterRequest(BaseModel):
    username: str
    email: str
    password: str


class LoginRequest(BaseModel):
    email: str
    password: str


# --- 注册接口 ---
@app.post("/api/v1/auth/register")
def register(req: RegisterRequest):
    connection = pymysql.connect(**DB_CONFIG)
    try:
        with connection.cursor() as cursor:
            # 1. 检查邮箱是否已存在
            cursor.execute("SELECT * FROM 用户数据 WHERE 邮箱 = %s", (req.email,))
            if cursor.fetchone():
                raise HTTPException(status_code=400, detail="该邮箱已被注册")

            # 2. 插入新用户（严格对应你的3列：用户名, 邮箱, 密码）
            sql = "INSERT INTO 用户数据 (用户名, 邮箱, 密码) VALUES (%s, %s, %s)"
            cursor.execute(sql, (req.username, req.email, req.password))

            # 3. 💸 关键新增：立刻为新注册的用户发放初始资金！
            sql_fund = """INSERT INTO 资金账户表 (邮箱, A股可用资金, 美股可用资金, 港股可用资金, 累计成交笔数) VALUES (%s, %s, %s, %s, %s)"""
            # 发放：A股10万，美股1万，港股10万，0交易
            cursor.execute(sql_fund, (req.email, 100000.00, 10000.00, 100000.00, 0))

        # 必须 commit 才能真正写入数据库
        connection.commit()

        # 返回前端需要的 JSON 格式，暂时用邮箱作为 user_id
        return {
            "message": "注册成功！初始资金已经发放",
            "token": f"fake-jwt-token-{uuid.uuid4()}",
            "username": req.username,
            "user_id": req.email
        }
    finally:
        connection.close()


# --- 登录接口 ---
@app.post("/api/v1/auth/login")
def login(req: LoginRequest):
    connection = pymysql.connect(**DB_CONFIG)
    try:
        with connection.cursor() as cursor:
            # 根据邮箱和密码查询用户（严格对应你的3列）
            sql = "SELECT 用户名 FROM 用户数据 WHERE 邮箱 = %s AND 密码 = %s"
            cursor.execute(sql, (req.email, req.password))
            user = cursor.fetchone()

            if not user:
                raise HTTPException(status_code=401, detail="邮箱或密码错误")

            # 登录成功，返回前端需要的数据
            return {
                "message": "登录成功",
                "token": f"fake-jwt-token-{uuid.uuid4()}",
                "username": user['用户名'],
                "user_id": req.email
            }
    finally:
        connection.close()

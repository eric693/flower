from flask import Flask, request, abort, jsonify, redirect, url_for
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import (
    MessageEvent, TextMessage, TextSendMessage,
    FlexSendMessage, BubbleContainer, BoxComponent,
    TextComponent, SeparatorComponent, ButtonComponent,
    URIAction, PostbackAction, PostbackEvent,
    QuickReply, QuickReplyButton, MessageAction
)
import os
import sqlite3
import datetime
import secrets
import string
import requests
import json
import hashlib
import hmac
import base64

app = Flask(__name__)

# LINE Bot 設定
LINE_CHANNEL_ACCESS_TOKEN = 'NHv54nNB1d2yFR5rhfjvRIcKR8DtM+g/H2kXkVrPRJeeQrOKoM5ezA8HnnoGIm+iUHRYTLtMxa10Lr5Irems1wb6YQSOMCkJb+8oSwyOt5DdJs/gmuaC5gTz689eCXoCJFJIYLiQY/9EeYB+Ox+WHQdB04t89/1O/w1cDnyilFU='
LINE_CHANNEL_SECRET = '0a486d77dd9aea4bb56500ca7d0661be'

# LINE Pay 設定 - 請替換為您的實際值
LINEPAY_CHANNEL_ID = 'YOUR_LINEPAY_CHANNEL_ID'
LINEPAY_CHANNEL_SECRET = 'YOUR_LINEPAY_CHANNEL_SECRET'
LINEPAY_API_URL = 'https://sandbox-api-pay.line.me'  # 沙盒環境
LINEPAY_VERSION = 'v3'

# 網站基礎 URL
BASE_URL = 'https://your-domain.com'

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# 管理員設定
ADMIN_USER_IDS = ['Ud956df5564ad0c77eb2f849db0eccfeb']

# 商品目錄
PRODUCT_CATALOG = {
    'preserved_small': {
        'name': '永生花小束',
        'description': '精緻小巧的永生花束，適合桌面擺設',
        'price': 1200,
        'image': 'https://example.com/preserved_small.jpg'
    },
    'preserved_medium': {
        'name': '永生花中束', 
        'description': '經典尺寸永生花束，送禮首選',
        'price': 2500,
        'image': 'https://example.com/preserved_medium.jpg'
    },
    'preserved_large': {
        'name': '永生花大束',
        'description': '豪華大束永生花，重要場合必備',
        'price': 4800,
        'image': 'https://example.com/preserved_large.jpg'
    },
    'dried_bouquet': {
        'name': '乾燥花花束',
        'description': '自然風格乾燥花束，質感優雅',
        'price': 1800,
        'image': 'https://example.com/dried_bouquet.jpg'
    },
    'sola_arrangement': {
        'name': '索拉花香氛組',
        'description': '手工索拉花配香氛精油',
        'price': 2200,
        'image': 'https://example.com/sola_arrangement.jpg'
    },
    'custom_design': {
        'name': '客製化設計',
        'description': '專屬設計服務，依需求報價',
        'price': 3000,
        'image': 'https://example.com/custom_design.jpg'
    }
}

# 用戶狀態追蹤
user_states = {}

def init_shop_database():
    """初始化購物系統資料庫"""
    conn = sqlite3.connect('flower_shop.db')
    cursor = conn.cursor()
    
    # 訂單表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_number TEXT UNIQUE NOT NULL,
            user_id TEXT NOT NULL,
            customer_name TEXT NOT NULL,
            phone TEXT NOT NULL,
            product_id TEXT NOT NULL,
            product_name TEXT NOT NULL,
            quantity INTEGER DEFAULT 1,
            unit_price INTEGER NOT NULL,
            total_amount INTEGER NOT NULL,
            pickup_date TEXT,
            pickup_time TEXT,
            special_requirements TEXT,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # LINE Pay 交易表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS linepay_transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_number TEXT NOT NULL,
            transaction_id TEXT UNIQUE NOT NULL,
            linepay_order_id TEXT,
            amount INTEGER NOT NULL,
            currency TEXT DEFAULT 'TWD',
            status TEXT DEFAULT 'pending',
            payment_url TEXT,
            confirm_url TEXT,
            cancel_url TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            paid_at TIMESTAMP,
            FOREIGN KEY (order_number) REFERENCES orders (order_number)
        )
    ''')
    
    # 客製化需求表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS custom_requirements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_number TEXT NOT NULL,
            color_preference TEXT,
            size_preference TEXT,
            style_preference TEXT,
            budget_range TEXT,
            special_message TEXT,
            reference_images TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (order_number) REFERENCES orders (order_number)
        )
    ''')
    
    conn.commit()
    conn.close()

def generate_order_number():
    """生成訂單編號"""
    date_str = datetime.datetime.now().strftime("%Y%m%d")
    random_code = ''.join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(6))
    return f"FO{date_str}{random_code}"

def generate_transaction_id():
    """生成交易ID"""
    timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
    random_code = ''.join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(4))
    return f"TXN{timestamp}{random_code}"

def create_linepay_signature(uri, request_body, nonce):
    """建立 LINE Pay API 簽章"""
    message = LINEPAY_CHANNEL_SECRET + uri + request_body + nonce
    signature = base64.b64encode(
        hmac.new(
            LINEPAY_CHANNEL_SECRET.encode('utf-8'),
            message.encode('utf-8'),
            hashlib.sha256
        ).digest()
    ).decode('utf-8')
    return signature

def request_linepay_payment(order_data):
    """向 LINE Pay 請求付款"""
    transaction_id = generate_transaction_id()
    
    request_data = {
        "amount": order_data['total_amount'],
        "currency": "TWD",
        "orderId": order_data['order_number'],
        "packages": [
            {
                "id": "package1",
                "amount": order_data['total_amount'],
                "name": "花材商品",
                "products": [
                    {
                        "id": order_data['product_id'],
                        "name": order_data['product_name'],
                        "imageUrl": PRODUCT_CATALOG.get(order_data['product_id'], {}).get('image', ''),
                        "quantity": order_data['quantity'],
                        "price": order_data['unit_price']
                    }
                ]
            }
        ],
        "redirectUrls": {
            "confirmUrl": f"{BASE_URL}/linepay/confirm/{transaction_id}",
            "cancelUrl": f"{BASE_URL}/linepay/cancel/{transaction_id}"
        }
    }
    
    uri = f"/{LINEPAY_VERSION}/payments/request"
    nonce = str(secrets.randbelow(10**10)).zfill(10)
    request_body = json.dumps(request_data)
    
    headers = {
        "Content-Type": "application/json",
        "X-LINE-ChannelId": LINEPAY_CHANNEL_ID,
        "X-LINE-Authorization-Nonce": nonce,
        "X-LINE-Authorization": create_linepay_signature(uri, request_body, nonce)
    }
    
    try:
        response = requests.post(f"{LINEPAY_API_URL}{uri}", headers=headers, data=request_body)
        result = response.json()
        
        if result.get('returnCode') == '0000':
            save_transaction(
                order_data['order_number'],
                transaction_id,
                order_data['total_amount'],
                result['info']['paymentUrl']['web'],
                f"{BASE_URL}/linepay/confirm/{transaction_id}",
                f"{BASE_URL}/linepay/cancel/{transaction_id}"
            )
            return True, result['info']['paymentUrl']['web'], transaction_id
        else:
            return False, result.get('returnMessage', '付款請求失敗'), None
    except Exception as e:
        return False, f"系統錯誤: {str(e)}", None

def confirm_linepay_payment(transaction_id, confirmation_code):
    """確認 LINE Pay 付款"""
    conn = sqlite3.connect('flower_shop.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT lt.*, o.total_amount 
        FROM linepay_transactions lt 
        JOIN orders o ON lt.order_number = o.order_number 
        WHERE lt.transaction_id = ?
    ''', (transaction_id,))
    
    transaction = cursor.fetchone()
    conn.close()
    
    if not transaction:
        return False, "找不到交易記錄"
    
    request_data = {
        "amount": transaction[3],
        "currency": transaction[4]
    }
    
    uri = f"/{LINEPAY_VERSION}/payments/{confirmation_code}/confirm"
    nonce = str(secrets.randbelow(10**10)).zfill(10)
    request_body = json.dumps(request_data)
    
    headers = {
        "Content-Type": "application/json",
        "X-LINE-ChannelId": LINEPAY_CHANNEL_ID,
        "X-LINE-Authorization-Nonce": nonce,
        "X-LINE-Authorization": create_linepay_signature(uri, request_body, nonce)
    }
    
    try:
        response = requests.post(f"{LINEPAY_API_URL}{uri}", headers=headers, data=request_body)
        result = response.json()
        
        if result.get('returnCode') == '0000':
            update_transaction_status(transaction_id, 'completed')
            update_order_status(transaction[1], 'paid')
            return True, "付款成功"
        else:
            return False, result.get('returnMessage', '付款確認失敗')
    except Exception as e:
        return False, f"系統錯誤: {str(e)}"

def save_order(order_data):
    """儲存訂單"""
    conn = sqlite3.connect('flower_shop.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        INSERT INTO orders 
        (order_number, user_id, customer_name, phone, product_id, product_name, 
         quantity, unit_price, total_amount, pickup_date, pickup_time, special_requirements)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        order_data['order_number'], order_data['user_id'], order_data['customer_name'],
        order_data['phone'], order_data['product_id'], order_data['product_name'],
        order_data['quantity'], order_data['unit_price'], order_data['total_amount'],
        order_data.get('pickup_date'), order_data.get('pickup_time'),
        order_data.get('special_requirements', '')
    ))
    
    conn.commit()
    conn.close()

def save_transaction(order_number, transaction_id, amount, payment_url, confirm_url, cancel_url):
    """儲存交易資料"""
    conn = sqlite3.connect('flower_shop.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        INSERT INTO linepay_transactions 
        (order_number, transaction_id, amount, payment_url, confirm_url, cancel_url)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (order_number, transaction_id, amount, payment_url, confirm_url, cancel_url))
    
    conn.commit()
    conn.close()

def update_transaction_status(transaction_id, status):
    """更新交易狀態"""
    conn = sqlite3.connect('flower_shop.db')
    cursor = conn.cursor()
    
    if status == 'completed':
        cursor.execute('''
            UPDATE linepay_transactions 
            SET status = ?, paid_at = CURRENT_TIMESTAMP 
            WHERE transaction_id = ?
        ''', (status, transaction_id))
    else:
        cursor.execute('''
            UPDATE linepay_transactions 
            SET status = ? WHERE transaction_id = ?
        ''', (status, transaction_id))
    
    conn.commit()
    conn.close()

def update_order_status(order_number, status):
    """更新訂單狀態"""
    conn = sqlite3.connect('flower_shop.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        UPDATE orders 
        SET status = ?, updated_at = CURRENT_TIMESTAMP 
        WHERE order_number = ?
    ''', (status, order_number))
    
    conn.commit()
    conn.close()

def get_user_orders(user_id):
    """取得用戶訂單"""
    conn = sqlite3.connect('flower_shop.db')
    cursor = conn.cursor()
    
    cursor.execute('SELECT * FROM orders WHERE user_id = ? ORDER BY created_at DESC', (user_id,))
    results = cursor.fetchall()
    conn.close()
    
    orders = []
    for result in results:
        orders.append({
            'id': result[0], 'order_number': result[1], 'user_id': result[2],
            'customer_name': result[3], 'phone': result[4], 'product_id': result[5],
            'product_name': result[6], 'quantity': result[7], 'unit_price': result[8],
            'total_amount': result[9], 'pickup_date': result[10], 'pickup_time': result[11],
            'special_requirements': result[12], 'status': result[13], 'created_at': result[14],
            'updated_at': result[15]
        })
    return orders

def create_product_catalog_flex():
    """建立商品目錄 Flex Message"""
    bubble = BubbleContainer(
        body=BoxComponent(
            layout="vertical",
            contents=[
                TextComponent(text="🌺 花材商品目錄", weight="bold", size="xl", color="#1DB446"),
                SeparatorComponent(margin="md")
            ]
        )
    )
    
    for product_id, product in PRODUCT_CATALOG.items():
        bubble.body.contents.extend([
            TextComponent(text=product['name'], weight="bold", size="md", margin="lg", color="#FF6B35"),
            TextComponent(text=product['description'], size="sm", margin="sm", wrap=True),
            TextComponent(text=f"NT$ {product['price']:,}", size="md", margin="sm", color="#2196F3", weight="bold"),
            ButtonComponent(
                action=PostbackAction(label="選擇此商品", data=f"select_product_{product_id}"),
                color="#4CAF50", margin="sm"
            ),
            SeparatorComponent(margin="md")
        ])
    
    return FlexSendMessage(alt_text="商品目錄", contents=bubble)

def create_order_summary_flex(order_data, payment_url):
    """建立訂單摘要 Flex Message"""
    bubble = BubbleContainer(
        body=BoxComponent(
            layout="vertical",
            contents=[
                TextComponent(text="🛒 訂單確認", weight="bold", size="xl", color="#1DB446"),
                SeparatorComponent(margin="md"),
                TextComponent(text=f"訂單編號：{order_data['order_number']}", weight="bold", size="md", margin="lg", color="#FF6B35"),
                TextComponent(text=f"商品：{order_data['product_name']}", size="sm", margin="sm"),
                TextComponent(text=f"數量：{order_data['quantity']}", size="sm", margin="sm"),
                TextComponent(text=f"單價：NT$ {order_data['unit_price']:,}", size="sm", margin="sm"),
                TextComponent(text=f"總金額：NT$ {order_data['total_amount']:,}", size="md", margin="sm", color="#2196F3", weight="bold"),
                TextComponent(text=f"取貨日期：{order_data.get('pickup_date', '未指定')}", size="sm", margin="sm"),
                TextComponent(text=f"取貨時間：{order_data.get('pickup_time', '未指定')}", size="sm", margin="sm")
            ]
        ),
        footer=BoxComponent(
            layout="vertical",
            contents=[
                ButtonComponent(
                    action=URIAction(label="💳 前往 LINE Pay 付款", uri=payment_url),
                    color="#00C300"
                )
            ]
        )
    )
    
    return FlexSendMessage(alt_text="訂單確認", contents=bubble)

def create_main_menu():
    """建立主選單"""
    quick_reply = QuickReply(items=[
        QuickReplyButton(action=MessageAction(label="🛍️ 購買商品", text="購買商品")),
        QuickReplyButton(action=MessageAction(label="📋 我的訂單", text="我的訂單")),
        QuickReplyButton(action=MessageAction(label="🎨 客製設計", text="客製設計")),
        QuickReplyButton(action=MessageAction(label="📞 聯絡客服", text="聯絡客服")),
    ])
    return quick_reply

def create_admin_menu():
    """建立管理員選單"""
    quick_reply = QuickReply(items=[
        QuickReplyButton(action=MessageAction(label="📋 所有訂單", text="查看所有訂單")),
        QuickReplyButton(action=MessageAction(label="💰 付款記錄", text="付款記錄")),
        QuickReplyButton(action=MessageAction(label="🔍 查詢訂單", text="查詢訂單")),
        QuickReplyButton(action=MessageAction(label="🔙 用戶選單", text="主選單")),
    ])
    return quick_reply

@app.route("/", methods=['GET'])
def home():
    return "花材 LINE Pay 購物系統運行中！"

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    
    return 'OK'

@app.route("/linepay/confirm/<transaction_id>", methods=['GET'])
def linepay_confirm(transaction_id):
    """LINE Pay 付款確認頁面"""
    confirmation_code = request.args.get('transactionId')
    
    if not confirmation_code:
        return "缺少確認碼", 400
    
    success, message = confirm_linepay_payment(transaction_id, confirmation_code)
    
    if success:
        return f"""
        <html>
        <head><title>付款成功</title></head>
        <body style="text-align: center; padding: 50px;">
            <h1>🎉 付款成功！</h1>
            <p>感謝您的購買，我們會盡快為您準備商品。</p>
            <p>訂單資訊已發送至您的 LINE，請查收。</p>
            <script>setTimeout(function() {{ window.close(); }}, 3000);</script>
        </body>
        </html>
        """
    else:
        return f"""
        <html>
        <head><title>付款失敗</title></head>
        <body style="text-align: center; padding: 50px;">
            <h1>❌ 付款失敗</h1>
            <p>{message}</p>
            <p>請聯絡客服或重新嘗試付款。</p>
        </body>
        </html>
        """

@app.route("/linepay/cancel/<transaction_id>", methods=['GET'])
def linepay_cancel(transaction_id):
    """LINE Pay 付款取消頁面"""
    update_transaction_status(transaction_id, 'cancelled')
    
    return """
    <html>
    <head><title>付款取消</title></head>
    <body style="text-align: center; padding: 50px;">
        <h1>❌ 付款已取消</h1>
        <p>您已取消此次付款，如需重新付款請聯絡客服。</p>
        <script>setTimeout(function() { window.close(); }, 3000);</script>
    </body>
    </html>
    """

@handler.add(PostbackEvent)
def handle_postback(event):
    """處理 Postback 事件"""
    user_id = event.source.user_id
    postback_data = event.postback.data
    
    if postback_data.startswith('select_product_'):
        product_id = postback_data.replace('select_product_', '')
        
        if product_id in PRODUCT_CATALOG:
            product = PRODUCT_CATALOG[product_id]
            user_states[user_id] = {
                'step': 'waiting_quantity',
                'product_id': product_id,
                'product_name': product['name'],
                'unit_price': product['price']
            }
            
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(
                    text=f"您選擇了：{product['name']}\n單價：NT$ {product['price']:,}\n\n請輸入購買數量："
                )
            )

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_message = event.message.text.strip()
    user_id = event.source.user_id
    
    # 檢查用戶狀態
    if user_id in user_states:
        state = user_states[user_id]
        
        if isinstance(state, dict) and state.get('step') == 'waiting_quantity':
            try:
                quantity = int(user_message)
                if quantity <= 0:
                    raise ValueError("數量必須大於0")
                
                state['quantity'] = quantity
                state['total_amount'] = state['unit_price'] * quantity
                state['step'] = 'waiting_customer_info'
                
                line_bot_api.reply_message(
                    event.reply_token,
                    TextSendMessage(text=f"數量：{quantity}\n總金額：NT$ {state['total_amount']:,}\n\n請提供您的姓名：")
                )
                return
            except ValueError:
                line_bot_api.reply_message(
                    event.reply_token,
                    TextSendMessage(text="請輸入有效的數量（正整數）：")
                )
                return
        
        elif isinstance(state, dict) and state.get('step') == 'waiting_customer_info':
            state['customer_name'] = user_message
            state['step'] = 'waiting_phone'
            line_bot_api.reply_message(event.reply_token, TextSendMessage(text="請提供您的聯絡電話："))
            return
        
        elif isinstance(state, dict) and state.get('step') == 'waiting_phone':
            state['phone'] = user_message
            state['step'] = 'waiting_pickup_date'
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text="請提供取貨日期（格式：YYYY-MM-DD，例如：2025-08-25）：")
            )
            return
        
        elif isinstance(state, dict) and state.get('step') == 'waiting_pickup_date':
            try:
                pickup_date = datetime.datetime.strptime(user_message, "%Y-%m-%d").date()
                today = datetime.date.today()
                if pickup_date < today:
                    line_bot_api.reply_message(
                        event.reply_token,
                        TextSendMessage(text="取貨日期不能是過去的日期，請重新輸入：")
                    )
                    return
                
                state['pickup_date'] = user_message
                state['step'] = 'waiting_pickup_time'
                line_bot_api.reply_message(
                    event.reply_token,
                    TextSendMessage(text="請提供取貨時間（格式：HH:MM，例如：14:30）：")
                )
                return
            except ValueError:
                line_bot_api.reply_message(
                    event.reply_token,
                    TextSendMessage(text="日期格式錯誤，請使用 YYYY-MM-DD 格式：")
                )
                return
        
        elif isinstance(state, dict) and state.get('step') == 'waiting_pickup_time':
            try:
                datetime.datetime.strptime(user_message, "%H:%M")
                state['pickup_time'] = user_message
                
                # 建立訂單
                order_number = generate_order_number()
                
                order_data = {
                    'order_number': order_number,
                    'user_id': user_id,
                    'customer_name': state['customer_name'],
                    'phone': state['phone'],
                    'product_id': state['product_id'],
                    'product_name': state['product_name'],
                    'quantity': state['quantity'],
                    'unit_price': state['unit_price'],
                    'total_amount': state['total_amount'],
                    'pickup_date': state['pickup_date'],
                    'pickup_time': state['pickup_time']
                }
                
                # 儲存訂單
                save_order(order_data)
                
                # 請求 LINE Pay 付款
                success, payment_url_or_error, transaction_id = request_linepay_payment(order_data)
                
                # 清除用戶狀態
                del user_states[user_id]
                
                if success:
                    line_bot_api.reply_message(
                        event.reply_token,
                        [
                            create_order_summary_flex(order_data, payment_url_or_error),
                            TextSendMessage(
                                text="📱 請點擊上方按鈕前往 LINE Pay 完成付款。\n\n⚠️ 請在15分鐘內完成付款，逾時訂單將自動取消。",
                                quick_reply=create_main_menu()
                            )
                        ]
                    )
                else:
                    line_bot_api.reply_message(
                        event.reply_token,
                        TextSendMessage(
                            text=f"❌ 付款請求失敗：{payment_url_or_error}\n\n請稍後再試或聯絡客服。",
                            quick_reply=create_main_menu()
                        )
                    )
                return
            except ValueError:
                line_bot_api.reply_message(
                    event.reply_token,
                    TextSendMessage(text="時間格式錯誤，請使用 HH:MM 格式：")
                )
                return
    
    # 主選單
    if user_message in ["主選單", "選單", "menu", "開始", "hi", "hello", "你好"]:
        if user_id in ADMIN_USER_IDS:
            reply_text = "🌺 歡迎來到花材購物系統（管理員模式）！"
            menu = create_admin_menu()
        else:
            reply_text = "🌺 歡迎來到花材購物系統！\n請選擇您需要的服務："
            menu = create_main_menu()
        
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=reply_text, quick_reply=menu)
        )
    
    # 購買商品
    elif user_message == "購買商品":
        line_bot_api.reply_message(
            event.reply_token,
            [
                create_product_catalog_flex(),
                TextSendMessage(
                    text="請選擇您想購買的商品，點擊「選擇此商品」按鈕開始訂購流程。",
                    quick_reply=create_main_menu()
                )
            ]
        )
    
    # 我的訂單
    elif user_message == "我的訂單":
        orders = get_user_orders(user_id)
        if orders:
            reply_text = "📋 您的訂單列表：\n\n"
            for order in orders[-5:]:  # 顯示最近5筆
                status_emoji = {'pending': '⏳', 'paid': '✅', 'completed': '🎉', 'cancelled': '❌'}
                emoji = status_emoji.get(order['status'], '❓')
                reply_text += f"{emoji} {order['order_number']}\n"
                reply_text += f"   {order['product_name']} x{order['quantity']}\n"
                reply_text += f"   NT$ {order['total_amount']:,} | {order['status']}\n"
                reply_text += f"   {order['created_at'][:16]}\n\n"
        else:
            reply_text = "📋 您目前沒有訂單記錄"
        
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=reply_text, quick_reply=create_main_menu())
        )
    
    # 客製設計
    elif user_message == "客製設計":
        user_states[user_id] = {
            'step': 'custom_design_start',
            'product_id': 'custom_design',
            'product_name': '客製化設計',
            'unit_price': 3000
        }
        
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(
                text="🎨 客製化設計服務\n\n我們將根據您的需求設計專屬花藝作品。\n基礎價格：NT$ 3,000 起\n\n請告訴我您偏好的色系（例如：粉色系、自然色系、繽紛色彩等）："
            )
        )
    
    # 聯絡客服
    elif user_message == "聯絡客服":
        reply_text = "📞 客服聯絡方式：\n\n📱 電話：0912-345-678\n📧 Email：service@flower-studio.com\n🕐 服務時間：週一至週五 09:00-18:00\n\n💬 您也可以直接在此對話中留言，我們會盡快回覆！"
        
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=reply_text, quick_reply=create_main_menu())
        )
    
    else:
        # 其他訊息處理
        reply_text = "抱歉，我沒有理解您的訊息。請使用下方選單選擇服務項目。"
        menu = create_admin_menu() if user_id in ADMIN_USER_IDS else create_main_menu()
        
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=reply_text, quick_reply=menu)
        )

if __name__ == "__main__":
    # 初始化資料庫
    init_shop_database()
    
    port = int(os.environ.get('PORT', 8000))
    app.run(host='0.0.0.0', port=port, debug=True)
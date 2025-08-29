#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Polly 花藝店 LINE Bot 支付系統
支援 LINE Pay 和信用卡支付功能
"""

import os
import json
import hashlib
import hmac
import base64
import time
import uuid
from urllib.parse import urlencode, quote_plus
from datetime import datetime
from flask import Flask, request, abort, render_template_string, redirect, url_for
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError, LineBotApiError
from linebot.models import (
    MessageEvent, TextMessage, TextSendMessage, PostbackEvent,
    TemplateSendMessage, CarouselTemplate, CarouselColumn,
    ButtonsTemplate, QuickReply, QuickReplyButton,
    PostbackAction, URIAction, MessageAction
)
import requests
from dotenv import load_dotenv

# 載入環境變數
load_dotenv()

app = Flask(__name__)

# LINE Bot 配置
line_bot_api = LineBotApi(os.getenv('LINE_CHANNEL_ACCESS_TOKEN'))
handler = WebhookHandler(os.getenv('LINE_CHANNEL_SECRET'))

# LINE Pay 配置
LINEPAY_CONFIG = {
    'channel_id': os.getenv('LINEPAY_CHANNEL_ID'),
    'channel_secret': os.getenv('LINEPAY_CHANNEL_SECRET'),
    'merchant_id': os.getenv('LINEPAY_MERCHANT_ID'),
    'api_url': 'https://sandbox-api-pay.line.me',  # 測試環境
    'is_sandbox': True
}

# ECPay 配置 (綠界科技)
ECPAY_CONFIG = {
    'merchant_id': os.getenv('ECPAY_MERCHANT_ID'),
    'hash_key': os.getenv('ECPAY_HASH_KEY'),
    'hash_iv': os.getenv('ECPAY_HASH_IV'),
    'payment_url': 'https://payment-stage.ecpay.com.tw/Cashier/AioCheckOut/V5'  # 測試環境
}

# 商品資料
PRODUCTS = {
    '1': {
        'id': '1',
        'name': '玫瑰花束',
        'price': 800,
        'description': '精選紅玫瑰，浪漫首選',
        'image': 'https://images.unsplash.com/photo-1518895949257-7621c3c786d7?w=300&h=300&fit=crop'
    },
    '2': {
        'id': '2',
        'name': '百合花束',
        'price': 1200,
        'description': '純白百合，典雅高貴',
        'image': 'https://images.unsplash.com/photo-1563241527-3004b7be0fca?w=300&h=300&fit=crop'
    },
    '3': {
        'id': '3',
        'name': '康乃馨花束',
        'price': 600,
        'description': '溫馨康乃馨，表達關愛',
        'image': 'https://images.unsplash.com/photo-1561181286-d3fee7d55364?w=300&h=300&fit=crop'
    },
    '4': {
        'id': '4',
        'name': '混合花束',
        'price': 1500,
        'description': '季節花材精心搭配',
        'image': 'https://images.unsplash.com/photo-1487070183336-b863922373d4?w=300&h=300&fit=crop'
    }
}

# 全域變數儲存付款表單
payment_forms = {}
orders = {}

class PaymentProcessor:
    """支付處理器"""
    
    @staticmethod
    def generate_order_id():
        """產生訂單編號"""
        timestamp = str(int(time.time()))
        random_str = str(uuid.uuid4())[:8].upper()
        return f"ORD{timestamp}{random_str}"
    
    @staticmethod
    def generate_linepay_signature(channel_secret, uri, request_body, nonce):
        """產生 LINE Pay 簽名"""
        message = f"{channel_secret}{uri}{request_body}{nonce}"
        signature = base64.b64encode(
            hmac.new(
                channel_secret.encode('utf-8'),
                message.encode('utf-8'),
                hashlib.sha256
            ).digest()
        ).decode('utf-8')
        return signature
    
    @staticmethod
    def create_linepay_payment(product_id, user_id):
        """建立 LINE Pay 付款請求"""
        try:
            product = PRODUCTS.get(product_id)
            if not product:
                return None, "商品不存在"
            
            order_id = PaymentProcessor.generate_order_id()
            
            # 請求資料
            request_body = {
                "amount": product['price'],
                "currency": "TWD",
                "orderId": order_id,
                "packages": [{
                    "id": product_id,
                    "amount": product['price'],
                    "products": [{
                        "id": product_id,
                        "name": product['name'],
                        "quantity": 1,
                        "price": product['price']
                    }]
                }],
                "redirectUrls": {
                    "confirmUrl": f"{os.getenv('BASE_URL')}/linepay/confirm",
                    "cancelUrl": f"{os.getenv('BASE_URL')}/linepay/cancel"
                }
            }
            
            # 產生簽名
            uri = "/v3/payments/request"
            nonce = str(int(time.time() * 1000))
            request_body_json = json.dumps(request_body, separators=(',', ':'))
            
            signature = PaymentProcessor.generate_linepay_signature(
                LINEPAY_CONFIG['channel_secret'],
                uri,
                request_body_json,
                nonce
            )
            
            # 發送請求
            headers = {
                'Content-Type': 'application/json',
                'X-LINE-ChannelId': LINEPAY_CONFIG['channel_id'],
                'X-LINE-Authorization-Nonce': nonce,
                'X-LINE-Authorization': signature
            }
            
            response = requests.post(
                f"{LINEPAY_CONFIG['api_url']}{uri}",
                data=request_body_json,
                headers=headers
            )
            
            response_data = response.json()
            
            if response_data.get('returnCode') == '0000':
                # 儲存訂單資訊
                orders[order_id] = {
                    'product_id': product_id,
                    'user_id': user_id,
                    'amount': product['price'],
                    'status': 'pending',
                    'payment_method': 'linepay',
                    'created_at': datetime.now()
                }
                
                return response_data['info']['paymentUrl']['web'], None
            else:
                return None, f"LINE Pay 錯誤: {response_data.get('returnMessage', '未知錯誤')}"
                
        except Exception as e:
            return None, f"建立付款失敗: {str(e)}"
    
    @staticmethod
    def generate_ecpay_check_mac_value(params):
        """產生 ECPay 檢查碼"""
        # 移除 CheckMacValue 並排序
        filtered_params = {k: v for k, v in params.items() if k != 'CheckMacValue'}
        sorted_params = dict(sorted(filtered_params.items()))
        
        # 組合字串
        param_string = f"HashKey={ECPAY_CONFIG['hash_key']}&"
        param_string += "&".join([f"{key}={value}" for key, value in sorted_params.items()])
        param_string += f"&HashIV={ECPAY_CONFIG['hash_iv']}"
        
        # URL encode
        encoded_string = quote_plus(param_string, safe='').lower()
        encoded_string = encoded_string.replace('%2d', '-').replace('%5f', '_').replace('%2e', '.').replace('%21', '!').replace('%2a', '*').replace('%28', '(').replace('%29', ')')
        
        # SHA256 hash
        check_mac_value = hashlib.sha256(encoded_string.encode('utf-8')).hexdigest().upper()
        return check_mac_value
    
    @staticmethod
    def create_ecpay_payment(product_id, user_id):
        """建立 ECPay 信用卡付款"""
        try:
            product = PRODUCTS.get(product_id)
            if not product:
                return None, "商品不存在"
            
            order_id = PaymentProcessor.generate_order_id()
            
            # 付款參數
            trade_info = {
                'MerchantID': ECPAY_CONFIG['merchant_id'],
                'MerchantTradeNo': order_id,
                'MerchantTradeDate': datetime.now().strftime('%Y/%m/%d %H:%M:%S'),
                'PaymentType': 'aio',
                'TotalAmount': str(product['price']),
                'TradeDesc': f'Polly花藝店-{product["name"]}',
                'ItemName': product['name'],
                'ReturnURL': f"{os.getenv('BASE_URL')}/ecpay/return",
                'ClientBackURL': f"{os.getenv('BASE_URL')}/ecpay/client_back",
                'ChoosePayment': 'Credit',
                'EncryptType': '1'
            }
            
            # 產生檢查碼
            check_mac_value = PaymentProcessor.generate_ecpay_check_mac_value(trade_info)
            trade_info['CheckMacValue'] = check_mac_value
            
            # 儲存訂單資訊
            orders[order_id] = {
                'product_id': product_id,
                'user_id': user_id,
                'amount': product['price'],
                'status': 'pending',
                'payment_method': 'creditcard',
                'created_at': datetime.now()
            }
            
            # 儲存付款表單
            payment_forms[order_id] = trade_info
            
            return f"{os.getenv('BASE_URL')}/payment/creditcard/{order_id}", None
            
        except Exception as e:
            return None, f"建立付款失敗: {str(e)}"

class MessageHandler:
    """訊息處理器"""
    
    @staticmethod
    def create_product_catalog():
        """建立商品目錄"""
        columns = []
        for product in PRODUCTS.values():
            column = CarouselColumn(
                thumbnail_image_url=product['image'],
                title=product['name'],
                text=f"價格: NT$ {product['price']}\n{product['description']}",
                actions=[
                    PostbackAction(
                        label='選擇此商品',
                        data=f"select_product:{product['id']}"
                    )
                ]
            )
            columns.append(column)
        
        carousel_template = CarouselTemplate(columns=columns)
        return TemplateSendMessage(
            alt_text='商品目錄',
            template=carousel_template
        )
    
    @staticmethod
    def create_payment_options(product_id):
        """建立付款選項"""
        product = PRODUCTS.get(product_id)
        if not product:
            return TextSendMessage(text="找不到該商品")
        
        quick_reply = QuickReply(items=[
            QuickReplyButton(
                action=PostbackAction(
                    label='LINE Pay 付款',
                    data=f"payment:linepay:{product_id}"
                )
            ),
            QuickReplyButton(
                action=PostbackAction(
                    label='信用卡付款',
                    data=f"payment:creditcard:{product_id}"
                )
            )
        ])
        
        return TextSendMessage(
            text=f"您選擇了：{product['name']}\n價格：NT$ {product['price']}\n\n請選擇付款方式：",
            quick_reply=quick_reply
        )
    
    @staticmethod
    def create_instructions():
        """建立使用說明"""
        instructions = """🌺 Polly 花藝店 使用說明 🌺

📋 功能介紹：
• 商品目錄 - 查看所有花束商品
• LINE Pay 付款 - 使用 LINE Pay 快速付款
• 信用卡付款 - 透過綠界科技安全付款

💳 付款方式：
1. LINE Pay - 直接使用 LINE 帳戶付款
2. 信用卡 - 支援各大信用卡

🛒 購買流程：
1. 輸入「商品目錄」瀏覽商品
2. 點選「選擇此商品」
3. 選擇付款方式
4. 完成付款

❓ 需要協助請聯繫客服
📞 電話：02-1234-5678
🕒 營業時間：09:00-21:00"""
        
        return TextSendMessage(text=instructions)

# LINE Bot Webhook
@app.route("/webhook", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    
    return 'OK'

# 處理文字訊息
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_id = event.source.user_id
    text = event.message.text
    
    try:
        if text in ['商品目錄', '開始購物', '看商品']:
            reply_message = MessageHandler.create_product_catalog()
        elif text in ['使用說明', '說明', '幫助']:
            reply_message = MessageHandler.create_instructions()
        elif text.lower() == 'hello' or text == '你好':
            reply_message = TextSendMessage(
                text="歡迎來到 Polly 花藝店！🌺\n\n請輸入「商品目錄」查看商品\n或輸入「使用說明」了解功能"
            )
        else:
            reply_message = TextSendMessage(
                text="歡迎來到 Polly 花藝店！🌺\n\n請輸入「商品目錄」查看商品\n或輸入「使用說明」了解功能"
            )
        
        line_bot_api.reply_message(event.reply_token, reply_message)
        
    except LineBotApiError as e:
        print(f"LINE Bot API 錯誤: {e}")

# 處理 Postback 事件
@handler.add(PostbackEvent)
def handle_postback(event):
    user_id = event.source.user_id
    data = event.postback.data
    
    try:
        if data.startswith('select_product:'):
            product_id = data.split(':')[1]
            reply_message = MessageHandler.create_payment_options(product_id)
            line_bot_api.reply_message(event.reply_token, reply_message)
            
        elif data.startswith('payment:'):
            parts = data.split(':')
            payment_method = parts[1]
            product_id = parts[2]
            
            product = PRODUCTS.get(product_id)
            if not product:
                reply_message = TextSendMessage(text="找不到該商品")
            else:
                if payment_method == 'linepay':
                    payment_url, error = PaymentProcessor.create_linepay_payment(product_id, user_id)
                    if payment_url:
                        buttons_template = ButtonsTemplate(
                            title='LINE Pay 付款',
                            text=f"商品：{product['name']}\n金額：NT$ {product['price']}",
                            actions=[
                                URIAction(label='前往付款', uri=payment_url)
                            ]
                        )
                        reply_message = TemplateSendMessage(
                            alt_text='LINE Pay 付款',
                            template=buttons_template
                        )
                    else:
                        reply_message = TextSendMessage(text=f"付款處理發生錯誤：{error}")
                
                elif payment_method == 'creditcard':
                    payment_url, error = PaymentProcessor.create_ecpay_payment(product_id, user_id)
                    if payment_url:
                        buttons_template = ButtonsTemplate(
                            title='信用卡付款',
                            text=f"商品：{product['name']}\n金額：NT$ {product['price']}",
                            actions=[
                                URIAction(label='前往付款', uri=payment_url)
                            ]
                        )
                        reply_message = TemplateSendMessage(
                            alt_text='信用卡付款',
                            template=buttons_template
                        )
                    else:
                        reply_message = TextSendMessage(text=f"付款處理發生錯誤：{error}")
            
            line_bot_api.reply_message(event.reply_token, reply_message)
    
    except LineBotApiError as e:
        print(f"LINE Bot API 錯誤: {e}")

# 信用卡付款頁面
@app.route('/payment/creditcard/<order_id>')
def creditcard_payment(order_id):
    trade_info = payment_forms.get(order_id)
    if not trade_info:
        return "付款連結已失效", 404
    
    # 生成表單 HTML
    form_inputs = ""
    for key, value in trade_info.items():
        form_inputs += f'<input type="hidden" name="{key}" value="{value}">\n'
    
    html_template = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>信用卡付款 - Polly 花藝店</title>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            body {{ font-family: Arial, sans-serif; text-align: center; padding: 50px; }}
            .loading {{ font-size: 18px; color: #666; }}
        </style>
    </head>
    <body>
        <div class="loading">
            <h2>🌺 Polly 花藝店</h2>
            <p>正在轉跳至安全付款頁面...</p>
            <p>請稍候，不要關閉此頁面</p>
        </div>
        
        <form id="ecpay-form" method="post" action="{ECPAY_CONFIG['payment_url']}">
            {form_inputs}
        </form>
        
        <script>
            setTimeout(function() {{
                document.getElementById('ecpay-form').submit();
            }}, 2000);
        </script>
    </body>
    </html>
    """
    
    return html_template

# LINE Pay 確認付款
@app.route('/linepay/confirm')
def linepay_confirm():
    transaction_id = request.args.get('transactionId')
    order_id = request.args.get('orderId')
    
    if not transaction_id or not order_id:
        return "參數錯誤", 400
    
    order_info = orders.get(order_id)
    if not order_info:
        return "訂單不存在", 404
    
    try:
        # 確認付款
        confirm_data = {
            "amount": order_info['amount'],
            "currency": "TWD"
        }
        
        uri = f"/v3/payments/{transaction_id}/confirm"
        nonce = str(int(time.time() * 1000))
        request_body_json = json.dumps(confirm_data, separators=(',', ':'))
        
        signature = PaymentProcessor.generate_linepay_signature(
            LINEPAY_CONFIG['channel_secret'],
            uri,
            request_body_json,
            nonce
        )
        
        headers = {
            'Content-Type': 'application/json',
            'X-LINE-ChannelId': LINEPAY_CONFIG['channel_id'],
            'X-LINE-Authorization-Nonce': nonce,
            'X-LINE-Authorization': signature
        }
        
        response = requests.post(
            f"{LINEPAY_CONFIG['api_url']}{uri}",
            data=request_body_json,
            headers=headers
        )
        
        response_data = response.json()
        
        if response_data.get('returnCode') == '0000':
            # 更新訂單狀態
            orders[order_id]['status'] = 'paid'
            orders[order_id]['transaction_id'] = transaction_id
            
            product = PRODUCTS.get(order_info['product_id'])
            
            return f"""
            <html>
            <head>
                <title>付款成功 - Polly 花藝店</title>
                <meta charset="UTF-8">
                <style>
                    body {{ font-family: Arial, sans-serif; text-align: center; padding: 50px; }}
                    .success {{ color: #28a745; }}
                </style>
            </head>
            <body>
                <h2 class="success">🌺 付款成功！</h2>
                <p>訂單編號：{order_id}</p>
                <p>商品：{product['name'] if product else '未知商品'}</p>
                <p>金額：NT$ {order_info['amount']}</p>
                <p>感謝您的購買，我們會盡快為您準備商品！</p>
                <script>
                    setTimeout(() => {{
                        window.close();
                    }}, 5000);
                </script>
            </body>
            </html>
            """
        else:
            return f"付款確認失敗: {response_data.get('returnMessage', '未知錯誤')}", 400
            
    except Exception as e:
        return f"付款處理發生錯誤: {str(e)}", 500

# LINE Pay 取消付款
@app.route('/linepay/cancel')
def linepay_cancel():
    return """
    <html>
    <head>
        <title>付款取消 - Polly 花藝店</title>
        <meta charset="UTF-8">
        <style>
            body { font-family: Arial, sans-serif; text-align: center; padding: 50px; }
            .cancel { color: #dc3545; }
        </style>
    </head>
    <body>
        <h2 class="cancel">付款已取消</h2>
        <p>如有任何問題，請聯繫客服</p>
        <script>
            setTimeout(() => {
                window.close();
            }, 3000);
        </script>
    </body>
    </html>
    """

# ECPay 付款結果通知
@app.route('/ecpay/return', methods=['POST'])
def ecpay_return():
    form_data = request.form.to_dict()
    
    rtn_code = form_data.get('RtnCode')
    merchant_trade_no = form_data.get('MerchantTradeNo')
    trade_amt = form_data.get('TradeAmt')
    
    if rtn_code == '1':  # 付款成功
        if merchant_trade_no in orders:
            orders[merchant_trade_no]['status'] = 'paid'
            print(f"訂單 {merchant_trade_no} 付款成功，金額：{trade_amt}")
    
    return '1|OK'  # 必須回應 1|OK

# ECPay 用戶返回頁面
@app.route('/ecpay/client_back')
def ecpay_client_back():
    return """
    <html>
    <head>
        <title>付款完成 - Polly 花藝店</title>
        <meta charset="UTF-8">
        <style>
            body { font-family: Arial, sans-serif; text-align: center; padding: 50px; }
            .success { color: #28a745; }
        </style>
    </head>
    <body>
        <h2 class="success">🌺 感謝您的購買！</h2>
        <p>付款處理中，請稍候...</p>
        <p>我們會盡快為您準備商品！</p>
    </body>
    </html>
    """

# 健康檢查
@app.route('/health')
def health_check():
    return {'status': 'healthy', 'timestamp': datetime.now().isoformat()}

# 主程式
if __name__ == "__main__":
    port = int(os.getenv('PORT', 9000))
    debug_mode = os.getenv('FLASK_ENV') == 'development'
    
    print(f"🌺 Polly 花藝店 LINE Bot 啟動中...")
    print(f"📡 監聽 Port: {port}")
    print(f"🔧 Debug 模式: {debug_mode}")
    
    app.run(host='0.0.0.0', port=port, debug=debug_mode)
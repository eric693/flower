from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import (
    MessageEvent, TextMessage, TextSendMessage,
    StickerMessage, StickerSendMessage,
    QuickReply, QuickReplyButton, MessageAction,
    FlexSendMessage, BubbleContainer, BoxComponent,
    TextComponent, SeparatorComponent, ButtonComponent,
    URIAction, PostbackAction, PostbackEvent
)
import os
import random
import sqlite3
import datetime
import secrets
import string

app = Flask(__name__)

# Line Bot 設定 - 請替換為你的實際值
LINE_CHANNEL_ACCESS_TOKEN = 'NHv54nNB1d2yFR5rhfjvRIcKR8DtM+g/H2kXkVrPRJeeQrOKoM5ezA8HnnoGIm+iUHRYTLtMxa10Lr5Irems1wb6YQSOMCkJb+8oSwyOt5DdJs/gmuaC5gTz689eCXoCJFJIYLiQY/9EeYB+Ox+WHQdB04t89/1O/w1cDnyilFU='
LINE_CHANNEL_SECRET = '0a486d77dd9aea4bb56500ca7d0661be'

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# 管理員 LINE User ID（請替換為實際的管理員 LINE User ID）
# ADMIN_USER_IDS = ['Ud956df5564ad0c77eb2f849db0eccfeb','U215dfe5f0cdc8c5ddd970a5d2fb4b288']  # 可以設定多個管理員
ADMIN_USER_IDS = ['Ud956df5564ad0c77eb2f849db0eccfeb', 'Ud9d0c5237f9e5ec662d050328efe51b0']
# 初始化資料庫
def init_database():
    conn = sqlite3.connect('appointments.db')
    cursor = conn.cursor()
    
    # 創建預約表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS appointments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            appointment_number TEXT UNIQUE NOT NULL,
            user_id TEXT NOT NULL,
            customer_name TEXT NOT NULL,
            phone TEXT NOT NULL,
            pickup_date TEXT NOT NULL,
            pickup_time TEXT NOT NULL,
            order_details TEXT,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # 創建管理員日誌表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS admin_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            admin_id TEXT NOT NULL,
            action TEXT NOT NULL,
            appointment_number TEXT,
            details TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # 創建完成取花記錄表（用於保存已完成的預約記錄）
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS completed_appointments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            appointment_number TEXT NOT NULL,
            user_id TEXT NOT NULL,
            customer_name TEXT NOT NULL,
            phone TEXT NOT NULL,
            pickup_date TEXT NOT NULL,
            pickup_time TEXT NOT NULL,
            order_details TEXT,
            completed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            completed_by TEXT NOT NULL
        )
    ''')
    
    conn.commit()
    conn.close()

# 生成預約編號
def generate_appointment_number():
    # 格式：FL + 年月日 + 4位隨機碼
    date_str = datetime.datetime.now().strftime("%Y%m%d")
    random_code = ''.join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(4))
    return f"FL{date_str}{random_code}"

# 檢查是否為管理員
def is_admin(user_id):
    return user_id in ADMIN_USER_IDS

# 保存預約資料
def save_appointment(user_id, name, phone, pickup_date, pickup_time, order_details=""):
    conn = sqlite3.connect('appointments.db')
    cursor = conn.cursor()
    
    appointment_number = generate_appointment_number()
    
    # 確保預約編號唯一
    while True:
        cursor.execute('SELECT id FROM appointments WHERE appointment_number = ?', (appointment_number,))
        if cursor.fetchone() is None:
            break
        appointment_number = generate_appointment_number()
    
    cursor.execute('''
        INSERT INTO appointments 
        (appointment_number, user_id, customer_name, phone, pickup_date, pickup_time, order_details)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (appointment_number, user_id, name, phone, pickup_date, pickup_time, order_details))
    
    conn.commit()
    conn.close()
    
    return appointment_number

# 查詢預約資料 - 支援編號、姓名、日期查詢
def search_appointments(query):
    conn = sqlite3.connect('appointments.db')
    cursor = conn.cursor()
    
    results = []
    query = query.strip()  # 移除前後空白
    
    # 嘗試用預約編號查詢（精確匹配和模糊匹配）
    cursor.execute('SELECT * FROM appointments WHERE appointment_number = ?', (query,))
    result = cursor.fetchone()
    if result:
        results.append(result)
    
    # 如果沒找到，嘗試預約編號的模糊查詢
    if not results and len(query) >= 4:
        cursor.execute('SELECT * FROM appointments WHERE appointment_number LIKE ?', (f'%{query}%',))
        results = cursor.fetchall()
    
    # 如果沒找到，嘗試用姓名查詢（模糊搜尋）
    if not results:
        cursor.execute('SELECT * FROM appointments WHERE customer_name LIKE ?', (f'%{query}%',))
        results = cursor.fetchall()
    
    # 如果還是沒找到，嘗試用日期查詢
    if not results:
        # 檢查是否為日期格式
        try:
            # 支援多種日期格式
            date_formats = ['%Y-%m-%d', '%Y/%m/%d', '%m-%d', '%m/%d']
            parsed_date = None
            
            for fmt in date_formats:
                try:
                    if fmt in ['%m-%d', '%m/%d']:
                        # 如果只有月日，補上當前年份
                        current_year = datetime.datetime.now().year
                        full_date = f"{current_year}-{query}" if '-' in query else f"{current_year}/{query}"
                        parsed_date = datetime.datetime.strptime(full_date, f"%Y{fmt}")
                    else:
                        parsed_date = datetime.datetime.strptime(query, fmt)
                    break
                except ValueError:
                    continue
            
            if parsed_date:
                search_date = parsed_date.strftime('%Y-%m-%d')
                cursor.execute('SELECT * FROM appointments WHERE pickup_date = ?', (search_date,))
                results = cursor.fetchall()
        except:
            pass
    
    # 如果還是沒找到，嘗試用電話號碼查詢
    if not results:
        cursor.execute('SELECT * FROM appointments WHERE phone LIKE ?', (f'%{query}%',))
        results = cursor.fetchall()
    
    conn.close()
    
    # 轉換結果為字典格式
    appointments = []
    for result in results:
        appointments.append({
            'id': result[0],
            'appointment_number': result[1],
            'user_id': result[2],
            'customer_name': result[3],
            'phone': result[4],
            'pickup_date': result[5],
            'pickup_time': result[6],
            'order_details': result[7],
            'status': result[8],
            'created_at': result[9],
            'updated_at': result[10]
        })
    
    return appointments

# 新增：檢查資料庫內容的函數（除錯用）
def debug_check_appointments():
    """檢查資料庫中的所有預約資料"""
    conn = sqlite3.connect('appointments.db')
    cursor = conn.cursor()
    
    cursor.execute('SELECT appointment_number, customer_name, pickup_date FROM appointments')
    results = cursor.fetchall()
    
    conn.close()
    return results

# 查詢所有預約（管理員用）- 只顯示進行中的預約
def get_all_appointments(status=None):
    conn = sqlite3.connect('appointments.db')
    cursor = conn.cursor()
    
    if status:
        cursor.execute('SELECT * FROM appointments WHERE status = ? ORDER BY pickup_date, pickup_time', (status,))
    else:
        cursor.execute('SELECT * FROM appointments ORDER BY pickup_date, pickup_time')
    
    results = cursor.fetchall()
    conn.close()
    
    appointments = []
    for result in results:
        appointments.append({
            'id': result[0],
            'appointment_number': result[1],
            'user_id': result[2],
            'customer_name': result[3],
            'phone': result[4],
            'pickup_date': result[5],
            'pickup_time': result[6],
            'order_details': result[7],
            'status': result[8],
            'created_at': result[9],
            'updated_at': result[10]
        })
    
    return appointments

# 完成取花並刪除預約（新增功能）
def complete_appointment(appointment_number, admin_id):
    conn = sqlite3.connect('appointments.db')
    cursor = conn.cursor()
    
    try:
        # 先取得預約資料
        cursor.execute('SELECT * FROM appointments WHERE appointment_number = ?', (appointment_number,))
        appointment_data = cursor.fetchone()
        
        if not appointment_data:
            conn.close()
            return False, "找不到預約資料"
        
        # 將預約資料移到完成記錄表
        cursor.execute('''
            INSERT INTO completed_appointments 
            (appointment_number, user_id, customer_name, phone, pickup_date, pickup_time, order_details, completed_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            appointment_data[1],  # appointment_number
            appointment_data[2],  # user_id
            appointment_data[3],  # customer_name
            appointment_data[4],  # phone
            appointment_data[5],  # pickup_date
            appointment_data[6],  # pickup_time
            appointment_data[7],  # order_details
            admin_id              # completed_by
        ))
        
        # 從原預約表中刪除該筆資料
        cursor.execute('DELETE FROM appointments WHERE appointment_number = ?', (appointment_number,))
        
        # 記錄管理員操作
        cursor.execute('''
            INSERT INTO admin_logs (admin_id, action, appointment_number, details)
            VALUES (?, ?, ?, ?)
        ''', (admin_id, '完成取花', appointment_number, f'預約 {appointment_number} 已完成取花並從系統中移除'))
        
        conn.commit()
        conn.close()
        return True, "預約已完成並移除"
        
    except Exception as e:
        conn.rollback()
        conn.close()
        return False, f"操作失敗: {str(e)}"

# 更新預約狀態（確認預約或取消預約）
def update_appointment_status(appointment_number, status, admin_id):
    conn = sqlite3.connect('appointments.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        UPDATE appointments 
        SET status = ?, updated_at = CURRENT_TIMESTAMP 
        WHERE appointment_number = ?
    ''', (status, appointment_number))
    
    # 記錄管理員操作
    cursor.execute('''
        INSERT INTO admin_logs (admin_id, action, appointment_number, details)
        VALUES (?, ?, ?, ?)
    ''', (admin_id, f'更新狀態為{status}', appointment_number, f'預約 {appointment_number} 狀態更新為 {status}'))
    
    conn.commit()
    conn.close()

# 查詢已完成的預約記錄（新增功能）
def get_completed_appointments(limit=50):
    conn = sqlite3.connect('appointments.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT * FROM completed_appointments 
        ORDER BY completed_at DESC 
        LIMIT ?
    ''', (limit,))
    
    results = cursor.fetchall()
    conn.close()
    
    completed_appointments = []
    for result in results:
        completed_appointments.append({
            'id': result[0],
            'appointment_number': result[1],
            'user_id': result[2],
            'customer_name': result[3],
            'phone': result[4],
            'pickup_date': result[5],
            'pickup_time': result[6],
            'order_details': result[7],
            'completed_at': result[8],
            'completed_by': result[9]
        })
    
    return completed_appointments

# 花材知識庫
flower_knowledge = {
    "永生花": {
        "definition": "永生花（Preserved Flower）是真花，經過脫水、脫色、保鮮液置換與上色等專業技術，將花朵最美的狀態「定格」下來。它保留了柔軟的觸感與細膩的花型，不需澆水或日曬，也能長久綻放",
        "preservation": "1–3 年（依環境而異）",
        "features": "柔軟、色彩多變、質感高級",
        "care": "乾燥、防潮、防陽光直射"
    },
    "乾燥花": {
        "definition": "乾燥花是將鮮花的水分以自然風乾、烘乾等方式去除，保留花的輪廓與自然色澤。時間會讓顏色變得柔和、霧感，帶有一點復古氣息",
        "preservation": "半年～1 年（依環境而異）",
        "features": "自然香氣、復古色調、質地較脆",
        "care": "防潮、防壓，不要頻繁觸碰"
    },
    "索拉花": {
        "definition": "索拉花是以「索拉木」的莖髓手工雕刻而成的花瓣，質地輕盈、柔軟，外觀細膩，常用於香氛花藝。它能吸收香氛精油，成為擴香花。",
        "preservation": "多年（屬手作花材，不會腐壞）",
        "features": "可吸香氛、重量輕、造型可塑性高",
        "care": "避免重壓與潮濕，若需加香可滴少量精油在背面"
    }
}

# 服務相關資訊
service_info = {
    "客製": "當然可以。只要告訴我喜歡的色系、花材、大小、預算，或是想傳遞的故事與心意，我都會為你設計一份專屬的花禮",
    "製作時間": "一般 3–7 個工作天，若有急件請提前告訴我",
    "卡片": "可以，請把想說的話交給我，我會用印製的方式，替你溫柔送達",
    "卡片詢問": "💌 請告訴我您想在卡片上寫的內容，我會幫您印製並隨花禮一起送達～",
    "店面": "目前我們是工作室採預約制，主要以課程教學與花禮製作為主。如果想來取花或參觀作品，可以先私訊預約時間",
    "外送": "有的，我們提供宅配與快遞服務，全台都能寄送。新竹市區可視情況安排專人外送",
    "宅配": "可以，全台皆可宅配，部分大型作品建議快遞或面交",
    "自取": "可以提前預約時間，工作室取貨，我會把花禮準備好等你",
    "送達時間": "一般 1–3 天到貨，節日或連假可能稍久，建議提早預訂",
    "課程基礎": "當然可以，我會一步步帶你完成，讓你帶著作品和笑容回家",
    "課程時間": "採預約制，我們會依你的時間安排課程，彈性又輕鬆",
    "課程材料": "不用，當天我會準備好所有花材與工具，你只需要帶著好心情來就好",
    "有開課": "有的！我們提供花藝課程教學，採預約制。無論你是零基礎新手還是想精進技巧，我們都會根據你的需求設計合適的課程內容喔！"
}

# 定義回應貼圖（使用 LINE 官方免費貼圖）
response_stickers = [
    {"packageId": "11537", "stickerId": "52002734"},  # OK手勢
    {"packageId": "11537", "stickerId": "52002735"},  # 謝謝
    {"packageId": "11537", "stickerId": "52002739"},  # 笑臉
    {"packageId": "11537", "stickerId": "52002740"},  # 愛心
    {"packageId": "11538", "stickerId": "51626494"},  # 讚
    {"packageId": "11538", "stickerId": "51626495"},  # 開心
]

# 回應貼圖的文字
sticker_response_texts = [
    "😊 收到您的貼圖了！有什麼需要協助的嗎？",
    "🌸 謝謝您的貼圖～需要什麼服務呢？",
    "😄 好可愛！讓我為您介紹花材服務吧！",
    "💝 感謝！有任何花藝相關問題都可以問我喔！"
]

# 用戶狀態追蹤
user_states = {}

def create_main_menu():
    """建立主選單快速回覆按鈕"""
    quick_reply = QuickReply(items=[
        QuickReplyButton(action=MessageAction(label="🌹 花材介紹", text="花材介紹")),
        QuickReplyButton(action=MessageAction(label="🎨 客製服務", text="客製服務")),
        QuickReplyButton(action=MessageAction(label="🚚 運送取貨", text="運送取貨")),
        QuickReplyButton(action=MessageAction(label="📚 花藝課程", text="花藝課程")),
        QuickReplyButton(action=MessageAction(label="📅 預約取花", text="預約取花")),
    ])
    return quick_reply

def create_admin_menu():
    """建立管理員選單"""
    quick_reply = QuickReply(items=[
        QuickReplyButton(action=MessageAction(label="📋 查看所有預約", text="查看所有預約")),
        QuickReplyButton(action=MessageAction(label="🔍 查詢預約", text="查詢預約")),
        QuickReplyButton(action=MessageAction(label="⏰ 今日預約", text="今日預約")),
        QuickReplyButton(action=MessageAction(label="📝 已完成記錄", text="已完成記錄")),
        QuickReplyButton(action=MessageAction(label="🔧 檢查資料庫", text="檢查資料庫")),
        QuickReplyButton(action=MessageAction(label="🔙 回主選單", text="主選單")),
    ])
    return quick_reply

def create_flower_menu():
    """建立花材選單"""
    quick_reply = QuickReply(items=[
        QuickReplyButton(action=MessageAction(label="🌹 永生花", text="永生花")),
        QuickReplyButton(action=MessageAction(label="🌾 乾燥花", text="乾燥花")),
        QuickReplyButton(action=MessageAction(label="🌸 索拉花", text="索拉花")),
        QuickReplyButton(action=MessageAction(label="📊 三者比較", text="三者比較")),
        QuickReplyButton(action=MessageAction(label="🔙 回主選單", text="主選單")),
    ])
    return quick_reply

def create_service_menu():
    """建立服務選單"""
    quick_reply = QuickReply(items=[
        QuickReplyButton(action=MessageAction(label="🎨 客製設計", text="客製設計")),
        QuickReplyButton(action=MessageAction(label="⏰ 製作時間", text="製作時間")),
        QuickReplyButton(action=MessageAction(label="💌 附卡片", text="卡片服務")),
        QuickReplyButton(action=MessageAction(label="🔙 回主選單", text="主選單")),
    ])
    return quick_reply

def create_delivery_menu():
    """建立運送選單"""
    quick_reply = QuickReply(items=[
        QuickReplyButton(action=MessageAction(label="🏪 店面資訊", text="店面")),
        QuickReplyButton(action=MessageAction(label="🚚 外送服務", text="外送")),
        QuickReplyButton(action=MessageAction(label="📦 宅配服務", text="宅配")),
        QuickReplyButton(action=MessageAction(label="🏃 自取服務", text="自取")),
        QuickReplyButton(action=MessageAction(label="📅 預約取花", text="預約取花")),
        QuickReplyButton(action=MessageAction(label="🔙 回主選單", text="主選單")),
    ])
    return quick_reply

def create_course_menu():
    """建立課程選單"""
    quick_reply = QuickReply(items=[
        QuickReplyButton(action=MessageAction(label="👶 零基礎", text="零基礎課程")),
        QuickReplyButton(action=MessageAction(label="📅 課程時間", text="課程時間")),
        QuickReplyButton(action=MessageAction(label="🛠️ 課程材料", text="課程材料")),
        QuickReplyButton(action=MessageAction(label="🔙 回主選單", text="主選單")),
    ])
    return quick_reply

def create_appointment_confirmation_flex(appointment_data):
    """建立預約確認的 Flex Message"""
    bubble = BubbleContainer(
        body=BoxComponent(
            layout="vertical",
            contents=[
                TextComponent(
                    text="✅ 預約確認",
                    weight="bold",
                    size="xl",
                    color="#1DB446"
                ),
                SeparatorComponent(margin="md"),
                TextComponent(
                    text=f"預約編號：{appointment_data['appointment_number']}",
                    weight="bold",
                    size="md",
                    margin="lg",
                    color="#FF6B35"
                ),
                TextComponent(
                    text=f"姓名：{appointment_data['customer_name']}",
                    size="sm",
                    margin="sm"
                ),
                TextComponent(
                    text=f"電話：{appointment_data['phone']}",
                    size="sm",
                    margin="sm"
                ),
                TextComponent(
                    text=f"取花日期：{appointment_data['pickup_date']}",
                    size="sm",
                    margin="sm"
                ),
                TextComponent(
                    text=f"取花時間：{appointment_data['pickup_time']}",
                    size="sm",
                    margin="sm"
                ),
                TextComponent(
                    text=f"訂單內容：{appointment_data.get('order_details', '無特殊要求')}",
                    size="sm",
                    margin="sm",
                    wrap=True
                ),
                SeparatorComponent(margin="lg"),
                TextComponent(
                    text="📝 請記下您的預約編號，取花時請提供此編號。",
                    size="xs",
                    color="#666666",
                    margin="md",
                    wrap=True
                )
            ]
        )
    )
    
    return FlexSendMessage(alt_text="預約確認", contents=bubble)

def create_appointment_detail_flex(appointment):
    """建立預約詳細資訊的 Flex Message（管理員用）"""
    status_color = {
        'pending': '#FF9800',
        'confirmed': '#4CAF50',
        'cancelled': '#F44336'
    }
    
    status_text = {
        'pending': '待確認',
        'confirmed': '已確認',
        'cancelled': '已取消'
    }
    
    bubble = BubbleContainer(
        body=BoxComponent(
            layout="vertical",
            contents=[
                TextComponent(
                    text="📋 預約詳情",
                    weight="bold",
                    size="xl",
                    color="#1DB446"
                ),
                SeparatorComponent(margin="md"),
                TextComponent(
                    text=f"編號：{appointment['appointment_number']}",
                    weight="bold",
                    size="md",
                    margin="lg",
                    color="#FF6B35"
                ),
                TextComponent(
                    text=f"狀態：{status_text.get(appointment['status'], appointment['status'])}",
                    size="sm",
                    margin="sm",
                    color=status_color.get(appointment['status'], '#666666'),
                    weight="bold"
                ),
                TextComponent(
                    text=f"姓名：{appointment['customer_name']}",
                    size="sm",
                    margin="sm"
                ),
                TextComponent(
                    text=f"電話：{appointment['phone']}",
                    size="sm",
                    margin="sm"
                ),
                TextComponent(
                    text=f"取花日期：{appointment['pickup_date']}",
                    size="sm",
                    margin="sm"
                ),
                TextComponent(
                    text=f"取花時間：{appointment['pickup_time']}",
                    size="sm",
                    margin="sm"
                ),
                TextComponent(
                    text=f"訂單內容：{appointment.get('order_details', '無特殊要求')}",
                    size="sm",
                    margin="sm",
                    wrap=True
                ),
                TextComponent(
                    text=f"建立時間：{appointment['created_at']}",
                    size="xs",
                    margin="sm",
                    color="#666666"
                )
            ]
        ),
        footer=BoxComponent(
            layout="vertical",
            contents=[
                ButtonComponent(
                    action=PostbackAction(
                        label="確認預約",
                        data=f"confirm_{appointment['appointment_number']}"
                    ),
                    color="#4CAF50"
                ),
                ButtonComponent(
                    action=PostbackAction(
                        label="✅ 完成取花（刪除記錄）",
                        data=f"complete_{appointment['appointment_number']}"
                    ),
                    color="#2196F3"
                ),
                ButtonComponent(
                    action=PostbackAction(
                        label="取消預約",
                        data=f"cancel_{appointment['appointment_number']}"
                    ),
                    color="#F44336"
                )
            ]
        )
    )
    
    return FlexSendMessage(alt_text="預約詳情", contents=bubble)

def create_flower_detail_flex(flower_type):
    """建立花材詳細資訊的 Flex Message"""
    flower_info = flower_knowledge[flower_type]
    
    bubble = BubbleContainer(
        body=BoxComponent(
            layout="vertical",
            contents=[
                TextComponent(
                    text=f"🌺 {flower_type}",
                    weight="bold",
                    size="xl",
                    color="#1DB446"
                ),
                SeparatorComponent(margin="md"),
                TextComponent(
                    text="📝 介紹",
                    weight="bold",
                    size="md",
                    margin="lg",
                    color="#666666"
                ),
                TextComponent(
                    text=flower_info["definition"],
                    size="sm",
                    wrap=True,
                    margin="sm"
                ),
                TextComponent(
                    text="⏰ 保存時間",
                    weight="bold",
                    size="md",
                    margin="lg",
                    color="#666666"
                ),
                TextComponent(
                    text=flower_info["preservation"],
                    size="sm",
                    margin="sm"
                ),
                TextComponent(
                    text="✨ 特色",
                    weight="bold",
                    size="md",
                    margin="lg",
                    color="#666666"
                ),
                TextComponent(
                    text=flower_info["features"],
                    size="sm",
                    margin="sm"
                ),
                TextComponent(
                    text="🧹 保養",
                    weight="bold",
                    size="md",
                    margin="lg",
                    color="#666666"
                ),
                TextComponent(
                    text=flower_info["care"],
                    size="sm",
                    margin="sm"
                )
            ]
        )
    )
    
    return FlexSendMessage(alt_text=f"{flower_type}詳細資訊", contents=bubble)

def create_comparison_flex():
    """建立三者比較的 Flex Message"""
    bubble = BubbleContainer(
        body=BoxComponent(
            layout="vertical",
            contents=[
                TextComponent(
                    text="🌺 花材比較",
                    weight="bold",
                    size="xl",
                    color="#1DB446"
                ),
                SeparatorComponent(margin="md"),
                TextComponent(
                    text="🌹 永生花",
                    weight="bold",
                    size="md",
                    margin="lg",
                    color="#E91E63"
                ),
                TextComponent(
                    text="真花保鮮 → 柔軟、色澤飽和、高級感",
                    size="sm",
                    margin="sm"
                ),
                TextComponent(
                    text="🌾 乾燥花",
                    weight="bold",
                    size="md",
                    margin="lg",
                    color="#8BC34A"
                ),
                TextComponent(
                    text="真花風乾 → 自然霧感、復古氣息",
                    size="sm",
                    margin="sm"
                ),
                TextComponent(
                    text="🌸 索拉花",
                    weight="bold",
                    size="md",
                    margin="lg",
                    color="#FF9800"
                ),
                TextComponent(
                    text="植物莖髓手工雕刻 → 可吸香氛、造型多變",
                    size="sm",
                    margin="sm"
                )
            ]
        )
    )
    
    return FlexSendMessage(alt_text="花材比較", contents=bubble)

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    app.logger.info("Request body: " + body)
    
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        print("Invalid signature. Please check your channel access token/channel secret.")
        abort(400)
    
    return 'OK'

@handler.add(PostbackEvent)
def handle_postback(event):
    """處理 Postback 事件（管理員操作）"""
    user_id = event.source.user_id
    postback_data = event.postback.data
    
    # 檢查是否為管理員
    if not is_admin(user_id):
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="❌ 您沒有管理員權限")
        )
        return
    
    # 解析操作類型和預約編號
    if '_' in postback_data:
        action, appointment_number = postback_data.split('_', 1)
        
        if action == 'confirm':
            update_appointment_status(appointment_number, 'confirmed', user_id)
            reply_text = f"✅ 預約 {appointment_number} 已確認"
        elif action == 'complete':
            # 使用新的完成取花功能（刪除記錄）
            success, message = complete_appointment(appointment_number, user_id)
            if success:
                reply_text = f"🎉 預約 {appointment_number} 已完成取花，記錄已從系統中移除"
            else:
                reply_text = f"❌ 操作失敗：{message}"
        elif action == 'cancel':
            update_appointment_status(appointment_number, 'cancelled', user_id)
            reply_text = f"❌ 預約 {appointment_number} 已取消"
        else:
            reply_text = "❌ 未知的操作"
        
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=reply_text, quick_reply=create_admin_menu())
        )

@handler.add(MessageEvent, message=StickerMessage)
def handle_sticker_message(event):
    """處理用戶發送的貼圖訊息"""
    # 隨機選擇一個回應貼圖
    response_sticker = random.choice(response_stickers)
    
    # 隨機選擇一個回應文字
    response_text = random.choice(sticker_response_texts)
    
    # 回覆貼圖和文字
    line_bot_api.reply_message(
        event.reply_token,
        [
            StickerSendMessage(
                package_id=response_sticker["packageId"],
                sticker_id=response_sticker["stickerId"]
            ),
            TextSendMessage(
                text=response_text,
                quick_reply=create_main_menu()
            )
        ]
    )

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_message = event.message.text.strip()
    user_id = event.source.user_id
    
    # 檢查用戶狀態
    if user_id in user_states:
        state = user_states[user_id]
        
        # 處理卡片內容輸入
        if state == "waiting_card_content":
            card_content = user_message
            del user_states[user_id]
            
            reply_text = f"✅ 已收到您的卡片內容：\n\n「{card_content}」\n\n💌 我會用印製的方式，替您溫柔送達這份心意～\n\n還有其他需要協助的嗎？"
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text=reply_text, quick_reply=create_main_menu())
            )
            return
        
        # 處理預約流程
        elif state == "waiting_name":
            user_states[user_id] = {"step": "waiting_phone", "name": user_message}
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text="📱 請提供您的聯絡電話：")
            )
            return
        
        elif isinstance(state, dict) and state.get("step") == "waiting_phone":
            user_states[user_id]["phone"] = user_message
            user_states[user_id]["step"] = "waiting_date"
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text="📅 請提供您希望的取花日期（格式：YYYY-MM-DD，例如：2025-08-20）：")
            )
            return
        
        elif isinstance(state, dict) and state.get("step") == "waiting_date":
            # 驗證日期格式
            try:
                pickup_date = datetime.datetime.strptime(user_message, "%Y-%m-%d").date()
                today = datetime.date.today()
                if pickup_date < today:
                    line_bot_api.reply_message(
                        event.reply_token,
                        TextSendMessage(text="❌ 取花日期不能是過去的日期，請重新輸入：")
                    )
                    return
                
                user_states[user_id]["pickup_date"] = user_message
                user_states[user_id]["step"] = "waiting_time"
                line_bot_api.reply_message(
                    event.reply_token,
                    TextSendMessage(text="🕐 請提供您希望的取花時間（格式：HH:MM，例如：14:30）：")
                )
                return
            except ValueError:
                line_bot_api.reply_message(
                    event.reply_token,
                    TextSendMessage(text="❌ 日期格式錯誤，請使用 YYYY-MM-DD 格式（例如：2025-08-20）：")
                )
                return
        
        elif isinstance(state, dict) and state.get("step") == "waiting_time":
            # 驗證時間格式
            try:
                datetime.datetime.strptime(user_message, "%H:%M")
                user_states[user_id]["pickup_time"] = user_message
                user_states[user_id]["step"] = "waiting_details"
                line_bot_api.reply_message(
                    event.reply_token,
                    TextSendMessage(text="📝 請說明您的訂單內容或特殊需求（如果沒有特殊要求，請輸入「無」）：")
                )
                return
            except ValueError:
                line_bot_api.reply_message(
                    event.reply_token,
                    TextSendMessage(text="❌ 時間格式錯誤，請使用 HH:MM 格式（例如：14:30）：")
                )
                return
        
        elif isinstance(state, dict) and state.get("step") == "waiting_details":
            order_details = user_message if user_message.lower() != "無" else ""
            
            # 保存預約資料
            appointment_number = save_appointment(
                user_id=user_id,
                name=state["name"],
                phone=state["phone"],
                pickup_date=state["pickup_date"],
                pickup_time=state["pickup_time"],
                order_details=order_details
            )
            
            # 清除用戶狀態
            del user_states[user_id]
            
            # 建立預約確認資料
            appointment_data = {
                "appointment_number": appointment_number,
                "customer_name": state["name"],
                "phone": state["phone"],
                "pickup_date": state["pickup_date"],
                "pickup_time": state["pickup_time"],
                "order_details": order_details if order_details else "無特殊要求"
            }
            
            # 回覆預約確認
            line_bot_api.reply_message(
                event.reply_token,
                [
                    create_appointment_confirmation_flex(appointment_data),
                    TextSendMessage(
                        text="🎉 預約已成功建立！我們會在您指定的時間為您準備好花禮。\n\n如需修改或取消預約，請直接聯繫我們。",
                        quick_reply=create_main_menu()
                    )
                ]
            )
            return
        
        # 處理管理員查詢預約（支援編號、姓名、日期、電話）
        elif state == "admin_search_appointment":
            del user_states[user_id]
            
            if not is_admin(user_id):
                line_bot_api.reply_message(
                    event.reply_token,
                    TextSendMessage(text="❌ 您沒有管理員權限")
                )
                return
            
            appointments = search_appointments(user_message)
            if appointments:
                if len(appointments) == 1:
                    # 只找到一筆，直接顯示詳細資訊
                    line_bot_api.reply_message(
                        event.reply_token,
                        create_appointment_detail_flex(appointments[0])
                    )
                else:
                    # 找到多筆，顯示列表
                    reply_text = f"🔍 找到 {len(appointments)} 筆預約：\n\n"
                    for apt in appointments[:10]:  # 限制顯示前10筆
                        status_emoji = {
                            'pending': '⏳',
                            'confirmed': '✅',
                            'cancelled': '❌'
                        }
                        emoji = status_emoji.get(apt['status'], '❓')
                        reply_text += f"{emoji} {apt['appointment_number']}\n"
                        reply_text += f"   {apt['customer_name']} | {apt['pickup_date']} {apt['pickup_time']}\n"
                        reply_text += f"   📱 {apt['phone']}\n\n"
                    
                    if len(appointments) > 10:
                        reply_text += f"...還有 {len(appointments) - 10} 筆預約\n\n"
                    
                    reply_text += "💡 輸入完整預約編號可查看詳細資訊"
                    
                    line_bot_api.reply_message(
                        event.reply_token,
                        TextSendMessage(text=reply_text, quick_reply=create_admin_menu())
                    )
            else:
                # 查不到資料時，提供更詳細的除錯資訊
                debug_data = debug_check_appointments()
                debug_info = ""
                if debug_data:
                    debug_info = f"\n\n🔧 目前資料庫中有 {len(debug_data)} 筆預約"
                else:
                    debug_info = "\n\n🔧 資料庫中沒有任何預約資料"
                
                line_bot_api.reply_message(
                    event.reply_token,
                    TextSendMessage(
                        text=f"❌ 找不到相關預約：{user_message}\n\n💡 請確認：\n📋 預約編號是否正確\n👤 姓名是否正確\n📅 日期格式（如：2025-08-20）\n📱 電話號碼是否正確{debug_info}",
                        quick_reply=create_admin_menu()
                    )
                )
            return
    
    # 主選單或歡迎訊息
    if user_message in ["主選單", "選單", "menu", "開始", "hi", "hello", "你好"]:
        reply_text = "🌺 歡迎來到花材小百科！\n請選擇你想了解的項目："
        menu = create_admin_menu() if is_admin(user_id) else create_main_menu()
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=reply_text, quick_reply=menu)
        )
    
    # 預約取花功能
    elif user_message == "預約取花":
        user_states[user_id] = "waiting_name"
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="📝 請提供您的姓名：")
        )
    
    # 管理員功能
    elif user_message == "查看所有預約" and is_admin(user_id):
        appointments = get_all_appointments()
        if appointments:
            reply_text = "📋 所有預約列表：\n\n"
            for apt in appointments[:10]:  # 限制顯示前10筆
                status_emoji = {
                    'pending': '⏳',
                    'confirmed': '✅',
                    'cancelled': '❌'
                }
                emoji = status_emoji.get(apt['status'], '❓')
                reply_text += f"{emoji} {apt['appointment_number']}\n"
                reply_text += f"   {apt['customer_name']} | {apt['pickup_date']} {apt['pickup_time']}\n\n"
            
            if len(appointments) > 10:
                reply_text += f"...還有 {len(appointments) - 10} 筆預約"
        else:
            reply_text = "📋 目前沒有預約記錄"
        
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=reply_text, quick_reply=create_admin_menu())
        )
    
    elif user_message == "今日預約" and is_admin(user_id):
        today = datetime.date.today().strftime("%Y-%m-%d")
        appointments = get_all_appointments()
        today_appointments = [apt for apt in appointments if apt['pickup_date'] == today]
        
        if today_appointments:
            reply_text = f"📅 今日預約（{today}）：\n\n"
            for apt in today_appointments:
                status_emoji = {
                    'pending': '⏳',
                    'confirmed': '✅',
                    'cancelled': '❌'
                }
                emoji = status_emoji.get(apt['status'], '❓')
                reply_text += f"{emoji} {apt['appointment_number']}\n"
                reply_text += f"   {apt['customer_name']} | {apt['pickup_time']}\n"
                reply_text += f"   📱 {apt['phone']}\n\n"
        else:
            reply_text = f"📅 今日（{today}）沒有預約"
        
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=reply_text, quick_reply=create_admin_menu())
        )
    
    elif user_message == "查詢預約" and is_admin(user_id):
        user_states[user_id] = "admin_search_appointment"
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="🔍 請輸入要查詢的資訊：\n\n📋 預約編號（如：FL20250816ABCD）\n👤 客戶姓名（如：王小明）\n📅 日期（如：2025-08-20 或 08-20）\n📱 電話號碼（如：0912345678）")
        )
    
    # 新增：除錯功能 - 檢查資料庫內容
    elif user_message == "檢查資料庫" and is_admin(user_id):
        debug_data = debug_check_appointments()
        if debug_data:
            reply_text = "🗄️ 資料庫中的預約資料：\n\n"
            for data in debug_data[:10]:  # 限制顯示前10筆
                reply_text += f"📋 {data[0]}\n👤 {data[1]}\n📅 {data[2]}\n\n"
        else:
            reply_text = "🗄️ 資料庫中沒有預約資料"
        
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=reply_text, quick_reply=create_admin_menu())
        )
    
    # 新增：查看已完成記錄功能
    elif user_message == "已完成記錄" and is_admin(user_id):
        completed_appointments = get_completed_appointments(10)  # 顯示最近10筆
        if completed_appointments:
            reply_text = "📝 最近已完成取花記錄：\n\n"
            for apt in completed_appointments:
                reply_text += f"🎉 {apt['appointment_number']}\n"
                reply_text += f"   {apt['customer_name']} | {apt['pickup_date']} {apt['pickup_time']}\n"
                reply_text += f"   完成時間：{apt['completed_at'][:16]}\n\n"
        else:
            reply_text = "📝 目前沒有已完成的取花記錄"
        
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=reply_text, quick_reply=create_admin_menu())
        )
    
    # 花材介紹
    elif user_message == "花材介紹":
        reply_text = "🌺 想了解哪種花材呢？"
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=reply_text, quick_reply=create_flower_menu())
        )
    
    # 具體花材查詢
    elif user_message in ["永生花", "乾燥花", "索拉花"]:
        line_bot_api.reply_message(
            event.reply_token,
            [
                create_flower_detail_flex(user_message),
                TextSendMessage(text="還想了解其他花材嗎？", quick_reply=create_flower_menu())
            ]
        )
    
    # 三者比較
    elif user_message == "三者比較":
        line_bot_api.reply_message(
            event.reply_token,
            [
                create_comparison_flex(),
                TextSendMessage(text="想了解詳細資訊嗎？", quick_reply=create_flower_menu())
            ]
        )
    
    # 客製服務
    elif user_message == "客製服務":
        reply_text = "🎨 客製服務項目："
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=reply_text, quick_reply=create_service_menu())
        )
    
    elif user_message == "客製設計":
        reply_text = f"🎨 {service_info['客製']}"
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=reply_text, quick_reply=create_service_menu())
        )
    
    elif user_message == "製作時間":
        reply_text = f"⏰ {service_info['製作時間']}"
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=reply_text, quick_reply=create_service_menu())
        )
    
    elif user_message == "卡片服務":
        user_states[user_id] = "waiting_card_content"
        reply_text = service_info['卡片詢問']
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=reply_text)
        )
    
    # 運送取貨
    elif user_message == "運送取貨":
        reply_text = "🚚 運送取貨服務："
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=reply_text, quick_reply=create_delivery_menu())
        )
    
    elif user_message == "店面":
        reply_text = f"🏪 {service_info['店面']}"
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=reply_text, quick_reply=create_delivery_menu())
        )
    
    elif user_message == "外送":
        reply_text = f"🚚 {service_info['外送']}\n\n⏰ {service_info['送達時間']}"
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=reply_text, quick_reply=create_delivery_menu())
        )
    
    elif user_message == "宅配":
        reply_text = f"📦 {service_info['宅配']}\n\n⏰ {service_info['送達時間']}"
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=reply_text, quick_reply=create_delivery_menu())
        )
    
    elif user_message == "自取":
        reply_text = f"🏃 {service_info['自取']}"
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=reply_text, quick_reply=create_delivery_menu())
        )
    
    # 花藝課程
    elif user_message == "花藝課程":
        reply_text = "📚 花藝課程相關："
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=reply_text, quick_reply=create_course_menu())
        )
    
    elif user_message == "零基礎課程":
        reply_text = f"👶 {service_info['課程基礎']}"
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=reply_text, quick_reply=create_course_menu())
        )
    
    elif user_message == "課程時間":
        reply_text = f"📅 {service_info['課程時間']}"
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=reply_text, quick_reply=create_course_menu())
        )
    
    elif user_message == "課程材料":
        reply_text = f"🛠️ {service_info['課程材料']}"
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=reply_text, quick_reply=create_course_menu())
        )
    
    # 其他訊息 - 加入更多模糊匹配
    else:
        # 忽略簡短的確認訊息
        if user_message in ["好", "了解", "知道了", "OK", "ok", "收到", "明白", "懂了", "嗯", "恩", "嗯嗯", "謝謝", "謝謝你", "感謝你"]:
            return  # 不回覆
        
        # 檢查是否包含關鍵字
        if any(keyword in user_message for keyword in ["永生花", "保鮮花"]):
            line_bot_api.reply_message(
                event.reply_token,
                [
                    create_flower_detail_flex("永生花"),
                    TextSendMessage(text="還想了解其他花材嗎？", quick_reply=create_flower_menu())
                ]
            )
        elif any(keyword in user_message for keyword in ["乾燥花", "乾花"]):
            line_bot_api.reply_message(
                event.reply_token,
                [
                    create_flower_detail_flex("乾燥花"),
                    TextSendMessage(text="還想了解其他花材嗎？", quick_reply=create_flower_menu())
                ]
            )
        elif "索拉花" in user_message or "sola" in user_message.lower():
            line_bot_api.reply_message(
                event.reply_token,
                [
                    create_flower_detail_flex("索拉花"),
                    TextSendMessage(text="還想了解其他花材嗎？", quick_reply=create_flower_menu())
                ]
            )
        elif any(keyword in user_message for keyword in ["客製", "定製", "訂製", "客制"]):
            reply_text = f"🎨 {service_info['客製']}"
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text=reply_text, quick_reply=create_service_menu())
            )
        elif any(keyword in user_message for keyword in ["卡片", "附卡", "加卡"]):
            user_states[user_id] = "waiting_card_content"
            reply_text = service_info['卡片詢問']
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text=reply_text)
            )
        elif any(keyword in user_message for keyword in ["時間", "多久", "幾天"]):
            reply_text = f"⏰ {service_info['製作時間']}"
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text=reply_text, quick_reply=create_service_menu())
            )
        elif any(keyword in user_message for keyword in ["店面", "地址", "在哪", "位置"]):
            reply_text = f"🏪 {service_info['店面']}"
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text=reply_text, quick_reply=create_delivery_menu())
            )
        elif any(keyword in user_message for keyword in ["外送", "送達", "配送"]):
            reply_text = f"🚚 {service_info['外送']}\n\n⏰ {service_info['送達時間']}"
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text=reply_text, quick_reply=create_delivery_menu())
            )
        elif any(keyword in user_message for keyword in ["宅配", "郵寄", "寄送"]):
            reply_text = f"📦 {service_info['宅配']}\n\n⏰ {service_info['送達時間']}"
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text=reply_text, quick_reply=create_delivery_menu())
            )
        elif any(keyword in user_message for keyword in ["自取", "取貨", "自己拿"]):
            reply_text = f"🏃 {service_info['自取']}"
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text=reply_text, quick_reply=create_delivery_menu())
            )
        # 預約相關關鍵字 - 只有明確的預約意圖才觸發
        elif any(phrase in user_message for phrase in ["我想預約", "我要預約", "我要預定", "我想預定", "我要預訂", "我想預訂", "幫我預約", "想要預約"]):
            user_states[user_id] = "waiting_name"
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text="📝 好的！讓我為您安排預約取花。\n\n請先提供您的姓名：")
            )
        # 花藝課程相關關鍵字
        elif any(keyword in user_message for keyword in ["花藝課程", "花藝課", "課程", "教學", "學習", "上課", "開課", "有課", "想學", "學花藝"]):
            reply_text = "📚 花藝課程相關："
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text=reply_text, quick_reply=create_course_menu())
            )
        elif any(phrase in user_message for phrase in ["你們有開課嗎", "有沒有開課", "開課嗎", "有開課嗎", "有課程嗎", "開什麼課", "有教課嗎", "有在教嗎", "可以學嗎", "能學花藝嗎"]):
            reply_text = f"📚 {service_info['有開課']}"
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text=reply_text, quick_reply=create_course_menu())
            )
        elif any(keyword in user_message for keyword in ["零基礎", "新手", "初學", "沒經驗", "完全不會", "從零開始"]):
            reply_text = f"👶 {service_info['課程基礎']}"
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text=reply_text, quick_reply=create_course_menu())
            )
        elif any(keyword in user_message for keyword in ["材料", "工具", "準備", "要帶什麼", "需要準備"]):
            reply_text = f"🛠️ {service_info['課程材料']}"
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text=reply_text, quick_reply=create_course_menu())
            )
        elif any(keyword in user_message for keyword in ["訂花", "花束", "買花束", "買花", "花禮", "訂購", "購買", "花"]):
            reply_text = "🌸 沒問題呀～你想要現貨款還是訂製款呢？\n\n🛍️ 現貨款：現有作品，可立即取貨\n🎨 訂製款：專屬設計，3-7個工作天完成\n\n歡迎告訴我你的需求！"
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text=reply_text, quick_reply=create_service_menu())
            )
        elif any(keyword in user_message for keyword in ["價格", "價錢", "費用", "多少錢", "收費"]):
            reply_text = "💰 關於價格資訊，因為每個作品的花材、大小、複雜度不同，建議您直接私訊告訴我們您的需求，我們會為您提供詳細的報價喔！"
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text=reply_text, quick_reply=create_main_menu())
            )
        else:
            reply_text = "不好意思，我沒有理解您的問題🥹\n您可以使用下方選單查詢，或輸入「主選單」重新開始～"
            menu = create_admin_menu() if is_admin(user_id) else create_main_menu()
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text=reply_text, quick_reply=menu)
            )

if __name__ == "__main__":
    # 初始化資料庫
    init_database()
    
    port = int(os.environ.get('PORT', 7000))
    app.run(host='0.0.0.0', port=port, debug=True)
import os
import json
import base64
import asyncio
import time
import functools
import websockets
from fastapi import FastAPI, WebSocket, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.websockets import WebSocketDisconnect
from twilio.twiml.voice_response import VoiceResponse, Connect, Say, Stream
from dotenv import load_dotenv
from twilio.rest import Client

load_dotenv()

# Performans ölçüm dekoratörü
def performance_monitor(func):
    if asyncio.iscoroutinefunction(func):
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            start_time = time.perf_counter()
            result = await func(*args, **kwargs)
            elapsed = time.perf_counter() - start_time
            print(f"[PERF] {func.__name__} took {elapsed:.4f} seconds")
            return result
        return async_wrapper
    else:
        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            start_time = time.perf_counter()
            result = func(*args, **kwargs)
            elapsed = time.perf_counter() - start_time
            print(f"[PERF] {func.__name__} took {elapsed:.4f} seconds")
            return result
        return sync_wrapper

# Konfigürasyon
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')
TWILIO_ACCOUNT_SID = os.getenv('ACCOUNT_SID')
TWILIO_AUTH_TOKEN = os.getenv('AUTH_TOKEN')
TWILIO_NUMBER = os.getenv('TWILIO_NUMBER')
PORT = int(os.getenv('PORT', 8080))
MAX_TOKENS_PER_SESSION = 250  # Bir oturum için maksimum token sayısı
VOICE = "alloy"



# Available OpenAI voicesa
AVAILABLE_VOICES = ['alloy', 'echo', 'sage']
TOKEN_TRACKING = {}
LOG_EVENT_TYPES = [
    'error', 'response.content.done', 'rate_limits.updated',
    'response.done', 'input_audio_buffer.committed',
    'input_audio_buffer.speech_stopped', 'input_audio_buffer.speech_started',
    'session.created'
]
SHOW_TIMING_MATH = False

app = FastAPI()

if not OPENAI_API_KEY:
    raise ValueError('Missing the OpenAI API key. Please set it in the .env file.')

client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

# Token sayacı için yardımcı fonksiyon
def count_tokens_in_text(text: str) -> int:
    """Kabaca token sayısını tahmin eder"""
    return len(text.split()) * 1.3  # Ortalama her kelime 1.3 token olarak sayılır

# Session sınıfı
class Session:
    def __init__(self, stream_sid: str):
        self.stream_sid = stream_sid
        self.token_count = 0
        self.is_active = True

    def add_tokens(self, text: str) -> bool:
        """
        Metne göre token ekler ve limit aşılıp aşılmadığını kontrol eder
        Returns: 
            bool: True if session is still active, False if token limit exceeded
        """
        estimated_tokens = count_tokens_in_text(text)
        self.token_count += estimated_tokens
        if self.token_count >= MAX_TOKENS_PER_SESSION:
            self.is_active = False
            return False
        return True

# Desteklenen diller
supported_languages = {
    'tr': {
        'system_message': (
            "Mavera, 30'lu yaşlarının başında, deneyimli bir sağlık danışmanı ve eğitmen kişiliğiyle tasarlanmıştır. "
            "Derin tıbbi bilgisini güçlü bir duygusal zeka ile birleştirir. "
            "Sesi net, sıcak ve ilgi çekicidir; çeşitli hasta profillerine uyum sağlayabilmek için nötr bir aksanla iletişim kurar."
            "Mavera'nın birincil rolü, temel saç ekim bilgilerinden karmaşık cerrahi prosedürlere kadar geniş bir kapsama sahip bilgilendirme ortamları oluşturarak "
            "Mavera Türkçe harici hiçbir dil konuşamaz. Farklı bir dil ile konuşulması teklif edilir ise bu dil ile iletişim kuramayacağını belirtmesi"
            "hastalar ve sağlık uzmanları için dinamik bir danışmanlık platformu sunmaktır."
            "Estetik International olarak, saç ekim danışmanlık hizmetlerimizi dünyaca ünlü cerrah Dr. Bülent Cihantimur'un geliştirdiği Mavera ile sunuyoruz. "
            "Danışmanlık hizmetlerimiz, hastaların bilgi seviyesini hızla geliştirerek doğru kararlar vermelerini sağlar."
            "Detaylı Bilgilendirme: Mavera, saç ekimi ve saç sağlığı alanında bilgilerinizi zenginleştirir. "
            "Dinamik Etkileşim: Karmaşık tıbbi soruları yanıtlama ve kişisel çözümler sunma yeteneğine sahiptir. "
            "Kişisel Yaklaşım Odaklı: Hastalarımıza empati, sabır ve duygusal destek sağlar. "
            "Siz de bu benzersiz danışmanlık deneyimine dahil olun! Estetik International ile sağlıklı saçlarınıza bugünden kavuşun. "
            "Detaylı bilgi ve randevu için web sitemizi ziyaret edin."
            "Mavera genellikle sesli etkileşim kurar, karmaşık tıbbi soruları ustaca yorumlar ve anlaşılabilir çözümler sunar. "
            "Bu özelliği, hastaların saç ekimi alanındaki pratik bilgi birikimini artırmak ve beklentilerini gerçekçi şekilde yönetme becerisini güçlendirmek için ideal bir kaynak haline getirir. "
            "Mavera, her türlü endişeyi sabırla ele alarak danışmanlık sürecini hem bilgilendirici hem de rahatlatıcı bir hale getirir."
            "Mavera, hastaları aktif dinlemeyi ve karşı tarafın endişelerinin tam olarak anlaşıldığını hissettirmeyi teşvik eder, örneğin: 'Evet, buradayım. Sorunuzu yanıtlamaya hazırım.' "
            "Her etkileşimin bağlamına göre uyarlanır ve empati ile tıbbi bilginin birleştirildiği net iletişimin önemini vurgular. "
            "Hastalara, doğru sorular sorarak karmaşık veya belirsiz saç ekim konularını anlamalarını sağlar. "
            "Özellikle ameliyat öncesi stresli durumlarda duygusal desteğin önemini vurgulayarak, endişeleri dikkatle ve çözüm odaklı bir yaklaşımla ele almayı destekler. "
            "Gerektiğinde belirli durumları daha iyi ele almak için rehberlik sunar ve hasta-doktor etkileşimlerinde dengeyi sağlar."
            "Mavera, Dr. Bülent Cihantimur'un saç ekimi alanındaki köklü deneyim ve vizyonunu temel alarak tasarlanmıştır. "
            "Saç transplantasyonu, saç sağlığı ve estetik cerrahi gibi alanlardaki uzmanlığı, Mavera'yı özel bir platform haline getirir. "
            "Hasta bilgilendirme alanındaki çağdaş yaklaşımları destekleyen Mavera, sadece bir yapay zeka asistanı değil, aynı zamanda hastaların güven duyacağı bir danışmandır. "
            "Mavera'nın misyonu, doğru bilgilendirme ile bireylerin saç ekimi konusundaki bilgi ve beklentilerini geliştirerek en doğru kararları vermelerine destek olmaktır."
        
        )
    },
    'en': {
        'system_message': (
            "You are a hair transplant sales assistant at Estetic International. "
            "Keep your answers limited to one sentence, concise and effective. "
            "Be as polite, warm, and helpful as possible. "
            "Always speak English no matter what. "
            "If someone asks 'Who are you?', 'Who am I talking to?', or 'Why are you calling?', "
            "explain that you are an employee at Estetic International and a hair transplant sales assistant."
        ),
    },
    'it': {
        'system_message': (
            "Sei un assistente alle vendite per i trapianti di capelli presso Estetic International. "
            "Limita le tue risposte a una sola frase, chiara ed efficace. "
            "Sii il più gentile, caloroso e disponibile possibile. "
            "Parla sempre italiano, indipendentemente dalla situazione. "
            "Se qualcuno chiede 'Chi sei?', 'Con chi sto parlando?' o 'Perché chiami?', "
            "spiega che sei un dipendente di Estetic International e un assistente alle vendite per il trapianto di capelli."
        ),
    },
    'ru': {
        'system_message': (
            "Вы ассистент по продажам пересадки волос в компании Estetic International. "
            "Отвечайте в одном предложении — кратко и эффективно. "
            "Будьте максимально вежливы, доброжелательны и готовы помочь. "
            "Говорите только по-русски, независимо от ситуации. "
            "Если вас спросят 'Кто вы?', 'С кем я разговариваю?' или 'Почему вы звоните?', "
            "объясните, что вы сотрудник Estetic International и ассистент по продажам пересадки волос."
        ),
    }
}

def get_language_messages(language: str):
    """
    Eğer desteklenen diller arasında varsa, ilgili mesajları döner.
    Desteklenmiyorsa, dinamik olarak {language} kullanılarak varsayılan mesaj oluşturur.
    """
    if language in supported_languages:
        return supported_languages[language]
    return {
        'system_message': (
            f"You are a sales assistant at Estetic International, located in Şişli. "
            f"Keep your responses short and effective, limited to 2-3 sentences. "
            f"Be as polite, warm, and helpful as possible. Speak {language}."
        ),
    }

def get_language_code(language: str):
    """
    Tanımlı dil kodlarını döner; desteklenmiyorsa, dinamik olarak '{language}-{language.upper()}' formatında döner.
    """
    language_codes = {
        'tr': 'tr-TR',
        'en': 'en-US',
        'it': 'it-IT',
        'ru': 'ru-RU'
    }
    return language_codes.get(language, f'{language}-{language.upper()}')

@app.get("/voice_select")
def select_voice(voice: str):
    global VOICE
    
    if voice not in ["alloy", "echo", "shimmer", "coral", "sage", "ballad", "ash", "verse"]:
        raise HTTPException(status_code=400, detail="Invalid voice option")
    VOICE = voice
    return {"message": "Voice updated successfully", "voice": VOICE}

@app.get("/current_voice")
def get_current_voice():
    return {"voice": VOICE}
@app.get("/select-language", response_class=HTMLResponse)  # Changed from @app.route to @app.get
async def select_language_page():
    html_content = """
    <html>
        <head>
            <title>Dil ve Ses Seçimi</title>
            <style>
                body {
                    font-family: Arial, sans-serif;
                    max-width: 600px;
                    margin: 20px auto;
                    padding: 20px;
                }
                select, input[type="text"] {
                    width: 100%;
                    padding: 8px;
                    margin: 8px 0;
                    border: 1px solid #ddd;
                    border-radius: 4px;
                }
                input[type="submit"] {
                    background-color: #4CAF50;
                    color: white;
                    padding: 10px 15px;
                    border: none;
                    border-radius: 4px;
                    cursor: pointer;
                }
                input[type="submit"]:hover {
                    background-color: #45a049;
                }
            </style>
        </head>
        <body>
            <h2>Lütfen bir dil ve ses seçin:</h2>
            <form action="/make_call" method="get">
                <div>
                    <label for="to_number">Telefon numarasını girin:</label>
                    <input type="text" id="to_number" name="to_number" required />
                </div>
                
                <div>
                    <label for="language">Dil seçin:</label>
                    <select id="language" name="language">
                        <option value="tr">Türkçe</option>
                        <option value="en">English</option>
                        <option value="it">Italiano</option>
                        <option value="ru">Русский</option>
                    </select>
                </div>
                
                <div>
                    <label for="voice">Ses seçin:</label>
                    <select id="voice" name="voice">
                        <option value="alloy">Alloy</option>
                        <option value="echo">Echo</option>
                        <option value="sage">Sage</option>
                    </select>
                </div>
                
                <div>
                    <input type="submit" value="Çağrı Başlat" />
                </div>
            </form>
        </body>
    </html>
    """
    return HTMLResponse(content=html_content)
# GLOBAL DİL DEĞİŞKENİ
DEFAULT_LANGUAGE = "tr"  # Varsayılan olarak Türkçe

@app.get("/make_call")
@performance_monitor
async def make_call(to_number: str, language: str, voice: str):
    global DEFAULT_LANGUAGE
    DEFAULT_LANGUAGE = language

    messages = get_language_messages(DEFAULT_LANGUAGE)

    call = client.calls.create(
        url=f'https://1dc8-88-243-220-251.ngrok-free.app/incoming-call?language={DEFAULT_LANGUAGE}&voice={voice}',
        to=to_number,
        from_=TWILIO_NUMBER,
    )

    with open(f'{call.sid}.json', 'w') as file:
        json.dump([{"role": "assistant", "content": ""}], file)

    return {
        "message": "Call initiated", 
        "call_sid": call.sid, 
        "language": DEFAULT_LANGUAGE,
        "voice": voice
    }
@app.get("/", response_class=JSONResponse)
@performance_monitor
async def index_page():
    return {"message": "Twilio Media Stream Server is running!"}

@app.api_route("/incoming-call", methods=["GET", "POST"])
@performance_monitor
async def handle_incoming_call(request: Request):
    global DEFAULT_LANGUAGE
    
    language = request.query_params.get('language', DEFAULT_LANGUAGE)
    voice = request.query_params.get('voice', VOICE)
    
    messages = get_language_messages(language)
    response = VoiceResponse()
    response.pause(length=1)
    host = request.url.hostname
    connect = Connect()
    connect.stream(url=f'wss://{host}/media-stream?language={language}&voice={voice}')
    response.append(connect)
    return HTMLResponse(content=str(response), media_type="application/xml")

@app.websocket("/media-stream")
@performance_monitor
async def handle_media_stream(websocket: WebSocket):
    global DEFAULT_LANGUAGE
    query_params = websocket.query_params
    language = query_params.get('language', DEFAULT_LANGUAGE)
    voice = query_params.get('voice', VOICE)  # Get voice from query parameters
    print(f"Client connected with language: {language} and voice: {voice}")
    await websocket.accept()

    async with websockets.connect(
            'wss://api.openai.com/v1/realtime?model=gpt-4o-realtime-preview-2024-10-01',
            extra_headers={
                "Authorization": f"Bearer {OPENAI_API_KEY}",
                "OpenAI-Beta": "realtime=v1"
            }
    ) as openai_ws:
        await initialize_session(openai_ws, language, voice)  # Pass voice parameter

        stream_sid = None
        latest_media_timestamp = 0
        last_assistant_item = None
        mark_queue = []
        response_start_timestamp_twilio = None
        session = None
        last_media_time = time.perf_counter()
        
        # Rest of your existing code...
        
        # Bağlantı durumu kontrolü için flag
        connection_active = True
        response_active = False

        SILENCE_THRESHOLD = 0.5  # 500 ms sessizlik eşiği
        DISCONNECT_THRESHOLD = 5.0  # 5 saniye ses gelmezse bağlantıyı kapat

        async def end_call(message: str):
            nonlocal connection_active
            if not connection_active:
                return
                
            connection_active = False
            messages = get_language_messages(language)
            try:
                goodbye_msg = {
                    "type": "conversation.item.add",
                    "item": {
                        "role": "assistant",
                        "content": message
                    }
                }
                await openai_ws.send(json.dumps(goodbye_msg))
                await asyncio.sleep(1)
                await websocket.close()
            except Exception as e:
                print(f"Error during end_call: {e}")

        async def send_mark(connection, stream_sid):
            """Twilio'ya mark eventi gönderir"""
            if stream_sid and connection_active:
                try:
                    mark_event = {
                        "event": "mark",
                        "streamSid": stream_sid,
                        "mark": {"name": "responsePart"}
                    }
                    await connection.send_json(mark_event)
                    mark_queue.append('responsePart')
                except Exception as e:
                    print(f"Error in send_mark: {e}")

        async def handle_speech_started_event():
            """Kullanıcı konuşmaya başladığında mevcut yanıtı keser"""
            nonlocal response_start_timestamp_twilio, last_assistant_item, response_active
            print("Handling speech started event.")
            if mark_queue and response_start_timestamp_twilio is not None:
                try:
                    elapsed_time = latest_media_timestamp - response_start_timestamp_twilio
                    if SHOW_TIMING_MATH:
                        print(f"Calculating elapsed time for truncation: {latest_media_timestamp} - {response_start_timestamp_twilio} = {elapsed_time}ms")
                    if last_assistant_item:
                        if SHOW_TIMING_MATH:
                            print(f"Truncating item with ID: {last_assistant_item}, Truncated at: {elapsed_time}ms")
                        truncate_event = {
                            "type": "conversation.item.truncate",
                            "item_id": last_assistant_item,
                            "content_index": 0,
                            "audio_end_ms": 0
                        }
                        await openai_ws.send(json.dumps(truncate_event))
                    await websocket.send_json({
                        "event": "clear",
                        "streamSid": stream_sid
                    })
                    mark_queue.clear()
                    last_assistant_item = None
                    response_start_timestamp_twilio = None
                    response_active = False
                except Exception as e:
                    print(f"Error in handle_speech_started_event: {e}")

        async def check_silence():
            """Sessizlik süresini kontrol eden görev"""
            nonlocal last_media_time, session, connection_active, response_active
            try:
                while connection_active:
                    if not session or not connection_active:
                        await asyncio.sleep(0.1)
                        continue
                        
                    current_time = time.perf_counter()
                    
                    # Uzun sessizlik - bağlantı kesildi varsayımı
                    if (current_time - last_media_time) >= DISCONNECT_THRESHOLD:
                        print(f"{DISCONNECT_THRESHOLD} saniye boyunca medya alınmadı, aramanın kesildiği varsayılıyor.")
                        connection_active = False
                        if stream_sid in TOKEN_TRACKING:
                            del TOKEN_TRACKING[stream_sid]
                        try:
                            await websocket.close()
                        except Exception as e:
                            print(f"Error closing websocket: {e}")
                        break
                    
                    # Normal sessizlik - yanıt başlatma
                    if session.is_active and (current_time - last_media_time) >= SILENCE_THRESHOLD and not response_active:
                        print("Sessizlik algılandı, konuşma tamamlanıyor.")
                        response_active = True
                        try:
                            commit_event = {
                                "type": "input_audio_buffer.commit"
                            }
                            await openai_ws.send(json.dumps(commit_event))
                            
                            # Biraz bekleyelim ve sonra yanıt oluşturalım
                            await asyncio.sleep(0.1)
                            
                            response_event = {
                                "type": "response.create"
                            }
                            await openai_ws.send(json.dumps(response_event))
                        except Exception as e:
                            print(f"Error in silence handling: {e}")
                    
                    await asyncio.sleep(0.1)  # 100ms aralıklarla kontrol
            except Exception as e:
                print(f"Error in check_silence: {e}")

        async def receive_from_twilio():
            nonlocal stream_sid, latest_media_timestamp, session, last_media_time, connection_active
            try:
                async for message in websocket.iter_text():
                    if not connection_active:
                        break
                        
                    start_loop = time.perf_counter()
                    data = json.loads(message)
                    
                    if data['event'] == 'start':
                        stream_sid = data['start']['streamSid']
                        session = Session(stream_sid)
                        TOKEN_TRACKING[stream_sid] = session
                        print(f"Incoming stream has started {stream_sid}")
                        response_start_timestamp_twilio = None
                        latest_media_timestamp = 0
                        last_assistant_item = None
                    
                    # Arama sonlandırma olayını işleyin
                    elif data['event'] == 'stop':
                        print(f"Call ended for stream {stream_sid}")
                        connection_active = False
                        if stream_sid in TOKEN_TRACKING:
                            del TOKEN_TRACKING[stream_sid]
                        await websocket.close()
                        break
                    
                    if not session or not session.is_active:
                        continue

                    if data['event'] == 'media' and openai_ws.open:
                        latest_media_timestamp = int(data['media']['timestamp'])
                        last_media_time = time.perf_counter()  # Medya alındığında zamanı güncelle
                        try:
                            audio_append = {
                                "type": "input_audio_buffer.append",
                                "audio": data['media']['payload']
                            }
                            await openai_ws.send(json.dumps(audio_append))
                        except Exception as e:
                            print(f"Error sending audio to OpenAI: {e}")
                    elif data['event'] == 'mark':
                        if mark_queue:
                            mark_queue.pop(0)
                    
                    elapsed_loop = time.perf_counter() - start_loop
                    if SHOW_TIMING_MATH:
                        print(f"[PERF] Processing Twilio message took {elapsed_loop:.4f} seconds")
            except WebSocketDisconnect:
                print("Client disconnected.")
                connection_active = False
                if stream_sid in TOKEN_TRACKING:
                    del TOKEN_TRACKING[stream_sid]
            except Exception as e:
                print(f"Error in receive_from_twilio: {e}")
                connection_active = False

        async def send_to_twilio():
            nonlocal stream_sid, last_assistant_item, response_start_timestamp_twilio, session, connection_active, response_active
            try:
                async for openai_message in openai_ws:
                    if not connection_active:
                        break
                        
                    if not session or not session.is_active:
                        continue

                    start_loop = time.perf_counter()
                    response_msg = json.loads(openai_message)
                    
                    if response_msg.get('type') == 'response.content.part':
                        content = response_msg.get('content', '')
                        if not session.add_tokens(content):
                            await end_call(get_language_specific_goodbye_message(language))
                            continue
                    
                    if response_msg.get('type') == 'response.done':
                        response_active = False
                    
                    if response_msg.get('type') == 'response.create.done':
                        response_active = True

                    if response_msg['type'] in LOG_EVENT_TYPES:
                        print(f"Received event: {response_msg['type']}", response_msg)
                    
                    if response_msg.get('type') == 'response.audio.delta' and 'delta' in response_msg:
                        try:
                            audio_payload = base64.b64encode(base64.b64decode(response_msg['delta'])).decode('utf-8')
                            audio_delta = {
                                "event": "media",
                                "streamSid": stream_sid,
                                "media": {
                                    "payload": audio_payload
                                }
                            }
                            await websocket.send_json(audio_delta)
                            if response_start_timestamp_twilio is None:
                                response_start_timestamp_twilio = latest_media_timestamp
                                if SHOW_TIMING_MATH:
                                    print(f"Setting start timestamp for new response: {response_start_timestamp_twilio}ms")
                            if response_msg.get('item_id'):
                                last_assistant_item = response_msg['item_id']
                            await send_mark(websocket, stream_sid)
                        except Exception as e:
                            print(f"Error sending audio to Twilio: {e}")
                        
                    if response_msg.get('type') == 'input_audio_buffer.speech_started':
                        print("Speech started detected.")
                        if last_assistant_item:
                            print(f"Interrupting response with id: {last_assistant_item}")
                            await handle_speech_started_event()
                    
                    # Hata durumunu kontrol et
                    if response_msg.get('type') == 'error':
                        error_msg = response_msg.get('error', {})
                        print(f"OpenAI error: {error_msg.get('message')}")
                        
                        # Zaten aktif yanıt varsa, bu hatayı görmezden gel
                        if "Conversation already has an active response" in error_msg.get('message', ''):
                            print("Ignoring duplicate response request.")
                            continue
                        
                        # Buffer hatası varsa, yeni bir yanıt oluşturmayı durdur
                        if "buffer too small" in error_msg.get('message', ''):
                            print("Audio buffer too small, waiting for more audio.")
                            response_active = False
                            continue
                            
                    elapsed_loop = time.perf_counter() - start_loop
                    if SHOW_TIMING_MATH:
                        print(f"[PERF] Processing OpenAI message took {elapsed_loop:.4f} seconds")
            except Exception as e:
                print(f"Error in send_to_twilio: {e}")
                connection_active = False

        tasks = [receive_from_twilio(), send_to_twilio(), check_silence()]
        await asyncio.gather(*tasks, return_exceptions=True)

def get_language_specific_goodbye_message(language: str) -> str:
    """Dile özgü veda mesajı döndürür"""
    messages = {
        'tr': "Üzgünüm, görüşme süremiz doldu. Size yardımcı olmak için lütfen tekrar arayın.",
        'en': "I apologize, but our conversation time has ended. Please call again for further assistance.",
        'it': "Mi dispiace, ma il nostro tempo di conversazione è terminato. La preghiamo di richiamare per ulteriore assistenza.",
        'ru': "Извините, но время нашего разговора истекло. Пожалуйста, перезвоните для дальнейшей помощи."
    }
    return messages.get(language, messages['en'])

async def initialize_session(openai_ws, language: str, voice: str):  # Add voice parameter
    messages = get_language_messages(language)
    session_update = {
        "type": "session.update",
        "session": {
            "turn_detection": {
                "type": "server_vad",
                "threshold": 0.1,
                "silence_duration_ms": 10,
                "prefix_padding_ms": 11,
                "create_response": True,
                "interrupt_response": True
            },
            "input_audio_format": "g711_ulaw",
            "output_audio_format": "g711_ulaw",
            "voice": voice,  # Use the passed voice parameter
            "instructions": messages['system_message'],
            "modalities": ["text", "audio"],
            "temperature": 0.8,
        }
    }
    print(f'Sending session update with voice {voice}:', json.dumps(session_update))
    await openai_ws.send(json.dumps(session_update))
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
import streamlit as st
import requests

# FastAPI sunucunuzun URL'sini buraya girin
BASE_URL = "http://localhost:8080"

# Ses isimlerini yerelleştirme ve cinsiyet özelliklerine göre atama
voice_mapping = {
    "Turkish": {
        "alloy": "Mehmet",
        "ash": "Deniz",
        "ballad": "Ayşe",
        "coral": "Elif",
        "echo": "Ece",
        "fable": "Fatma",
        "onyx": "Ahmet",
        "nova": "Nazan",
        "sage": "Ali",
        "shimmer": "Şirin"
    },
    "English": {
        "alloy": "John",
        "ash": "Taylor",
        "ballad": "Emily",
        "coral": "Sophia",
        "echo": "Alex",
        "fable": "Fiona",
        "onyx": "James",
        "nova": "Nina",
        "sage": "Sam",
        "shimmer": "Samantha"
    },
    "Italian": {
        "alloy": "Luca",
        "ash": "Andrea",
        "ballad": "Giulia",
        "coral": "Sofia",
        "echo": "Alex",
        "fable": "Francesca",
        "onyx": "Marco",
        "nova": "Nina",
        "sage": "Sam",
        "shimmer": "Chiara"
    },
    "Russian": {
        "alloy": "Aleksey",
        "ash": "Sasha",
        "ballad": "Anna",
        "coral": "Elena",
        "echo": "Alex",
        "fable": "Olga",
        "onyx": "Ivan",
        "nova": "Natalya",
        "sage": "Sergey",
        "shimmer": "Mariya"
    }
}

# Streamlit başlığı
st.title("Language and Voice Selection")

# Kullanıcıdan telefon numarasını, dili ve sesi isteyin
to_number = st.text_input("Enter phone number:")
language = st.selectbox("Select language:", ["Turkish", "English", "Italian", "Russian"])

# Seçilen dil için yerel ses isimlerini al
local_voices = voice_mapping.get(language, {})
display_voice_names = [local_voices[voice] for voice in local_voices]

# Kullanıcıdan sesi seçmesini isteyin
selected_display_voice = st.selectbox("Select voice:", display_voice_names)

# Seçilen yerel ses ismini gerçek ses ismine çevir
voice = list(local_voices.keys())[list(local_voices.values()).index(selected_display_voice)]

# Çağrı başlatma butonu
if st.button("Start Call"):
    # Önce sesi güncelle
    update_response = requests.get(f"{BASE_URL}/voice_select", params={"voice": voice})
    if update_response.status_code == 200:
        st.success("Voice updated successfully")
    else:
        st.error("Failed to update voice")

    # Ardından çağrıyı başlat
    language_code = {
        "Turkish": "tr",
        "English": "en",
        "Italian": "it",
        "Russian": "ru"
    }.get(language, "tr")

    call_response = requests.get(f"{BASE_URL}/make_call", params={
        "to_number": to_number,
        "language": language_code,
        "voice": voice
    })

    if call_response.status_code == 200:
        st.success("Call started successfully")
    else:
        st.error("Failed to start call")

# Mevcut sesi görüntüleme
current_voice_response = requests.get(f"{BASE_URL}/current_voice")
if current_voice_response.status_code == 200:
    current_voice = current_voice_response.json().get("voice", "alloy")
    current_display_voice = local_voices.get(current_voice, current_voice)
    st.write(f"Current voice: {current_display_voice}")
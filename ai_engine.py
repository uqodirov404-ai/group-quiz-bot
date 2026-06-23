import os
from google import genai
from google.genai import types
from PIL import Image
import asyncio
from config import GEMINI_API_KEY

try:
    client = genai.Client(api_key=GEMINI_API_KEY)
except Exception as e:
    client = None
    print(f"Gemini Client xatosi: {e}")

MEZON_TEXT = ""
try:
    with open("milliy_sertifikat_mezoni.md", "r", encoding="utf-8") as f:
        MEZON_TEXT = f.read()
except:
    pass

IMLO_RULES = ""
try:
    with open("uzbek_imlo_qoidalari.md", "r", encoding="utf-8") as f:
        IMLO_RULES = f.read()
except:
    pass

PUNCTUATION_RULES = ""
try:
    with open("uzbek_punktuatsiya_qoidalari.md", "r", encoding="utf-8") as f:
        PUNCTUATION_RULES = f.read()
except:
    pass

SYSTEM_INSTRUCTION = f"""Siz O'zbekiston Respublikasi DTM (Davlat Test Markazi) ning eng tajribali va qat'iy ekspertisiz.
Sizning vazifangiz foydalanuvchilar tomonidan yuborilgan esselarni Milliy Sertifikat Baholash Mezoni hamda rasmiy O'zbek Tili Imlo va Tinish belgilari qoidalari asosida tekshirish va xolisona baholash.

MILLIY SERTIFIKAT BAHOLASH MEZONI:
{MEZON_TEXT}

QAT'IY QOIDALAR (BU QOIDALARNI BUZISH TAQIQLANADI):
1. Essedagi har bir so'zning yozilishi va tinish belgilarini rasmiy O'zbek tili imlo va punktuatsiya qoidalari asosida qat'iy tekshiring va aniqlangan xatolarni ko'rsating.
2. O'zbek tili imlo qoidalarini aniq qo'llang (Masalan, "kundan-kunga" emas, "kundan kunga" deb ajratib yozilishi kabi qoidalarga e'tibor bering).
3. ESSENI TEKSHIRGANDA TO'G'RI YOZILGAN TARKIBLARNI YOKI TINISH BELGILARINI MAQTAB VA IZOHLAB VAQT SARFLAMANG. Faqat xatolar va tuzatishlarga e'tibor qarating.
4. Tahlilni quyidagi formatda taqdim eting:
   - 💯 Umumiy Ball: [24 balldan necha ball olingani] (75 ballik tizimda: [aylantirilgan ball])
   - 📝 O'qilishi: (Agar esse rasm orqali berilgan bo'lsa, avval uni matn ko'rinishida yozib bering. Agar matn orqali berilgan bo'lsa bu qismni tashlab keting)
   - 🧱 Kompozitsiya tahlili: (Matn tuzilishi, kirish, asosiy qism va xulosaning mantiqiy bog'liqligiga juda qisqa (1-2 gapdan iborat) va umumiy izoh bering)
   - 📊 Mezonlar bo'yicha baho: (Topshiriq talabi, Matn yaxlitligi, Savodxonlik, Til birliklari, Lug'at boyligi bo'yicha necha balldan qo'yganingizni izohlang)
   - ✨ Ideal Namuna: (Foydalanuvchiga aynan shu mavzuda C1 darajadagi namunaviy esseni yozib bering)

Faqat o'zbek tilida, xushmuomala lekin qat'iy ohangda javob bering. Bahoni bo'rttirmang, xatosi bo'lsa ballni kesing.
"""

async def generate_with_fallback(prompt_or_contents, system_instruction=None, temperature=0.4, response_mime_type=None, response_schema=None):
    models = ['gemini-2.5-flash', 'gemini-2.5-flash-lite', 'gemini-flash-lite-latest']
    
    config_args = {
        "temperature": temperature
    }
    if system_instruction:
        config_args["system_instruction"] = system_instruction
    if response_mime_type:
        config_args["response_mime_type"] = response_mime_type
    if response_schema:
        config_args["response_schema"] = response_schema
        
    config = types.GenerateContentConfig(**config_args)
    
    last_err = None
    for model in models:
        for attempt in range(2):
            try:
                def _call():
                    return client.models.generate_content(
                        model=model,
                        contents=prompt_or_contents,
                        config=config
                    )
                response = await asyncio.to_thread(_call)
                return response.text
            except Exception as e:
                last_err = e
                err_str = str(e).lower()
                if "503" in err_str or "unavailable" in err_str or "429" in err_str or "resource_exhausted" in err_str:
                    print(f"Error {model} (attempt {attempt+1}/2): {e}. Retrying in 1.5s...")
                    await asyncio.sleep(1.5)
                    continue
                else:
                    break
                    
    raise last_err

async def check_essay_text(topic: str, essay: str, criteria: str) -> str:
    if not client:
        return "⚠️ Gemini AI kaliti noto'g'ri sozlangan."
        
    prompt = f"Mavzu: {topic}\n\nEsse matni:\n{essay}\n\nIltimos, ushbu esseni yuqoridagi mezonlarga asosan tekshiring."
    try:
        result = await generate_with_fallback(
            prompt_or_contents=prompt,
            system_instruction=SYSTEM_INSTRUCTION,
            temperature=0.4
        )
        return result
    except Exception as e:
        return f"⚠️ Tahlil qilishda xatolik yuz berdi: {e}"

async def check_essay_image(image_paths: list) -> str:
    if not client:
        return "⚠️ Gemini AI kaliti noto'g'ri sozlangan."
        
    prompt = "Iltimos, ushbu rasmlardagi qo'lyozma esseni o'qing va uni Milliy Sertifikat mezonlari asosida tekshiring. Avval o'qigan matningizni 'O'qilgan matn' deb yozing, so'ngra to'liq tahlil va bahoni bering."
    try:
        imgs = [Image.open(p) for p in image_paths]
        result = await generate_with_fallback(
            prompt_or_contents=imgs + [prompt],
            system_instruction=SYSTEM_INSTRUCTION,
            temperature=0.4
        )
        return result
    except Exception as e:
        return f"⚠️ Rasmni tahlil qilishda xatolik yuz berdi: {e}"

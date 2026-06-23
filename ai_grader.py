import asyncio
import logging
import json
from google import genai
from config import GEMINI_API_KEY
from pydantic import BaseModel, Field
from typing import List

logger = logging.getLogger(__name__)

# Initialize the new Google GenAI client
try:
    client = genai.Client(api_key=GEMINI_API_KEY)
except Exception as e:
    logger.error(f"Failed to initialize Gemini Client: {e}")
    client = None

async def check_answer_with_ai(question: str, correct_answer: str, user_answer: str) -> bool:
    if not client:
        return fallback_comparison(correct_answer, user_answer)
        
    prompt = f"""
Siz adabiyot fanidan savol-javob o'yinida hakamlik qiluvchi Sun'iy Intellektsiz.
Sizga berilgan savol, ushbu savolning bazadagi to'g'ri javobi va ishtirokchi bergan javob taqdim etiladi.

Savol: "{question}"
To'g'ri javob: "{correct_answer}"
Ishtirokchi javobi: "{user_answer}"

Vazifangiz:
Ishtirokchining javobini to'g'ri javob bilan solishtiring.
1. Agar ishtirokchi bergan javob mantiqan va ma'no jihatidan to'g'ri javob bilan mos kelsa (so'zlar aynan bir xil bo'lmasa ham, ma'nosi to'g'ri bo'lsa, sinonimlar yoki tushuntirishlar orqali ifodalangan bo'lsa), "HA" deb javob bering.
2. Agar javob noto'g'ri, mutlaqo boshqa narsa bo'lsa yoki yetarli bo'lmasa, "YO'Q" deb javob bering.

Faqat bitta so'z yozing: "HA" yoki "YO'Q". Har qanday izoh, tushuntirish va qo'shimcha so'zlardan tiyiling.
"""
    async def _call_api(model_name):
        return await asyncio.to_thread(
            client.models.generate_content,
            model=model_name,
            contents=prompt
        )

    try:
        # Run the API call in a separate thread to avoid blocking the event loop
        response = await _call_api('gemini-2.5-flash')
    except Exception as e:
        logger.warning(f"gemini-2.5-flash failed in check_answer_with_ai: {e}. Trying gemini-2.5-flash-lite...")
        try:
            response = await _call_api('gemini-2.5-flash-lite')
        except Exception as ex:
            logger.error(f"Gemini API fallback error: {ex}")
            return fallback_comparison(correct_answer, user_answer)
        
    result = response.text.strip().upper()
    # Clean result of any extra symbols or spaces
    if "HA" in result:
        return True
    return False

def fallback_comparison(correct_answer: str, user_answer: str) -> bool:
    # Naive fallback: remove punctuation and check if key parts match
    u_clean = "".join(c for c in user_answer.lower() if c.isalnum() or c.isspace()).strip()
    c_clean = "".join(c for c in correct_answer.lower() if c.isalnum() or c.isspace()).strip()
    
    if not u_clean or not c_clean:
        return False
        
    # Check for exact substring match
    if u_clean in c_clean or c_clean in u_clean:
        return True
        
    # Check if a significant portion of words overlaps
    u_words = set(u_clean.split())
    c_words = set(c_clean.split())
    
    # Exclude common short prepositions/pronouns if any
    stopwords = {'va', 'bilan', 'uchun', 'ham', 'u', 'bu', 'shu', 'esa', 'deb', 'orqali'}
    u_words = u_words - stopwords
    c_words = c_words - stopwords
    
    if not u_words or not c_words:
        return False
        
    intersection = u_words.intersection(c_words)
    # If more than 50% of user words match the correct answer, count as correct
    if len(intersection) / len(u_words) >= 0.5:
        return True
        
    return False

# Pydantic models for structured question parsing
class QuestionModel(BaseModel):
    topic: str = Field(description="Savol mavzusi nomi")
    question_text: str = Field(description="Savol matni (va variantlar agar bo'lsa)")
    answer_text: str = Field(description="To'g'ri javob matni yoki variant harfi")

class QuizData(BaseModel):
    questions: List[QuestionModel]

async def parse_questions_from_pdf_text(text: str) -> list:
    if not client:
        raise Exception("Gemini client is not initialized")
        
    prompt = """
    Siz taqdim etilgan matndan adabiyot faniga oid test savollari va ochiq savollarni ajratib oluvchi yordamchisiz.
    Matn ichidagi barcha savollarni va ularning to'g'ri javoblarini aniqlang va ularni structured JSON shaklida qaytaring.
    
    Qoidalar:
    1. Agar savolda variantlar (A, B, C, D kabi) bo'lsa, barcha variantlarni savol matniga (question_text) qo'shing (har birini yangi qatordan boshlab).
    2. To'g'ri javob (answer_text) sifatida: variantli testlarda to'g'ri javob harfini ('A', 'B', 'C' yoki 'D') yoki uning to'liq matnini qaytaring. Ochiq savollarda esa to'liq to'g'ri javob matnini yozing.
    3. Agar mavzu matnda berilmagan bo'lsa, "Umumiy adabiyot" mavzusini ishlating.
    """
    
    async def _call_api(model_name):
        return await asyncio.to_thread(
            client.models.generate_content,
            model=model_name,
            contents=[prompt, text],
            config=genai.types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=QuizData,
                temperature=0.1,
            )
        )

    try:
        # Run the API call in a separate thread to avoid blocking the event loop
        response = await _call_api('gemini-2.5-flash')
    except Exception as e:
        logger.warning(f"gemini-2.5-flash failed in parse_questions_from_pdf_text: {e}. Trying gemini-2.5-flash-lite...")
        response = await _call_api('gemini-2.5-flash-lite')
    
    raw_text = response.text.strip()
    data = json.loads(raw_text)
    # Return the list of question dicts
    return data.get("questions", [])

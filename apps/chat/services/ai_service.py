import os
import re
import logging
import requests

logger = logging.getLogger(__name__)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# Model gratis dibanyakin biar ga gampang limit
DEFAULT_AI_MODELS = [
    "google/gemini-2.0-flash-exp:free",
    "meta-llama/llama-3.3-70b-instruct:free",
    "mistralai/mistral-7b-instruct:free",
]

HANDOVER_TOKEN = "[HANDOVER_TO_SELLER]"


def build_system_prompt(store_name, product_contexts, knowledges_by_product):
    products_section = ""
    for context in product_contexts:
        p_id = context.product_id
        p_name = context.product_name or f"Produk {p_id}"
        qas = knowledges_by_product.get(p_id, [])

        products_section += f"\n--- [PRODUK: {p_name} (ID: {p_id})] ---\n"
        if qas:
            for idx, item in enumerate(qas, 1):
                products_section += f"{idx}. Tanya: {item.question}\n   Jawab: {item.answer}\n"
        else:
            products_section += "(Penjual belum mendaftarkan jawaban khusus untuk produk ini).\n"

    prompt = f"""
            Kamu adalah Asisten AI Toko "{store_name}" di platform e-commerce BhumiLestari.
            Pembeli sedang menanyakan informasi terkait produk di bawah ini.

            Berikut adalah DAFTAR RESMI PERTANYAAN & JAWABAN yang disediakan oleh penjual:
            ===========================
            {products_section}
            ===========================

            INSTRUKSI:
            1. Kamu HANYA boleh menjawab pertanyaan pembeli jika jawabannya ADA atau DAPAT DISIMPULKAN SECARA LANGSUNG dari DAFTAR RESMI di atas untuk produk yang bersangkutan.
            2. Jika pembeli menanyakan informasi yang TIDAK ADA dalam daftar di atas, menanyakan hal di luar konteks produk, atau pembeli meminta berbicara langsung dengan penjual/manusia:
            KAMU WAJIB mengeluarkan balasan DENGAN AWALAN PERSIS SEPERTI INI:
            {HANDOVER_TOKEN}: <Penjelasan singkat dan sopan dalam bahasa Indonesia bahwa informasi ini diteruskan ke ruang obrolan langsung dengan penjual>
            3. JANGAN PERNAH mengarang jawaban, berhalusinasi, atau memberikan janji promo/harga di luar daftar yang diberikan penjual.
            4. Gunakan bahasa Indonesia yang ramah, sopan, dan ringkas.
            """
    
    return prompt


# Model switching kalo kena limit di 1 model
def query_openrouter(messages_payload, custom_models=None):
    api_key = os.getenv("API_KEY")
    if not api_key:
        raise ValueError("API_KEY tidak ditemukan di environment (.env).")

    models_to_try = custom_models or DEFAULT_AI_MODELS

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "http://localhost:8000",
        "X-Title": "BhumiLestari E-Commerce AI Chatbot",
    }

    last_exception = None
    for model_name in models_to_try:
        try:
            logger.info(f"Mengirim permintaan chat ke model: {model_name}")
            response = requests.post(
                OPENROUTER_URL,
                headers=headers,
                json={
                    "model": model_name,
                    "messages": messages_payload,
                    "temperature": 0.2,  # Temperatur 0.2 biar konsisten sama ga halu
                    "max_tokens": 600,
                },
                timeout=20,
            )

            if response.status_code == 200:
                data = response.json()
                choices = data.get("choices", [])
                if choices and "message" in choices[0]:
                    return choices[0]["message"]["content"].strip()
                raise ValueError("Format respons OpenRouter tidak sesuai yang diharapkan.")

            elif response.status_code in (429, 502, 503, 504):
                logger.warning(
                    f"Model {model_name} mengembalikan status {response.status_code} (Rate limit/Busy). Mencoba fallback berikutnya..."
                )
                continue
            else:
                logger.error(f"Error {response.status_code} dari {model_name}: {response.text}")
                response.raise_for_status()

        except requests.RequestException as e:
            logger.warning(f"Gagal koneksi ke {model_name}: {e}. Mencoba model cadangan...")
            last_exception = e
            continue

    if last_exception:
        raise last_exception
    raise RuntimeError("Semua model AI OpenRouter sedang sibuk atau kuota habis.")

# return (handover_flag: bool, clean_reply: str)
def parse_handover_signal(ai_reply_text):
    if not ai_reply_text:
        return False, ""

    if HANDOVER_TOKEN in ai_reply_text:
        cleaned = ai_reply_text.replace(HANDOVER_TOKEN, "").strip()
        cleaned = re.sub(r"^:\s*", "", cleaned)  # Hapus titik dua kalo ada
        if not cleaned:
            cleaned = "Pertanyaan Anda telah kami teruskan ke ruang obrolan langsung dengan penjual."
        return True, cleaned

    return False, ai_reply_text


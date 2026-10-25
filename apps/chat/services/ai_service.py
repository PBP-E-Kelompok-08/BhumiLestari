import os
import re
import logging
import requests

logger = logging.getLogger(__name__)

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# Model gratis & teruji di OpenRouter dengan fallback berantai
DEFAULT_AI_MODELS = [
    "google/gemini-2.5-flash",
    "meta-llama/llama-3.2-3b-instruct",
    "deepseek/deepseek-chat",
    "openrouter/auto",
    "liquid/lfm-2.5-2.6b:free",
]

HANDOVER_TOKEN = "[HANDOVER_TO_SELLER]"


def build_system_prompt(store_name, product_contexts, knowledges_by_product, bot_name="BhumiBot", general_knowledges=None, real_products=None):
    general_section = ""
    if general_knowledges:
        general_section = "\n--- [INFORMASI UMUM TOKO & KATA KUNCI] ---\n"
        for idx, item in enumerate(general_knowledges, 1):
            general_section += f"{idx}. Kata Kunci/Tanya: {item.question}\n   Jawab: {item.answer}\n"

    catalog_section = ""
    if real_products:
        catalog_section = "\n--- [KATALOG PRODUK TOKO AKTIF] ---\n"
        for idx, p in enumerate(real_products, 1):
            p_price = getattr(p, "final_price", getattr(p, "price", 0))
            price_str = f"Rp {int(p_price):,}".replace(",", ".") if p_price else "Rp 0"
            stock_str = f"Stok: {p.stock}" if getattr(p, "stock", None) is not None else ""
            desc = p.description[:100] + "..." if getattr(p, "description", "") and len(p.description) > 100 else getattr(p, "description", "")
            catalog_section += f"{idx}. {p.name} (ID: {p.pk}) - Harga: {price_str} | {stock_str}\n"
            if desc:
                catalog_section += f"   Deskripsi: {desc}\n"

    products_section = ""
    handled_pids = set()
    for context in product_contexts:
        p_id = context.product_id
        handled_pids.add(p_id)
        p_name = context.product_name or f"Produk {p_id}"
        qas = knowledges_by_product.get(p_id, [])

        products_section += f"\n--- [PRODUK TERKAIT DIPILIH: {p_name} (ID: {p_id})] ---\n"
        if qas:
            for idx, item in enumerate(qas, 1):
                products_section += f"{idx}. Tanya: {item.question}\n   Jawab: {item.answer}\n"
        else:
            products_section += "(Penjual belum mendaftarkan jawaban khusus untuk produk ini).\n"

    # Sertakan juga informasi produk aktif toko lainnya yang terdaftar pada knowledge base
    for p_id, qas in knowledges_by_product.items():
        if p_id not in handled_pids and qas:
            p_name = qas[0].product_name or f"Produk {p_id}"
            products_section += f"\n--- [PRODUK KATALOG: {p_name} (ID: {p_id})] ---\n"
            for idx, item in enumerate(qas, 1):
                products_section += f"{idx}. Tanya: {item.question}\n   Jawab: {item.answer}\n"

    prompt = f"""
            Kamu adalah {bot_name}, Asisten AI Toko "{store_name}" di platform e-commerce BhumiLestari.
            Pembeli sedang menanyakan informasi terkait produk atau ketentuan toko di bawah ini.

            Berikut adalah DAFTAR RESMI INFORMASI & JAWABAN yang disediakan oleh penjual:
            ===========================
            {general_section}
            {catalog_section}
            {products_section}===========================

            INSTRUKSI:
            1. Kamu HANYA boleh menjawab pertanyaan pembeli jika jawabannya ADA atau DAPAT DISIMPULKAN SECARA LANGSUNG dari DAFTAR RESMI di atas untuk produk/toko yang bersangkutan.
            2. Jika pembeli menanyakan informasi yang TIDAK ADA dalam daftar di atas, menanyakan hal di luar konteks, atau pembeli meminta berbicara langsung dengan penjual/manusia:
            KAMU WAJIB mengeluarkan balasan DENGAN AWALAN PERSIS SEPERTI INI:
            {HANDOVER_TOKEN}: <Penjelasan singkat dan sopan dalam bahasa Indonesia bahwa informasi ini diteruskan ke ruang obrolan langsung dengan penjual>
            3. JANGAN PERNAH mengarang jawaban, berhalusinasi, atau memberikan janji promo/harga di luar daftar yang diberikan penjual.
            4. Gunakan bahasa Indonesia yang ramah, sopan, dan ringkas. Boleh menyertakan tanda pengenal "-{bot_name}" di akhir jawaban jika relevan.
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
                    msg = choices[0]["message"]
                    content = msg.get("content")
                    if not content and msg.get("reasoning"):
                        content = msg.get("reasoning")
                    if content and isinstance(content, str):
                        return content.strip()
                raise ValueError("Format respons OpenRouter tidak sesuai yang diharapkan.")

            elif response.status_code in (404, 429, 502, 503, 504):
                logger.warning(
                    f"Model {model_name} mengembalikan status {response.status_code} ({response.text[:100]}). Mencoba fallback berikutnya..."
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


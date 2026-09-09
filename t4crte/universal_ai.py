import os
import time
import json
import requests
import pandas as pd
from typing import Dict, Any, Optional
from ai_advisor import AIAnalysisResult, AIAdvisor

AI_PRESETS = {
    "deepseek": {
        "name": "DeepSeek API",
        "base_url": "https://api.deepseek.com/v1",
        "default_model": "deepseek-chat",
        "info": "أحد أقوى النماذج للتحليل المنطقي والرياضيات وبتكلفة منخفضة جداً"
    },
    "openrouter": {
        "name": "OpenRouter (بوابة النماذج الشاملة)",
        "base_url": "https://openrouter.ai/api/v1",
        "default_model": "google/gemini-2.0-flash-001",
        "info": "يتيح الوصول لمئات النماذج بمفتاح واحد (بما في ذلك نماذج مجانية تماماً)"
    },
    "groq": {
        "name": "Groq (فائق السرعة)",
        "base_url": "https://api.groq.com/openai/v1",
        "default_model": "llama-3.3-70b-versatile",
        "info": "استجابة فائقة السرعة خلال أجزاء من الثانية مع باقة مجانية كريمة"
    },
    "gemini": {
        "name": "Google Gemini (الواجهة المتوافقة)",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "default_model": "gemini-2.0-flash",
        "info": "باقة مجانية ممتازة من Google AI Studio"
    },
    "openai": {
        "name": "OpenAI (ChatGPT)",
        "base_url": "https://api.openai.com/v1",
        "default_model": "gpt-4o-mini",
        "info": "نماذج OpenAI الرسمية (GPT-4o / GPT-4o-mini)"
    },
    "ollama": {
        "name": "Ollama / LM Studio (محلي على جهازك مجاناً)",
        "base_url": "http://localhost:11434/v1",
        "default_model": "llama3.2",
        "info": "يعمل محلياً بدون إنترنت وبدون أي مفاتيح API خارجية"
    },
    "custom": {
        "name": "رابط مخصص (Custom Endpoint)",
        "base_url": "https://api.example.com/v1",
        "default_model": "custom-model",
        "info": "أي خادم متوافق مع معايير OpenAI REST API"
    },
    "quant_builtin": {
        "name": "المحرك الكمي المدمج (خوارزمي مجاني بدون مفاتيح)",
        "base_url": "",
        "default_model": "internal-quant",
        "info": "تحليل فني كمي سريع ومبني محلياً في البوت مجاناً 100%"
    }
}

class UniversalAIClient:
    """
    العميل الشامل لربط أي نموذج ذكاء اصطناعي من أي مزود
    باستخدام بروتوكول OpenAI-Compatible REST API
    """

    @staticmethod
    def test_connection(base_url: str, api_key: str, model_name: str) -> Dict[str, Any]:
        """
        اختبار فوري للاتصال بالنموذج وقياس سرعة الاستجابة
        """
        if not base_url or not base_url.strip():
            return {"success": False, "error": "يرجى إدخال رابط الـ API الأساسي (Base URL)"}

        # Normalize URL
        url = base_url.rstrip("/")
        if not url.endswith("/chat/completions"):
            url += "/chat/completions"

        headers = {
            "Content-Type": "application/json",
        }
        if api_key and api_key.strip():
            headers["Authorization"] = f"Bearer {api_key.strip()}"

        payload = {
            "model": model_name.strip(),
            "messages": [
                {
                    "role": "system",
                    "content": "You are a crypto trading AI assistant. Respond in Arabic in 1 short sentence confirming connection."
                },
                {
                    "role": "user",
                    "content": "أكد نجاح الاتصال بك واذكر اسمك وطبيعة عملك."
                }
            ],
            "max_tokens": 100,
            "temperature": 0.3
        }

        start_time = time.time()
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=12)
            elapsed_ms = int((time.time() - start_time) * 1000)

            if resp.status_code == 200:
                data = resp.json()
                content = data['choices'][0]['message']['content'].strip()
                return {
                    "success": True,
                    "latency_ms": elapsed_ms,
                    "model": model_name,
                    "reply": content
                }
            else:
                return {
                    "success": False,
                    "status_code": resp.status_code,
                    "error": f"فشل الاتصال (كود {resp.status_code}): {resp.text[:300]}"
                }
        except requests.exceptions.Timeout:
            return {"success": False, "error": "انتهت مهلة الانتظار (Timeout) - تأكد من صحة الرابط أو سرعة الخادم"}
        except requests.exceptions.ConnectionError:
            return {"success": False, "error": f"تعذر الوصول إلى الرابط: {url} - تأكد من اتصال الإنترنت أو تشغيل الخادم المحلي"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    @classmethod
    def analyze_market_with_llm(
        cls,
        candles_df: pd.DataFrame,
        pair: str,
        base_url: str,
        api_key: str,
        model_name: str,
        take_profit_pct: float = 1.8,
        stop_loss_pct: float = 1.2
    ) -> AIAnalysisResult:
        """
        إرسال ملخص الشموع والمؤشرات للذكاء الاصطناعي ليصدر تحليلاً وتوصية دقيقة بصيغة JSON
        """
        # Fallback to internal quant if no key or quant is selected
        if not api_key or not base_url or not model_name:
            return AIAdvisor.analyze(candles_df, pair, take_profit_pct, stop_loss_pct)

        if candles_df.empty or len(candles_df) < 25:
            return AIAdvisor.analyze(candles_df, pair, take_profit_pct, stop_loss_pct)

        last_row = candles_df.iloc[-1]
        prev_row = candles_df.iloc[-2]

        current_price = float(last_row['close'])
        rsi = float(last_row['rsi'])
        ema_9 = float(last_row['ema_9'])
        ema_21 = float(last_row['ema_21'])
        ema_50 = float(last_row['ema_50'])
        ema_200 = float(last_row.get('ema_200', ema_50))
        bb_upper = float(last_row['bb_upper'])
        bb_lower = float(last_row['bb_lower'])
        volume_ratio = float(last_row.get('volume_ratio', 1.0))

        # Build market facts prompt
        market_summary = f"""
الزوج: {pair}
السعر الحالي: {current_price:.2f}$
مؤشر القوة النسبية RSI(14): {rsi:.2f}
المتوسط الأسي EMA 9: {ema_9:.2f}
المتوسط الأسي EMA 21: {ema_21:.2f}
المتوسط الأسي EMA 50 (الاتجاه): {ema_50:.2f}
المتوسط الأسي EMA 200: {ema_200:.2f}
نطاق بولينجر العلوي: {bb_upper:.2f}
نطاق بولينجر السفلي: {bb_lower:.2f}
نسبة حجم التداول إلى المتوسط (Volume Ratio): {volume_ratio:.2f}
رأس المال المخصص: 4 دولارات (تداول فوري بدون رافعة مالية)
الهدف الربحي المقترح: +{take_profit_pct}%
وقف الخسارة المسموح: -{stop_loss_pct}%
"""

        system_prompt = """
أنت خبير كمي استراتيجي في التداول الفوري للعملات المشفرة (Spot Trading Quantitative AI).
مهمتك حماية رأس المال الصغير (4 دولارات) وتحقيق أرباح تراكمية بنسبة مخاطرة شبه معدومة.
لا تنصح بالشراء إلا عند توافر أسباب فنية قاطعة تشير لارتداد صاعد آمن ومحمي.

يجب أن ترد دائماً وأبداً فقط بصيغة JSON نظيفة بدون أي علامات أخرى:
{
  "signal": "BUY" أو "SELL" أو "HOLD",
  "confidence": رقم صحيح من 1 إلى 100,
  "safety_score": رقم صحيح من 1 إلى 100,
  "market_sentiment": "صاعد قوي" أو "صاعد معتدل" أو "هابط" أو "تذبذب عرضي",
  "arabic_summary": "جملة واحدة تلخص الموقف الفني بدقة",
  "detailed_advice": "نصيحة موجهة للمتداول تشرح الإجراء المناسب والأهداف",
  "reasons": ["السبب الفني 1", "السبب الفني 2", "السبب الفني 3"]
}
"""

        url = base_url.rstrip("/")
        if not url.endswith("/chat/completions"):
            url += "/chat/completions"

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key.strip()}"
        }

        payload = {
            "model": model_name.strip(),
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": market_summary}
            ],
            "max_tokens": 800,
            "temperature": 0.2,
            "reasoning_effort": "max"
        }

        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=12)
            if resp.status_code == 200:
                text = resp.json()['choices'][0]['message']['content'].strip()
                # Clean markdown backticks if any
                if text.startswith("```json"):
                    text = text[7:]
                if text.startswith("```"):
                    text = text[3:]
                if text.endswith("```"):
                    text = text[:-3]
                
                parsed = json.loads(text.strip())
                signal = parsed.get("signal", "HOLD").upper()
                if signal not in ["BUY", "SELL", "HOLD"]:
                    signal = "HOLD"

                signal_map = {
                    "BUY": "شراء مؤكد 🟢",
                    "SELL": "بيع / جني أرباح 🔴",
                    "HOLD": "مراقبة وانتظار 🟡"
                }

                tp = current_price * (1 + (take_profit_pct / 100))
                sl = current_price * (1 - (stop_loss_pct / 100))

                return AIAnalysisResult(
                    signal=signal,
                    signal_arabic=signal_map.get(signal, "مراقبة وانتظار 🟡"),
                    confidence=int(parsed.get("confidence", 70)),
                    safety_score=int(parsed.get("safety_score", 85)),
                    market_sentiment=parsed.get("market_sentiment", "محايد"),
                    current_price=current_price,
                    recommended_tp=tp,
                    recommended_sl=sl,
                    reasons=parsed.get("reasons", ["تحليل فني مستند إلى قراءات النموذج"]),
                    arabic_summary=parsed.get("arabic_summary", "تم تحليل السوق بواسطة النموذج."),
                    detailed_advice=parsed.get("detailed_advice", "التزم بإدارة المخاطر.")
                )
        except Exception as e:
            print(f"Universal AI Call Error (Falling back to Quant engine): {e}")

        # Fallback to robust algorithmic engine
        return AIAdvisor.analyze(candles_df, pair, take_profit_pct, stop_loss_pct)

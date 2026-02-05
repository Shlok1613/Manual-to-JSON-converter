import os
import json
from dotenv import load_dotenv
from google import genai
from google.genai import types
import re
from google.genai.errors import ClientError

# Load environment variables
load_dotenv()
client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))

def extract_specifications(text: str):
    """
    Extract structured specifications from product manual text using Gemini.
    Falls back to text-based key–value parsing if JSON decoding fails.
    """
    prompt = f"""
    You are an expert in interpreting industrial testing manuals.

    The text below contains product testing instructions written by engineers.
    They may be written inconsistently — sometimes as sentences, sometimes as tables.

    Your task:
    1. Identify every TEST STEP or ACTION described (e.g., "Switch on Switch 1 so Bulb 1 glows").
    2. Interpret each step as a structured JSON entry with these keys:
       - "Action" : what the user does (e.g., "Switch ON Switch 1")
       - "Expected Behavior" : what happens (e.g., "Bulb 1 Glows")
       - "Relay Status" : ON / OFF / No Change (if mentioned)
       - "LED Indicator" : ON / OFF / Blinking / Not Mentioned
       - "Delay" : timing or condition delay (if mentioned)
       - "Condition Type" : Healthy, Faulty, Recovery, etc. (if applicable)
    3. Also include general product specifications (voltage, delay, etc.) in a separate section.

    Return a single JSON object with two keys:
    {{
      "Specifications": {{ ... }},
      "TestSteps": [
         {{
           "Action": "...",
           "Expected Behavior": "...",
           "Relay Status": "...",
           "LED Indicator": "...",
           "Delay": "...",
           "Condition Type": "..."
         }}
      ]
    }}

    Respond ONLY in JSON format.
    Text:
    {text[:8000]}
"""


    # --- AI Call ---
    try:
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt,
            config=types.GenerateContentConfig(temperature=0)
        )
        print("[Gemini Output Preview]:", response.text[:500])  # Debug log

        output_text = response.text.strip()

        # --- Try loading as JSON ---
        try:
            structured_data = json.loads(output_text)
        except json.JSONDecodeError:
            # --- Fallback: parse as simple key-value pairs ---
            structured_data = {}
            lines = [ln.strip() for ln in output_text.splitlines() if ln.strip()]
            for line in lines:
                # Example matches: "Under Voltage: 194–214 VAC", "Over Voltage - 254–274 VAC"
                match = re.match(r"([\w\s%/()]+)\s*[:\-–]\s*(.+)", line)
                if match:
                    key, val = match.groups()
                    structured_data[key.strip()] = val.strip()
            if not structured_data:
                structured_data = {"raw_output": output_text}
            
    except ClientError as e:
                # 🔴 DO NOT crash your API
        return {
            "error": "AI_QUOTA_EXCEEDED",
            "message": "Gemini quota exhausted. Returning raw extracted text only."
        }

    return structured_data

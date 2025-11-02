import os
import json
from dotenv import load_dotenv
from google import genai
from google.genai import types

# Load environment variables
load_dotenv()
client = genai.Client(api_key=os.getenv("GOOGLE_API_KEY"))

def extract_specifications(text: str):
    """
    Extracts structured specifications from product manual text using Gemini.
    """
    prompt = f"""
You are an expert in industrial product documentation.
Extract all key specifications from the following text and return them
as a clean JSON object only — no extra text or explanation.

Use consistent keys like Rated Voltage, Frequency, Power, Current, Operating Range, etc.

Example output:
{{
    "Rated Voltage": "230 V AC",
    "Operating Range": "220–240 V",
    "Frequency": "50 Hz"
}}

Text:
{text[:6000]}
"""

    # Generate content using Gemini
    response = client.models.generate_content(
        model="gemini-2.0-flash",  # or "gemini-1.5"
        contents=prompt,
        config=types.GenerateContentConfig(temperature=0)
    )

    output_text = response.text.strip()

    # Parse JSON if possible
    try:
        structured_data = json.loads(output_text)
    except json.JSONDecodeError:
        structured_data = {"raw_output": output_text}

    return structured_data

import os
from pathlib import Path

from sarvamai import SarvamAI

if "SARVAM_API_KEY" not in os.environ:
    for line in Path(__file__).with_name(".env").read_text(encoding="utf-8").splitlines():
        name, separator, value = line.partition("=")
        if separator and name.strip() == "SARVAM_API_KEY":
            os.environ["SARVAM_API_KEY"] = value.strip().strip("\"'")
            break

api_key = os.getenv("SARVAM_API_KEY")
if not api_key:
    raise SystemExit("Set SARVAM_API_KEY in the environment before running.")

client = SarvamAI(api_subscription_key=api_key)
response = client.chat.completions(
    model="sarvam-105b-conversations",
    messages=[{"role": "user", "content": "Reply with a short greeting."}],
)
print(response.choices[0].message.content)
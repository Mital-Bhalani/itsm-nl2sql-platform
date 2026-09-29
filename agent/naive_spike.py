# Deliberately naive NL2SQL spike: no schema context, no guardrails, no validation, no execution.
import importlib
import os


def get_openai_client():
	try:
		openai_module = importlib.import_module("openai")
	except ModuleNotFoundError as exc:
		raise RuntimeError("The 'openai' package is required. Install it with: pip install openai") from exc
	return openai_module.OpenAI()


# Read basic .env entries without requiring python-dotenv.
env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
if os.path.isfile(env_path):
	with open(env_path, encoding="utf-8") as env_file:
		for line in env_file:
			line = line.strip()
			if line and not line.startswith("#") and "=" in line:
				key, value = line.split("=", 1)
				os.environ.setdefault(key.strip(), value.strip().strip("\"'"))

question = "which assignment groups breached SLA most last month ?"
client = get_openai_client()  # reads OPENAI_API_KEY from the environment / .env
reply = client.chat.completions.create(model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"), messages=[{"role": "user", "content": f"Write a SQL query to answer: {question}"}])
print(reply.choices[0].message.content)

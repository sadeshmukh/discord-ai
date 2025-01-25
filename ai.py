# ollama support?

# dotenv should be loaded in the main file, not in the module

import itertools
import json
import logging
import os
import ollama
from google.generativeai import configure as configure_google
from google.generativeai.types import HarmBlockThreshold
import google.generativeai as genai
from anthropic import AsyncAnthropic
from openai import AsyncOpenAI
from asyncio import to_thread
import itertools

with open("models.json") as f:
    MODELS = json.load(f).get("providers")

# models structur:
"""
{
    "providers": {
      "openai": [
          "gpt-3.5-turbo",
      ]
    }

"""

ollama_client = ollama.AsyncClient()
configure_google(api_key=os.getenv("GEMINI_API_KEY"))
google_client = genai.GenerativeModel("gemini-1.5-flash") # hardcoded model unfortunately for now
anthropic_client = AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
openai_client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))


class ChatProvider():
    def __init__(self, provider, model=None):
        self.provider = provider
        self.model = model
    def set_model(self, model):
        if model not in self.available_models(self.provider):
            # swap provider
            if model in itertools.chain.from_iterable(self.available_models().values()):
                self.provider = next(key for key, value in MODELS.items() if model in value)
        self.model = model
    def set_provider(self, provider):
        self.provider = provider
    def available_models(self, filter_provider=None):
        return list(itertools.chain.from_iterable([f"{provider}|{submodel}" for submodel in submodels] for provider, submodels in MODELS.items())) if not filter_provider else MODELS.get(filter_provider)
    def get_config(self):
        return {
            "provider": self.provider,
            "model": self.model
        }

    async def generate_text(self, history, override_provider=None, override_model=None, usage=False):
        provider = override_provider if override_provider else self.provider
        model = override_model if override_model else self.model
        if not model and not self.provider == "google":
            raise ValueError("Model not set for provider")
        usage_dict = {"input": 0, "output": 0}
        response_text = "There was an error."
        if provider == "ollama":
            try:
                res = await ollama_client.chat(model=model, messages=history)
            except Exception as e:
                logging.error(e)
                if usage:
                    return usage_dict, response_text
                return response_text
            response_text = res.get("message", {}).get("content", "There was an error.")
            usage_dict["input"] = res.get("prompt_eval_count", 0)
            usage_dict["output"] = res.get("eval_count", 0)
            if usage["input"] == 0 or usage["output"] == 0:
                logging.warning("No usage data returned")
        if provider == "google":
            if len(history) == 1 and history[0].get("role") == "system":
                if usage:
                    return usage_dict, response_text
                return response_text
            google_history = [
                {
                    "parts": [{"text": message.get("content")}], 
                    "role": "user" if message.get("role") == "user" else "model"
                    } 
                    for message in history]
            logging.debug(google_history)
            try:
                res = await google_client.generate_content_async(google_history, safety_settings=HarmBlockThreshold.BLOCK_NONE, generation_config={"max_output_tokens": 1000, "stop_sequences": ["<END>"]})
            except Exception as e:
                logging.error(e)
                if usage:
                    return usage_dict, response_text
                return response_text
            if res.prompt_feedback:
                logging.warning(res.prompt_feedback)
            if not res.candidates or not res.candidates[0] or not res.candidates[0].content.parts:
                logging.error("No parts returned")
                logging.error(res)
                
                response_text = "There was an error."
            else:
                usage_dict["input"] = res.usage_metadata.prompt_token_count
                usage_dict["output"] = res.usage_metadata.candidates_token_count
                response_text = " ".join([part.text for part in res.candidates[0].content.parts])
        if provider == "anthropic":
            res = await anthropic_client.messages.create(
                messages=history,
                model=model,
                max_tokens=1000
            )
            logging.debug(res)
            response_text = res.content
        if provider == "openai":
            res = await openai_client.chat.completions.create(
                model=model,
                messages=history
            )
            logging.debug(res)
            response_text = res.choices[0].message.content
        if usage:
            return usage_dict, response_text
        return response_text
    async def emoji_summary(history):
        pass # TODO: summarize convo with singular emojis
        
        
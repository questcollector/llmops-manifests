import gradio as gr
import os
from openai import OpenAI
from urllib.parse import urljoin

INFERENCE_SERVICE = os.environ["INFERENCE_SERVICE"]
MODLE_NAME = os.environ["MODEL_NAME"]
API_KEY = os.environ["API_KEY"]

client = OpenAI(
    base_url=urljoin(INFERENCE_SERVICE, "v1"), 
    api_key=API_KEY,
    default_headers={
        "Content-Type": "application/json",
    })
SYSTEM = os.environ["SYSTEM_PROMPT"]

def inference(message, history):
    history_openai_format = [{"role": "system", "content": SYSTEM}]
    for user, assistant in history:
        history_openai_format.append({"role": "user", "content": user})
        history_openai_format.append({"role": "assistant", "content": assistant})
    history_openai_format.append({"role": "user", "content": message})
 
    chat_completion = client.chat.completions.create(
        model=MODLE_NAME,
        messages=history_openai_format,
        stream=True
    )
    partial_message = ""
    for chunk in chat_completion:
        if chunk.choices[0].delta.content is not None:
            partial_message = partial_message + chunk.choices[0].delta.content
            yield partial_message
 
def gradio():
    gr.ChatInterface(fn=inference).launch()
 
if __name__ == "__main__":
    gradio()
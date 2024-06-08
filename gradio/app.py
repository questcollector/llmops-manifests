import gradio as gr
import os
from openai import OpenAI
from urllib.parse import urljoin

from dotenv import load_dotenv

load_dotenv()

INFERENCE_SERVICE = os.environ["INFERENCE_SERVICE"]
MODLE_NAME = os.environ["MODEL_NAME"]
AUTHSERVICE_COOKIE = os.environ["AUTHSERVICE_COOKIE"]
client = OpenAI(
    base_url=urljoin(INFERENCE_SERVICE, "v1"), 
    api_key="-",
    default_headers={
        "Content-Type": "application/json",
        "Cookie": f"authservice_session={AUTHSERVICE_COOKIE}"
    })

def inference(message, history):
    history_openai_format = [{"role": "system", "content": "당신은 K-pop 아이돌 그룹 뉴진스(NewJeans)의 정보를 알려주는 멋진 AI 어시스턴트입니다. 모든 대화는 한국어(Korean)로 합니다."}]
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
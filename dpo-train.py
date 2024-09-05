from transformers import (
    logging,
    AutoTokenizer,
    AutoModelForCausalLM,
    HfArgumentParser,
)
from trl import (
    DPOConfig, 
    DPOTrainer,
)
from peft import LoraConfig, TaskType, PeftModel
import torch
import numpy as np

import os
from datasets import load_from_disk
from typing import Dict, Optional
from dataclasses import dataclass, field

## NCCL log level
os.environ["NCCL_DEBUG"] = 'INFO'
## transformers log level
logging.set_verbosity_debug()

## TraingArguments
@dataclass
class ScriptArguments:
    model_path: Optional[str] = field(default="meta-llama/Llama-2-7b-hf", metadata={"help": "the model path"})
    sft_adapter_path: Optional[str] = field(default="meta-llama/Llama-2-7b-hf", metadata={"help": "the sft lora adapter path"})
    dataset_path: Optional[str] = field(default="lvwerra/stack-exchange-paired", metadata={"help": "the dataset path"})

    # LoraConfig
    lora_alpha: Optional[float] = field(default=16, metadata={"help": "the lora alpha parameter"})
    lora_dropout: Optional[float] = field(default=0.05, metadata={"help": "the lora dropout parameter"})
    lora_r: Optional[int] = field(default=8, metadata={"help": "the lora r parameter"})

parser = HfArgumentParser((ScriptArguments, DPOConfig))
script_args, training_args = parser.parse_args_into_dataclasses()

## peft
peft_config = LoraConfig(
    task_type=TaskType.CAUSAL_LM,
    r=script_args.lora_r,
    lora_alpha=script_args.lora_alpha,
    lora_dropout=script_args.lora_dropout,
    use_rslora=True,
)

## load dataset, tokenizer, model
tokenizer = AutoTokenizer.from_pretrained(script_args.model_path, trust_remote_code=True)
tokenizer.pad_token = tokenizer.eos_token
tokenizer.padding_side = "right"

SYSTEM = """당신은 원영적 사고를 하는 지능형 어시스턴트입니다. 원영적 사고란 단순 긍정적인 사고를 넘어 초월적인 긍정적 사고 방식이며, 자신에게 일어나는 모든 사건이 궁극적으로 긍정적인 결과로 귀결될 것이라는 확고한 낙관주의를 기반으로 두고 있습니다. 
즉, 나에게 일어나는 모든 일은 결국 나에게 좋은 일이라는 것입니다. 다만, 부정적인 감정을 회피하고 거부하는 것이 아니며, 부정적인 현실과 감정도 긍정적인 결과에 이르는 과정으로 받아들인다는 차이점이 있습니다.
예를 들어, 갑자기 비가 온 상황에서, 비가 왔지만 나는 춥지 않고 행복하다라며 춥다는 부정적인 감각을 부정하는 것이 아니라, 추운 것은 맞지만 오히려 운치있는 빗소리를 들을 수 있으니까 운이 좋다. 즉 궁극적으로 긍정적인 결과로 이르게 되는 원인으로 해석하는 것입니다.
이어지는 문장에서 나타는 상황에 대해 원영적 사고로 해석하는 역할을 수행합니다. emoji를 적극적으로 사용합니다."""

def return_prompt_and_responses(samples) -> Dict[str, str]:
    ## apply chat template
    prompt_messages = [
        [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": prompt}
        ] for prompt in samples["prompt"]
    ]
    return {
        "prompt": [ tokenizer.apply_chat_template(chat_template, tokenize=False) for chat_template in prompt_messages ],
        "chosen": [ f"<|start_header_id|>assistant<|end_header_id|>\n\n{chosen}<|eot_id|>" for chosen in samples["chosen"]],
        "rejected": [ f"<|start_header_id|>assistant<|end_header_id|>\n\n{rejected}<|eot_id|>" for rejected in samples["rejected"]],
    }
dataset = load_from_disk(script_args.dataset_path)
# dataset = dataset['train'].train_test_split(test_size=10, train_size=100)
dataset = dataset['train'].train_test_split(test_size=0.1)
dataset = dataset.map(
    return_prompt_and_responses, 
    batched=True, 
    remove_columns=dataset["train"].column_names
)
train_data, valid_data = (dataset['train'], dataset['test'])
train_data = train_data.filter(
    lambda r: len(r["prompt"]) + len(r["chosen"]) <= training_args.max_length
    and len(r["prompt"]) + len(r["rejected"]) <= training_args.max_length
)
valid_data = valid_data.filter(
    lambda r: len(r["prompt"]) + len(r["chosen"]) <= training_args.max_length
    and len(r["prompt"]) + len(r["rejected"]) <= training_args.max_length
)

model = AutoModelForCausalLM.from_pretrained(
    script_args.model_path,
    trust_remote_code=True,
    torch_dtype=torch.bfloat16,
)
model.config.use_cache = False
model.config.pretraining_tp = 1
model = PeftModel.from_pretrained(model, script_args.sft_adapter_path, is_trainable=True, adapter_name=training_args.model_adapter_name)

model.load_adapter(script_args.sft_adapter_path, adapter_name=training_args.ref_adapter_name)

trainer = DPOTrainer(
    args=training_args,
    model=model,
    tokenizer=tokenizer,
    train_dataset=train_data,
    eval_dataset=valid_data,
    # peft_config=peft_config,
    ref_model=None,
)

trainer.model.print_trainable_parameters()
trainer.train()
trainer.save_model()

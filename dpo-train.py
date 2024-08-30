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
from peft import LoraConfig, TaskType
import torch
import evaluate
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

# metric
metric = evaluate.load('accuracy', module_type="metric")
def compute_metrics(eval_pred):
    predictions, labels = eval_pred
    predictions = np.argmax(predictions, axis=1)
    acc = metric.compute(predictions=predictions, references=labels)
    return {{'accuracy': acc}}

## load dataset, tokenizer, model
def return_prompt_and_responses(samples) -> Dict[str, str]:
    return {
        "prompt": [f"### SYSTEM: {system}\n\n### QUESTION: {question}\n\n### ANSWER:" for system, question in zip(samples["system"], samples["question"])],
        "chosen": samples["chosen"],
        "rejected": samples["rejected"],
    }
dataset = load_from_disk(script_args.dataset_path)
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

tokenizer = AutoTokenizer.from_pretrained(script_args.model_path, trust_remote_code=True)
tokenizer.pad_token = tokenizer.eos_token
tokenizer.padding_side = "right"

model = AutoModelForCausalLM.from_pretrained(
    script_args.model_path,
    trust_remote_code=True,
    torch_dtype=torch.bfloat16,
)
model.config.use_cache = False
model.config.pretraining_tp = 1

trainer = DPOTrainer(
    args=training_args,
    model=model,
    tokenizer=tokenizer,
    train_dataset=train_data,
    eval_dataset=valid_data,
    peft_config=peft_config,
    ref_model=None,
    compute_metrics=compute_metrics,    
)

trainer.model.print_trainable_parameters()
trainer.train()
trainer.save_model()

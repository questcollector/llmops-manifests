from transformers import (
    logging,
    AutoTokenizer,
    AutoModelForCausalLM,
    HfArgumentParser,
)
from trl import (
    SFTTrainer,
    SFTConfig
)
from datasets import load_from_disk
from peft import LoraConfig, TaskType
import torch
import torch.distributed as dist
import evaluate
import numpy as np

from dataclasses import dataclass, field
from typing import Optional
import os

## current script path
dirname = os.path.dirname(__file__)
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

parser = HfArgumentParser((ScriptArguments, SFTConfig))
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
def prepare_sample_text(example):
    """Prepare the text from a sample of the dataset."""
    text = f"### SYSTEM: {example['system']}\n\n### QUESTION: {example['question']}\n\n### ANSWER: {example['chosen']}"
    return text

dataset = load_from_disk(script_args.dataset_path)
train_data, valid_data = (dataset['train'], dataset['test'])

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

## trainer
trainer = SFTTrainer(
    args=training_args,
    model=model,
    tokenizer=tokenizer,
    train_dataset=train_data,
    eval_dataset=valid_data,
    peft_config=peft_config,
    formatting_func=prepare_sample_text,
    compute_metrics=compute_metrics,
)

trainer.model.print_trainable_parameters()
trainer.train()
trainer.save_model()
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
from datasets import load_dataset
from peft import LoraConfig, TaskType
import torch
import torch.distributed as dist
import mlflow
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
    model_path: Optional[str] = field(default="unsloth/Meta-Llama-3.1-8B-Instruct", metadata={"help": "the model path"})
    train_dataset_path: Optional[str] = field(default="Junnos/luckyvicky-DPO", metadata={"help": "the train dataset path"})
    eval_dataset_path: Optional[str] = field(default="Junnos/luckyvicky-DPO", metadata={"help": "the eval dataset path"})
    training_job_name: Optional[str] = field(default="sft-train", metadata={"help": "training job name"})
    training_job_id: Optional[str] = field(default="abcde", metadata={"help": "training job id"})
    system_prompt: Optional[str] = field(default="system prompt", metadata={"help": "system prompt"})

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

metric = evaluate.load("accuracy")
def compute_metrics(eval_preds):
    logits, labels = eval_preds
    predictions = np.argmax(logits, axis=-1)
    for pred, refs in zip(predictions, labels):
        metric.add_batch(predictions=pred, references=refs)
    return metric.compute()

train_dataset = load_dataset("json", data_files=script_args.train_dataset_path)['train']
if script_args.eval_dataset_path is not None:
    eval_dataset = load_dataset("json", data_files=script_args.eval_dataset_path)['train']

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
    train_dataset=train_dataset,
    eval_dataset=eval_dataset if script_args.eval_dataset_path is not None else None,
    peft_config=peft_config,
    compute_metrics=compute_metrics,
)

## mlflow
os.environ["MLFLOW_EXPERIMENT_NAME"] = script_args.training_job_name
os.environ["MLFLOW_FLATTEN_PARAMS"] = "1"
os.environ["MLFLOW_TRACKING_URI"]="http://mlflow.mlflow"
os.environ["MLFLOW_S3_ENDPOINT_URL"]="http://minio-service.kubeflow:9000"
os.environ["MLFLOW_S3_IGNORE_TLS"]="true"

# create mlflow run in master
if dist.get_rank() == 0:
    mlflow.set_tracking_uri(os.environ["MLFLOW_TRACKING_URI"])
    mlflow.set_experiment(os.environ["MLFLOW_EXPERIMENT_NAME"])
    mlflow.start_run(run_name=script_args.training_job_id)
    mlflow.log_param("system_prompt", script_args.system_prompt)

trainer.model.print_trainable_parameters()
trainer.train()
trainer.save_model()

## mlflow log model and end run
if dist.get_rank() == 0:
    mlflow.transformers.log_model(
        transformers_model={
            "model": trainer.model,
            "tokenizer": tokenizer,
        },
        artifact_path="model",
        task="text-generation"
    )
    mlflow.end_run()
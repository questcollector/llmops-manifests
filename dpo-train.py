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
import torch.distributed as dist
import mlflow

import os
from datasets import load_dataset
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
    training_job_name: Optional[str] = field(default="sft-train", metadata={"help": "training job name"})
    training_job_id: Optional[str] = field(default="abcde", metadata={"help": "training job id"})
    system_prompt: Optional[str] = field(default="system prompt", metadata={"help": "system prompt"})

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

dataset = load_dataset("json", data_files=script_args.dataset_path)['train']
dataset = dataset.filter(
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

trainer = DPOTrainer(
    args=training_args,
    model=model,
    tokenizer=tokenizer,
    train_dataset=dataset,
)

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
import mlflow.data.huggingface_dataset
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
import boto3
from urllib.parse import urlparse

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
    train_dataset_uri: Optional[str] = field(default="Junnos/luckyvicky-DPO", metadata={"help": "the train dataset path"})
    eval_dataset_uri: Optional[str] = field(default="Junnos/luckyvicky-DPO", metadata={"help": "the eval dataset path"})
    training_job_name: Optional[str] = field(default="sft-train", metadata={"help": "training job name"})
    training_job_id: Optional[str] = field(default="vicky", metadata={"help": "training job id"})
    per_device_train_batch_size: Optional[int] = field(default=4, metadata={"help": "batch size for training"})
    per_device_eval_batch_size: Optional[int] = field(default=4, metadata={"help": "batch size for evaluation"})
    num_train_epochs: Optional[int] = field(default=10, metadata={"help": "number of training epochs"})
    deepspeed: Optional[str] = field(default="deepspeed.json", metadata={"help": "training job id"})

    # LoraConfig
    lora_alpha: Optional[float] = field(default=16, metadata={"help": "the lora alpha parameter"})
    lora_dropout: Optional[float] = field(default=0.05, metadata={"help": "the lora dropout parameter"})
    lora_r: Optional[int] = field(default=8, metadata={"help": "the lora r parameter"})

parser = HfArgumentParser(ScriptArguments)
script_args = parser.parse_args_into_dataclasses()

# SFTConfig
output_dir = os.path.join(
    script_args.mount_path, 
    f"{script_args.job_name}-{script_args.job_id}"
)
training_args = SFTConfig(
    output_dir=output_dir,
    per_device_train_batch_size=script_args.per_device_train_batch_size,
    per_device_eval_batch_size=script_args.per_device_eval_batch_size,
    num_train_epochs=script_args.num_train_epochs,
    deepspeed=script_args.deepspeed,
    gradient_accumulation_steps=4,
    eval_strategy="epoch",
    logging_steps=1,
    log_level="info",
    report_to=["tensorboard","mlflow"],
    warmup_ratio=0.1,
    learning_rate=2e-4,
    lr_scheduler_type="cosine",
    bf16=True,
    gradient_checkpointing=True,
    gradient_checkpointing_kwargs={"use_reentrant":False},
    max_seq_length=1024,
    packing=True,
    eval_on_start=True,
    disable_tqdm=True,
)

## LoRA
peft_config = LoraConfig(
    task_type=TaskType.CAUSAL_LM,
    r=script_args.lora_r,
    lora_alpha=script_args.lora_alpha,
    lora_dropout=script_args.lora_dropout,
    use_rslora=True,
)

# eval metric
metric = evaluate.load("accuracy")
def compute_metrics(eval_preds):
    logits, labels = eval_preds
    predictions = np.argmax(logits, axis=-1)
    for pred, refs in zip(predictions, labels):
        metric.add_batch(predictions=pred, references=refs)
    return metric.compute()

## get dataset
minio_endpoint = "http://minio-service.kubeflow:9000"
minio_client = boto3.client("s3", endpoint_url=minio_endpoint,
                            aws_access_key_id=os.environ["AWS_ACCESS_KEY_ID"],
                            aws_secret_access_key=os.environ["AWS_SECRET_ACCESS_KEY"])
def download_object_and_convert_to_dataset(minio_client, url):
    # parse minio object url
    parsed_url = urlparse(url)
    bucket, key = (parsed_url.netloc, parsed_url.path)

    # download minio object
    temp_dir = os.path.dirname(__file__)
    temp_file = os.path.basename(key)
    file_path = os.path.join(temp_dir, temp_file)
    minio_client.download_file(bucket, key, file_path)

    # load dataset from jsonl format data file
    dataset = load_dataset("json", data_files=file_path)
    return dataset['train']

print(f"train dataset uri: {script_args.train_dataset_uri}")
print(f"eval dataset uri: {script_args.eval_dataset_uri}")

train_dataset = download_object_and_convert_to_dataset(minio_client, script_args.train_dataset_uri)
eval_dataset = download_object_and_convert_to_dataset(minio_client, script_args.eval_dataset_uri)

# get tokenizer and model
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
    eval_dataset=eval_dataset,
    peft_config=peft_config,
    compute_metrics=compute_metrics,
)

## mlflow config
os.environ["MLFLOW_EXPERIMENT_NAME"] = script_args.training_job_name
os.environ["MLFLOW_FLATTEN_PARAMS"] = "1"
os.environ["MLFLOW_TRACKING_URI"]="http://mlflow.mlflow"
os.environ["MLFLOW_S3_ENDPOINT_URL"]=minio_endpoint
os.environ["MLFLOW_S3_IGNORE_TLS"]="true"

# create mlflow run in master
if dist.get_rank() == 0:
    mlflow.set_tracking_uri(os.environ["MLFLOW_TRACKING_URI"])
    mlflow.set_experiment(os.environ["MLFLOW_EXPERIMENT_NAME"])
    mlflow.start_run(run_name=script_args.training_job_id)
    train_dataset_for_log = mlflow.data.huggingface_dataset.from_huggingface(train_dataset)
    eval_dataset_for_log = mlflow.data.huggingface_dataset.from_huggingface(eval_dataset)
    mlflow.log_input(train_dataset_for_log,context="training")
    mlflow.log_input(eval_dataset_for_log,context="testing")

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